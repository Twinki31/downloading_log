import gzip
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from filtering import Rule
from operations import process_local_log, process_s3_log
from operation_state import OperationCancelled, OperationController


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / "2026_09_24_12.tsv.gz"
        self.destination = self.root / "result.tsv"
        self.rules = [Rule("banner_id", "Одно из значений", ("208684",))]

    def download_valid_archive(self):
        with gzip.open(self.archive, "wt", encoding="utf-8") as output:
            output.write("banner_id\n208684\n9\n")
        return self.archive

    def test_keep_raw_leaves_downloaded_archive(self):
        result, removed, existed_before = process_s3_log(
            self.archive, self.destination, self.rules, True,
            self.download_valid_archive,
        )
        self.assertEqual(result["matched"], 1)
        self.assertTrue(self.archive.exists())
        self.assertFalse(removed)
        self.assertFalse(existed_before)

    def test_raw_is_removed_only_after_successful_filtering(self):
        result, removed, _ = process_s3_log(
            self.archive, self.destination, self.rules, False,
            self.download_valid_archive,
        )
        self.assertEqual(result["matched"], 1)
        self.assertTrue(self.destination.exists())
        self.assertFalse(self.archive.exists())
        self.assertTrue(removed)

    def test_filter_error_preserves_archive_and_old_result(self):
        self.destination.write_text("old result", encoding="utf-8")

        def download_invalid_archive():
            with gzip.open(self.archive, "wt", encoding="utf-8") as output:
                output.write("ip\n127.0.0.1\n")
            return self.archive

        with self.assertRaisesRegex(ValueError, "В логе отсутствуют поля"):
            process_s3_log(
                self.archive, self.destination, self.rules, False,
                download_invalid_archive,
            )
        self.assertTrue(self.archive.exists())
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "old result")

    def test_local_source_is_never_removed(self):
        source = self.root / "source.tsv"
        source.write_text("banner_id\n208684\n", encoding="utf-8")
        process_local_log(source, self.destination, self.rules)
        self.assertEqual(source.read_text(encoding="utf-8"), "banner_id\n208684\n")

    def test_preexisting_archive_is_not_removed(self):
        self.archive.write_bytes(b"previous archive")
        result, removed, existed_before = process_s3_log(
            self.archive, self.destination, self.rules, False,
            self.download_valid_archive,
        )
        self.assertEqual(result["matched"], 1)
        self.assertTrue(self.archive.exists())
        self.assertFalse(removed)
        self.assertTrue(existed_before)

    def test_completed_archive_survives_download_error(self):
        def failing_download():
            self.download_valid_archive()
            raise OSError("connection closed late")

        with self.assertRaisesRegex(OSError, "connection closed late"):
            process_s3_log(
                self.archive, self.destination, self.rules, False,
                failing_download,
            )
        self.assertTrue(self.archive.exists())
        self.assertFalse(self.destination.exists())

    def test_cancel_filtering_removes_only_archive_created_by_operation(self):
        unrelated = self.root / "unrelated.part"
        unrelated.write_bytes(b"keep")

        def cancelled_filter(*_args):
            self.destination.with_suffix(".part").write_bytes(b"simulated")
            self.destination.with_suffix(".part").unlink()
            raise OperationCancelled("stop")

        with self.assertRaises(OperationCancelled):
            process_s3_log(
                self.archive, self.destination, self.rules, True,
                self.download_valid_archive, filterer=cancelled_filter,
            )
        self.assertFalse(self.archive.exists())
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_cancel_filtering_never_removes_preexisting_archive(self):
        self.archive.write_bytes(b"previous archive")

        def cancelled_filter(*_args):
            raise OperationCancelled("stop")

        with self.assertRaises(OperationCancelled):
            process_s3_log(
                self.archive, self.destination, self.rules, False,
                lambda: self.archive, filterer=cancelled_filter,
            )
        self.assertEqual(self.archive.read_bytes(), b"previous archive")

    def _assert_cancel_before_s3_commit_preserves_files(self, preexisting_archive):
        self.destination.write_text("old result", encoding="utf-8")
        if preexisting_archive:
            self.archive.write_bytes(b"old archive")
        staged = self.root / "download.part"
        with gzip.open(staged, "wt", encoding="utf-8") as output:
            output.write("banner_id\n208684\n")

        controller = OperationController()
        at_boundary = threading.Event()
        release_boundary = threading.Event()

        def operation(state):
            state.begin_filtering()

            def controlled_finalize(action):
                at_boundary.set()
                release_boundary.wait(1)
                return state.finalize(action)

            return process_s3_log(
                self.archive, self.destination, self.rules, True,
                lambda: staged, checkpoint=state.check_cancelled,
                finalize=controlled_finalize,
            )

        self.assertTrue(controller.start(operation))
        self.assertTrue(at_boundary.wait(1))
        self.assertTrue(controller.cancel())
        release_boundary.set()
        controller.wait(1)

        self.assertEqual(controller.snapshot().status, "cancelled")
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "old result")
        if preexisting_archive:
            self.assertEqual(self.archive.read_bytes(), b"old archive")
        else:
            self.assertFalse(self.archive.exists())
        self.assertFalse(staged.exists())
        self.assertFalse([
            path for path in self.root.glob("*.part") if path != staged
        ])

    def test_cancel_before_s3_commit_preserves_new_archive_destination(self):
        self._assert_cancel_before_s3_commit_preserves_files(False)

    def test_cancel_before_s3_commit_preserves_preexisting_archive_destination(self):
        self._assert_cancel_before_s3_commit_preserves_files(True)

    def test_cancel_after_s3_commit_starts_is_rejected_and_raw_decision_finishes(self):
        self.destination.write_text("old result", encoding="utf-8")
        staged = self.root / "download.part"
        with gzip.open(staged, "wt", encoding="utf-8") as output:
            output.write("banner_id\n208684\n")
        controller = OperationController()
        real_replace = os.replace
        cancel_results = []

        def replace_result_and_cancel(source, destination):
            cancel_results.append(controller.cancel())
            real_replace(source, destination)

        def operation(state):
            state.begin_filtering()
            return process_s3_log(
                self.archive, self.destination, self.rules, False,
                lambda: staged, checkpoint=state.check_cancelled,
                finalize=state.finalize,
            )

        with patch("filtering.os.replace", side_effect=replace_result_and_cancel):
            self.assertTrue(controller.start(operation))
            controller.wait(1)

        self.assertEqual(cancel_results, [False])
        self.assertEqual(controller.snapshot().status, "completed")
        self.assertEqual(self.destination.read_text(encoding="utf-8"),
                         "banner_id\n208684\n")
        self.assertFalse(self.archive.exists())
        self.assertFalse(staged.exists())

    def test_cancel_during_archive_publish_is_rejected_and_archive_is_committed(self):
        staged = self.root / "download.part"
        with gzip.open(staged, "wt", encoding="utf-8") as output:
            output.write("banner_id\n208684\n")
        controller = OperationController()
        real_replace = os.replace
        cancel_results = []

        def replace_archive_and_cancel(source, destination):
            cancel_results.append(controller.cancel())
            real_replace(source, destination)

        def operation(state):
            state.begin_filtering()
            return process_s3_log(
                self.archive, self.destination, self.rules, True,
                lambda: staged, checkpoint=state.check_cancelled,
                finalize=state.finalize,
            )

        with patch("operations.os.replace", side_effect=replace_archive_and_cancel):
            self.assertTrue(controller.start(operation))
            controller.wait(1)

        self.assertEqual(cancel_results, [False, False])
        self.assertEqual(controller.snapshot().status, "completed")
        with gzip.open(self.archive, "rt", encoding="utf-8") as incoming:
            self.assertEqual(incoming.read(), "banner_id\n208684\n")
        self.assertFalse(staged.exists())


if __name__ == "__main__":
    unittest.main()
