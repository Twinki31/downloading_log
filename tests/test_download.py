from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from download import download_log


class DownloadTests(unittest.TestCase):
    def test_metadata_and_callbacks_report_controlled_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            totals = []
            increments = []

            class FakeClient:
                def head_object(self, **_kwargs):
                    return {"ContentLength": 6}

                def download_file(self, _bucket, _key, filename, Callback, Config):
                    Path(filename).write_bytes(b"abcdef")
                    Callback(2)
                    Callback(4)

                def close(self):
                    pass

            class FakeSession:
                def client(self, *_args, **_kwargs):
                    return FakeClient()

            with patch("boto3.Session", return_value=FakeSession()):
                destination = download_log(
                    date(2026, 9, 24), 12, temporary, "https://s3.example",
                    "bucket", "prefix", progress=increments.append,
                    metadata=totals.append,
                )

            self.assertEqual(totals, [6])
            self.assertEqual(increments, [2, 4])
            self.assertEqual(destination.read_bytes(), b"abcdef")

    def test_zero_metadata_size_is_reported_as_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            totals = []

            class FakeClient:
                def head_object(self, **_kwargs):
                    return {"ContentLength": 0}

                def download_file(self, _bucket, _key, filename, Callback, Config):
                    Path(filename).write_bytes(b"")

                def close(self):
                    pass

            class FakeSession:
                def client(self, *_args, **_kwargs):
                    return FakeClient()

            with patch("boto3.Session", return_value=FakeSession()):
                download_log(
                    date(2026, 9, 24), 12, temporary, "https://s3.example",
                    "bucket", "prefix", metadata=totals.append,
                )
            self.assertEqual(totals, [None])

    def test_download_error_removes_part_but_preserves_preexisting_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            archive.write_bytes(b"previous archive")

            class FakeClient:
                closed = False

                def download_file(self, _bucket, _key, filename, Callback, Config):
                    Path(filename).write_bytes(b"partial download")
                    raise OSError("network failed")

                def close(self):
                    self.closed = True

            client = FakeClient()

            class FakeSession:
                def client(self, *_args, **_kwargs):
                    return client

            with patch("boto3.Session", return_value=FakeSession()):
                with self.assertRaisesRegex(OSError, "network failed"):
                    download_log(
                        date(2026, 9, 24), 12, root, "https://s3.example",
                        "bucket", "prefix",
                    )

            self.assertEqual(archive.read_bytes(), b"previous archive")
            self.assertFalse(list(root.glob("*.part")))
            self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
