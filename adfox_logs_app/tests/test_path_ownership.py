import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from execution import run_local_operation
from filtering import Rule, filter_log
from operation_state import OperationController
from path_ownership import (LOCK_SUFFIX, PathBusyError, reserve_paths)


class PathOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.tsv"
        self.source.write_text("banner_id\n208684\n", encoding="utf-8")
        self.rules = (Rule("banner_id", "Одно из значений", ("208684",)),)

    def _local_operation(self, destination, *, replace=False):
        return lambda state: run_local_operation(
            state, source=self.source, destination=destination,
            rules=self.rules, replace=replace,
        )

    def test_two_operations_for_same_path_do_not_write_concurrently(self):
        destination = self.root / "result.tsv"
        entered = threading.Event()
        release = threading.Event()
        real_filter = filter_log

        def controlled_filter(*args, **kwargs):
            entered.set()
            release.wait(2)
            return real_filter(*args, **kwargs)

        first = OperationController()
        second = OperationController()
        with patch("execution.process_local_log", side_effect=controlled_filter):
            self.assertTrue(first.start(self._local_operation(destination)))
            self.assertTrue(entered.wait(1))
            self.assertTrue(second.start(self._local_operation(destination)))
            second.wait(1)
            self.assertEqual(second.snapshot().status, "failed")
            self.assertIn("Путь уже используется другой операцией", second.snapshot().error)
            release.set()
            first.wait(2)

        self.assertEqual(first.snapshot().status, "completed")
        self.assertEqual(destination.read_text(encoding="utf-8"),
                         "banner_id\n208684\n")
        self.assertFalse(list(self.root.glob(f"*{LOCK_SUFFIX}")))

    def test_operations_for_different_paths_run_in_parallel(self):
        destinations = (self.root / "first.tsv", self.root / "second.tsv")
        barrier = threading.Barrier(2)
        real_filter = filter_log

        def controlled_filter(*args, **kwargs):
            barrier.wait(2)
            return real_filter(*args, **kwargs)

        controllers = (OperationController(), OperationController())
        with patch("execution.process_local_log", side_effect=controlled_filter):
            for controller, destination in zip(controllers, destinations):
                self.assertTrue(controller.start(self._local_operation(destination)))
            for controller in controllers:
                controller.wait(2)

        self.assertEqual([item.snapshot().status for item in controllers],
                         ["completed", "completed"])
        self.assertTrue(all(path.exists() for path in destinations))

    def test_path_pairs_are_acquired_in_stable_order_without_deadlock(self):
        archive = self.root / "archive.tsv.gz"
        destination = self.root / "result.tsv"
        attempted = threading.Event()
        errors = []

        def reversed_reservation():
            try:
                with reserve_paths((destination, archive)):
                    pass
            except Exception as error:
                errors.append(error)
            finally:
                attempted.set()

        with reserve_paths((archive, destination)):
            thread = threading.Thread(target=reversed_reservation)
            thread.start()
            self.assertTrue(attempted.wait(1))
            thread.join(1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PathBusyError)

    def test_file_appearing_before_publish_is_not_replaced_without_permission(self):
        destination = self.root / "late.tsv"

        def create_competing_file(action):
            destination.write_text("чужой результат", encoding="utf-8")
            action()

        with self.assertRaisesRegex(FileExistsError, "замена не разрешена"):
            filter_log(
                self.source, destination, self.rules,
                finalize=create_competing_file, replace=False,
            )

        self.assertEqual(destination.read_text(encoding="utf-8"), "чужой результат")
        self.assertFalse(list(self.root.glob("*.part")))

    def test_replace_true_replaces_existing_file(self):
        destination = self.root / "result.tsv"
        destination.write_text("старый результат", encoding="utf-8")

        filter_log(self.source, destination, self.rules, replace=True)

        self.assertEqual(destination.read_text(encoding="utf-8"),
                         "banner_id\n208684\n")

    def test_error_and_cancel_release_lock(self):
        error_destination = self.root / "error.tsv"
        failed = OperationController()
        with patch("execution.process_local_log", side_effect=OSError("disk failed")):
            self.assertTrue(failed.start(self._local_operation(error_destination)))
            failed.wait(1)
        self.assertEqual(failed.snapshot().status, "failed")
        with reserve_paths((error_destination,)):
            pass

        cancel_destination = self.root / "cancel.tsv"
        entered = threading.Event()
        release = threading.Event()

        def cancellable_filter(_source, _destination, _rules, _progress,
                               checkpoint, _finalize, **_kwargs):
            entered.set()
            release.wait(2)
            checkpoint()

        cancelled = OperationController()
        with patch("execution.process_local_log", side_effect=cancellable_filter):
            self.assertTrue(cancelled.start(self._local_operation(cancel_destination)))
            self.assertTrue(entered.wait(1))
            self.assertTrue(cancelled.cancel())
            release.set()
            cancelled.wait(2)
        self.assertEqual(cancelled.snapshot().status, "cancelled")
        with reserve_paths((cancel_destination,)):
            pass

    def test_foreign_lock_and_part_are_not_removed(self):
        destination = self.root / "result.tsv"
        sidecar = destination.with_name(destination.name + LOCK_SUFFIX)
        sidecar.write_text("чужой lock", encoding="utf-8")
        part = self.root / "unrelated.part"
        part.write_text("чужой part", encoding="utf-8")

        with self.assertRaises(PathBusyError):
            with reserve_paths((destination,)):
                pass

        self.assertEqual(sidecar.read_text(encoding="utf-8"), "чужой lock")
        self.assertEqual(part.read_text(encoding="utf-8"), "чужой part")

    @unittest.skipIf(os.name == "nt", "На Windows stale lock удаляется вручную")
    def test_dead_owner_lock_is_recovered_but_live_lock_is_not(self):
        destination = self.root / "result.tsv"
        sidecar = destination.with_name(destination.name + LOCK_SUFFIX)
        record = {
            "owner": "dead-owner", "pid": 99999999,
            "host": socket.gethostname(), "created": time.time(),
            "path": str(destination.resolve()),
        }
        sidecar.write_text(json.dumps(record), encoding="utf-8")

        with patch("path_ownership._pid_is_alive", return_value=False):
            with reserve_paths((destination,)):
                self.assertTrue(sidecar.exists())
        self.assertFalse(sidecar.exists())

        with reserve_paths((destination,)):
            with self.assertRaises(PathBusyError):
                with reserve_paths((destination,)):
                    pass


if __name__ == "__main__":
    unittest.main()
