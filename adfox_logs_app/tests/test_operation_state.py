import threading
import time
import unittest

from operation_state import (
    OperationCancelled,
    OperationController,
    OperationState,
    safe_error_text,
)


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class OperationStateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.state = OperationState(clock=self.clock, speed_interval=0.5)
        self.assertTrue(self.state.prepare())

    def test_known_size_progress_is_monotonic_and_finishes_at_100(self):
        self.state.begin_download(4000)
        percents = []
        downloaded = []
        for amount in (500, 1000, 2500):
            self.clock.value += 0.5
            self.state.add_downloaded(amount)
            snapshot = self.state.snapshot()
            downloaded.append(snapshot.downloaded_bytes)
            percents.append(snapshot.percent)
        self.assertEqual(downloaded, [500, 1500, 4000])
        self.assertEqual(percents, [12.5, 37.5, 100.0])
        self.state.begin_filtering()
        self.assertEqual(self.state.snapshot().percent, 100.0)

    def test_unknown_and_zero_size_have_no_percentage(self):
        for size in (None, 0):
            with self.subTest(size=size):
                state = OperationState(clock=self.clock)
                state.prepare()
                state.begin_download(size)
                state.add_downloaded(10)
                self.assertIsNone(state.snapshot().percent)

    def test_speed_uses_controlled_monotonic_clock_and_interval(self):
        self.state.begin_download(4000)
        self.clock.value = 0.2
        self.state.add_downloaded(1000)
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 0.0)
        self.clock.value = 1.0
        self.state.add_downloaded(1000)
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 2000.0)
        self.clock.value = 2.0
        self.state.begin_filtering()
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 2000.0)

    def test_speed_before_during_and_after_actual_pause(self):
        self.state.begin_download(400)
        self.clock.value = 1.0
        self.state.add_downloaded(100)
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 100.0)

        self.assertTrue(self.state.request_pause())
        pausing = self.state.snapshot()
        self.assertEqual(pausing.status, "pausing")
        self.assertEqual(pausing.speed_bytes_per_second, 100.0)

        # Текущая Range-порция ещё дочитывается после запроса паузы.
        self.clock.value = 2.0
        self.state.add_downloaded(200)
        pausing = self.state.snapshot()
        self.assertEqual(pausing.status, "pausing")
        self.assertEqual(pausing.downloaded_bytes, 300)
        self.assertEqual(pausing.speed_bytes_per_second, 200.0)

        waiting = threading.Thread(target=self.state.wait_download_permission)
        waiting.start()
        for _ in range(100):
            if self.state.snapshot().status == "paused":
                break
            time.sleep(0.001)
        self.assertEqual(self.state.snapshot().status, "paused")
        paused_bytes = self.state.snapshot().downloaded_bytes
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 0.0)

        self.clock.value = 102.0
        self.assertTrue(self.state.resume())
        waiting.join(1)
        resumed = self.state.snapshot()
        self.assertEqual(resumed.status, "downloading")
        self.assertEqual(resumed.downloaded_bytes, paused_bytes)
        self.assertEqual(resumed.speed_bytes_per_second, 0.0)

        self.clock.value = 103.0
        self.state.add_downloaded(100)
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 100.0)

        # Активное ожидание завершения порции (1..2) входит в среднюю,
        # а только фактическая пауза (2..102) исключается.
        self.clock.value = 104.0
        self.state.begin_filtering()
        self.assertEqual(self.state.snapshot().downloaded_bytes, paused_bytes + 100)
        self.assertEqual(self.state.snapshot().speed_bytes_per_second, 100.0)

    def test_successful_state_transitions(self):
        self.state.begin_download(10)
        self.state.add_downloaded(10)
        self.state.begin_filtering()
        self.state.complete({"ok": True})
        self.assertEqual(
            self.state.history(),
            ("idle", "preparing", "downloading", "filtering", "completed"),
        )
        self.assertFalse(self.state.snapshot().active)

    def test_failure_keeps_error_text(self):
        self.state.begin_download(None)
        self.state.fail(OSError("network failed"))
        snapshot = self.state.snapshot()
        self.assertEqual(snapshot.status, "failed")
        self.assertEqual(snapshot.error, "OSError: network failed")
        self.assertFalse(snapshot.active)

    def test_failure_redacts_credentials_from_error_text(self):
        fake_secret = "FAKE_CREDENTIAL_FOR_TESTS"
        fake_aws_id = "AKIA" + "TESTONLY12345678"
        cases = (
            (
                'request failed: {"aws_secret_access_key": "' + fake_secret + '"}',
                (fake_secret,),
                ("request failed", '"aws_secret_access_key": "<скрыто>"'),
            ),
            (
                "request failed: {'password': '" + fake_secret + "'}",
                (fake_secret,),
                ("request failed", "'password': '<скрыто>'"),
            ),
            (
                "connection failed; access_token   =   " + fake_secret,
                (fake_secret,),
                ("connection failed", "access_token   =   <скрыто>"),
            ),
            (
                "upstream rejected request\nAuthorization: Bearer " + fake_secret,
                (fake_secret,),
                ("upstream rejected request", "Authorization: Bearer <скрыто>"),
            ),
            (
                "proxy response: Authorization: Basic " + fake_secret,
                (fake_secret,),
                ("proxy response", "Authorization: Basic <скрыто>"),
            ),
            (
                "request URL: https://example.test/log?access_token="
                + fake_secret
                + "&part=7",
                (fake_secret,),
                ("request URL", "&part=7"),
            ),
            (
                "request URL: https://fake-user:" + fake_secret + "@example.test/log",
                ("fake-user", fake_secret),
                ("request URL", "example.test/log"),
            ),
            (
                "download failed: password="
                + fake_secret
                + "; Authorization: Bearer "
                + fake_secret
                + "; id="
                + fake_aws_id,
                (fake_secret, fake_aws_id),
                ("download failed", "id=<скрыто>"),
            ),
            (
                "network timeout while reading response",
                (),
                ("network timeout", "reading response"),
            ),
            (
                "password field is missing; tokenization failed",
                (),
                ("password field is missing", "tokenization failed"),
            ),
        )

        for error_text, secrets, useful_parts in cases:
            with self.subTest(error_text=error_text):
                message = safe_error_text(RuntimeError(error_text))
                self.assertNotIn(fake_secret, message)
                for secret in secrets:
                    self.assertNotIn(secret, message)
                for useful_part in useful_parts:
                    self.assertIn(useful_part, message)

    def test_cancel_before_finalization_wins_without_running_action(self):
        self.state.begin_filtering()
        self.assertTrue(self.state.request_cancel())
        called = []

        with self.assertRaises(OperationCancelled):
            self.state.finalize(lambda: called.append(True))

        self.assertEqual(called, [])

    def test_cancel_during_finalization_is_rejected(self):
        self.state.begin_filtering()
        cancel_results = []

        def action():
            cancel_results.append(self.state.request_cancel())

        self.state.finalize(action)
        self.state.complete("done")

        self.assertEqual(cancel_results, [False])
        self.assertEqual(self.state.snapshot().status, "completed")
        self.assertEqual(
            self.state.history(),
            ("idle", "preparing", "filtering", "finalizing", "completed"),
        )


