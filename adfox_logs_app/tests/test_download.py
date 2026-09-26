from datetime import date
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from download import RemoteObjectChangedError, download_log
from operation_state import OperationCancelled, OperationState


class Body(BytesIO):
    pass


class RangeClient:
    def __init__(self, data, etag='"v1"'):
        self.data = data
        self.etag = etag
        self.closed = False
        self.requests = []
        self.first_read_started = threading.Event()
        self.release_first_read = threading.Event()
        self.block_first_read = False
        self.fail_get = None

    def head_object(self, **_kwargs):
        return {"ContentLength": len(self.data), "ETag": self.etag}

    def get_object(self, **kwargs):
        if self.fail_get:
            raise self.fail_get
        self.requests.append(kwargs)
        start_text, end_text = kwargs["Range"].removeprefix("bytes=").split("-")
        payload = self.data[int(start_text):int(end_text) + 1]
        client = self

        class ControlledBody(Body):
            def read(self, *args):
                if client.block_first_read and len(client.requests) == 1:
                    client.first_read_started.set()
                    client.release_first_read.wait(2)
                return super().read(*args)

        return {"Body": ControlledBody(payload), "ETag": self.etag}

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, client):
        self.fake_client = client

    def client(self, *_args, **_kwargs):
        return self.fake_client


class DownloadTests(unittest.TestCase):
    def run_download(self, root, client, **kwargs):
        with patch("boto3.Session", return_value=FakeSession(client)):
            return download_log(
                date(2026, 9, 24), 12, root, "https://s3.example",
                "bucket", "prefix", **kwargs,
            )

    def test_metadata_callbacks_and_ranges_report_controlled_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            totals, increments = [], []
            client = RangeClient(b"abcdef")
            destination = self.run_download(
                temporary, client, progress=increments.append,
                metadata=totals.append, chunk_size=2,
            )

            self.assertEqual(totals, [6])
            self.assertEqual(increments, [2, 2, 2])
            self.assertEqual(
                [request["Range"] for request in client.requests],
                ["bytes=0-1", "bytes=2-3", "bytes=4-5"],
            )
            self.assertEqual(destination.read_bytes(), b"abcdef")
            self.assertTrue(client.closed)

    def test_zero_metadata_size_is_reported_as_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            totals = []
            self.run_download(temporary, RangeClient(b""), metadata=totals.append)
            self.assertEqual(totals, [None])

    def test_pause_stops_counter_and_resume_finishes_same_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = RangeClient(b"abcdefghijkl")
            client.block_first_read = True
            state = OperationState()
            state.prepare()
            result = []

            def worker():
                try:
                    result.append(self.run_download(
                        temporary, client, metadata=state.begin_download,
                        progress=state.add_downloaded, control=state, chunk_size=4,
                    ))
                except Exception as error:  # pragma: no cover - assertion below reports it
                    result.append(error)

            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(client.first_read_started.wait(1))
            self.assertTrue(state.request_pause())
            client.release_first_read.set()
            for _ in range(200):
                if state.snapshot().status == "paused":
                    break
                time.sleep(0.001)
            self.assertEqual(state.snapshot().status, "paused")
            paused_bytes = state.snapshot().downloaded_bytes
            time.sleep(0.02)
            self.assertEqual(state.snapshot().downloaded_bytes, paused_bytes)

            self.assertTrue(state.resume())
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(result[0], Path)
            self.assertEqual(result[0].read_bytes(), b"abcdefghijkl")
            self.assertEqual(state.snapshot().downloaded_bytes, 12)

    def test_changed_object_on_resume_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = RangeClient(b"abcdefgh")
            client.block_first_read = True
            state = OperationState()
            state.prepare()
            errors = []

            def worker():
                try:
                    self.run_download(
                        root, client, metadata=state.begin_download,
                        progress=state.add_downloaded, control=state, chunk_size=4,
                    )
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(client.first_read_started.wait(1))
            state.request_pause()
            client.release_first_read.set()
            for _ in range(200):
                if state.snapshot().status == "paused":
                    break
                time.sleep(0.001)
            client.data = b"ABCDEFGH"
            client.etag = '"v2"'
            state.resume()
            thread.join(2)

            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], RemoteObjectChangedError)
            self.assertIn("изменился", str(errors[0]))
            self.assertFalse(list(root.glob("*.part")))
            self.assertFalse((root / "2026_09_24_12.tsv.gz").exists())

    def test_cancel_active_download_removes_part_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            archive.write_bytes(b"previous archive")
            unrelated = root / "unrelated.part"
            unrelated.write_bytes(b"keep")
            client = RangeClient(b"abcdefgh")
            client.block_first_read = True
            state = OperationState()
            state.prepare()
            errors = []

            def worker():
                try:
                    self.run_download(
                        root, client, metadata=state.begin_download,
                        progress=state.add_downloaded, control=state, chunk_size=4,
                    )
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(client.first_read_started.wait(1))
            self.assertTrue(state.request_cancel())
            client.release_first_read.set()
            thread.join(2)

            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], OperationCancelled)
            self.assertEqual(archive.read_bytes(), b"previous archive")
            self.assertEqual(unrelated.read_bytes(), b"keep")
            self.assertEqual(list(root.glob("*.part")), [unrelated])

    def test_download_error_removes_own_part_but_preserves_preexisting_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            archive.write_bytes(b"previous archive")
            client = RangeClient(b"abcdef")
            client.fail_get = OSError("network failed")

            with self.assertRaisesRegex(OSError, "network failed"):
                self.run_download(root, client)

            self.assertEqual(archive.read_bytes(), b"previous archive")
            self.assertFalse(list(root.glob("*.part")))
            self.assertTrue(client.closed)

    def test_replace_error_preserves_old_archive_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            archive.write_bytes(b"previous archive")
            client = RangeClient(b"new archive")

            with patch("path_ownership.os.replace", side_effect=OSError("disk error")):
                with self.assertRaisesRegex(OSError, "disk error"):
                    self.run_download(root, client, replace=True)

            self.assertEqual(archive.read_bytes(), b"previous archive")
            self.assertFalse(list(root.glob("*.part")))
            self.assertTrue(client.closed)

    def test_archive_appearing_during_download_is_not_replaced_without_permission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            client = RangeClient(b"new archive")

            def competing_publish(_total):
                archive.write_bytes(b"competing archive")

            with self.assertRaisesRegex(FileExistsError, "замена не разрешена"):
                self.run_download(
                    root, client, metadata=competing_publish, replace=False,
                )

            self.assertEqual(archive.read_bytes(), b"competing archive")
            self.assertFalse(list(root.glob("*.part")))

    def test_replace_true_allows_existing_archive_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "2026_09_24_12.tsv.gz"
            archive.write_bytes(b"old archive")

            result = self.run_download(
                root, RangeClient(b"new archive"), replace=True,
            )

            self.assertEqual(result, archive)
            self.assertEqual(archive.read_bytes(), b"new archive")


if __name__ == "__main__":
    unittest.main()
