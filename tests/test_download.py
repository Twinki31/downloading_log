from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from download import download_log


class DownloadTests(unittest.TestCase):
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