class OperationControllerTests(unittest.TestCase):
    def test_second_start_is_rejected_and_success_unlocks(self):
        controller = OperationController()
        release = threading.Event()

        def operation(state):
            state.begin_download(1)
            release.wait(2)
            state.begin_filtering()
            return "done"

        self.assertTrue(controller.start(operation))
        self.assertFalse(controller.start(operation))
        release.set()
        controller.wait(2)
        self.assertEqual(controller.snapshot().status, "completed")
        self.assertTrue(controller.start(lambda state: "again"))
        controller.wait(2)

    def test_failure_unlocks_next_start(self):
        controller = OperationController()

        def failing(_state):
            raise RuntimeError("broken")

        self.assertTrue(controller.start(failing))
        controller.wait(2)
        self.assertEqual(controller.snapshot().status, "failed")
        self.assertTrue(controller.start(lambda state: "recovered"))
        controller.wait(2)
        self.assertEqual(controller.snapshot().status, "completed")

    def test_cancel_on_pause_is_idempotent_and_next_start_works(self):
        controller = OperationController()
        reach_checkpoint = threading.Event()
        continue_to_checkpoint = threading.Event()

        def operation(state):
            state.begin_download(10)
            reach_checkpoint.set()
            continue_to_checkpoint.wait(1)
            state.wait_download_permission()
            return "not reached"

        self.assertTrue(controller.start(operation))
        self.assertTrue(reach_checkpoint.wait(1))
        self.assertTrue(controller.pause())
        continue_to_checkpoint.set()
        for _ in range(100):
            if controller.snapshot().status == "paused":
                break
            time.sleep(0.001)
        self.assertEqual(controller.snapshot().status, "paused")
        self.assertTrue(controller.cancel())
        self.assertFalse(controller.cancel())
        controller.wait(1)
        self.assertEqual(controller.snapshot().status, "cancelled")
        self.assertEqual(controller.snapshot().downloaded_bytes, 0)

        self.assertTrue(controller.start(lambda _state: "again"))
        controller.wait(1)
        self.assertEqual(controller.snapshot().status, "completed")


if __name__ == "__main__":
    unittest.main()
