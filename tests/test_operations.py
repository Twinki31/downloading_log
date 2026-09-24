import gzip
from pathlib import Path
import tempfile
import unittest

from filtering import Rule
from operations import process_local_log, process_s3_log


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


if __name__ == "__main__":
    unittest.main()
