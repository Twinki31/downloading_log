import threading
import time
import unittest

from operation_state import OperationController, OperationState


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

    def test_pause_time_is_excluded_from_speed(self):
        self.state.begin_download(200)
        self.clock.value = 1.0
        self.state.add_downloaded(100)
        self.assertTrue(self.state.request_pause())

        waiting = threading.Thread(target=self.state.wait_download_permission)
        waiting.start()
        for _ in range(100):
            if self.state.snapshot().status == "paused":
                break
            time.sleep(0.001)
        self.assertEqual(self.state.snapshot().status, "paused")
        paused_bytes = self.state.snapshot().downloaded_bytes
        self.clock.value = 101.0
        self.assertTrue(self.state.resume())
        waiting.join(1)

        self.clock.value = 102.0
        self.state.add_downloaded(100)
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
