import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


APP = Path(__file__).parents[1] / "app.py"


class AppUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_file = str(Path(self.tmp.name) / "state.json")
        self.environment = patch.dict(os.environ, {"ADFOX_LOGS_STATE_FILE": self.state_file})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def open_app(self):
        app = AppTest.from_file(str(APP), default_timeout=10).run()
        self.assertFalse(list(app.exception))
        return app

    @staticmethod
    def button(app, label):
        return next(button for button in app.button if button.label == label)

    def test_delete_middle_keeps_values_and_persists_after_restart(self):
        app = self.open_app()
        app.text_area[0].set_value("первый\nA").run()
        app.button[2].click().run()
        self.assertEqual(len(app.text_area), 3)
        app.text_area[2].set_value("последний\nC").run()

        app.button[1].click().run()
        self.assertEqual([item.value for item in app.text_area],
                         ["первый\nA", "последний\nC"])

        restarted = self.open_app()
        self.assertEqual([item.value for item in restarted.text_area],
                         ["первый\nA", "последний\nC"])

    def test_overwrite_permission_is_not_restored(self):
        app = self.open_app()
        app.checkbox(key="replace").set_value(True).run()
        self.assertTrue(app.checkbox(key="replace").value)

        restarted = self.open_app()
        self.assertFalse(restarted.checkbox(key="replace").value)

    def test_keep_raw_persists_and_is_disabled_for_local_source(self):
        app = self.open_app()
        keep_raw = app.checkbox(key="keep_raw")
        self.assertTrue(keep_raw.value)
        self.assertFalse(keep_raw.disabled)
        keep_raw.set_value(False).run()

        restarted = self.open_app()
        self.assertFalse(restarted.checkbox(key="keep_raw").value)
        restarted.radio(key="mode").set_value("Локальный файл").run()
        self.assertTrue(restarted.checkbox(key="keep_raw").disabled)
        self.assertTrue(any(
            "Локальный исходный файл никогда не изменяется" in item.value
            for item in restarted.caption
        ))

    def test_local_filtering_from_ui(self):
        source = Path(self.tmp.name) / "source.tsv"
        source.write_text(
            "banner_id\tflag_virtual\tuseragent\n"
            "208684\t0\tAndroid\n"
            "208684\t1\tiOS\n",
            encoding="utf-8",
        )
        app = self.open_app()
        app.radio(key="mode").set_value("Локальный файл").run()
        app.text_input(key="local_path").set_value(str(source)).run()
        app.text_input(key="folder").set_value(self.tmp.name).run()
        app.text_input(key="output_name").set_value("result.tsv").run()
        next(button for button in app.button if button.label == "Отфильтровать").click().run()

        # AppTest не исполняет таймер fragment как браузер: вручную делаем
        # несколько обычных rerun, пока короткий фоновый worker заканчивает.
        for _ in range(20):
            if any("Состояние: готово" in item.value for item in app.success):
                break
            time.sleep(0.01)
            app.run()

        self.assertFalse(list(app.exception))
        self.assertTrue(any("Состояние: готово" in item.value for item in app.success))
        self.assertFalse(app.text_input(key="folder").disabled)
        self.assertFalse(next(button for button in app.button if button.label == "Отфильтровать").disabled)
        self.assertEqual(
            (Path(self.tmp.name) / "result.tsv").read_text(encoding="utf-8"),
            "banner_id\tflag_virtual\tuseragent\n208684\t0\tAndroid\n",
        )

    def test_active_operation_disables_start_and_folder_then_unlocks(self):
        app = self.open_app()
        controller = app.session_state["operation_controller"]
        release = threading.Event()

        def operation(state):
            state.begin_filtering()
            release.wait(2)
            return {
                "path": str(Path(self.tmp.name) / "result.tsv"),
                "filter_result": {"checked": 0, "matched": 0, "malformed": 0,
                                  "preview": []},
                "archive_note": "Тест завершён.",
                "archive": None,
            }

        self.assertTrue(controller.start(operation))
        app.run()
        self.assertTrue(app.text_input(key="folder").disabled)
        start = next(button for button in app.button
                     if button.label == "Скачать и отфильтровать")
        self.assertTrue(start.disabled)

        release.set()
        controller.wait(2)
        app.run()
        self.assertFalse(app.text_input(key="folder").disabled)
        start = next(button for button in app.button
                     if button.label == "Скачать и отфильтровать")
        self.assertFalse(start.disabled)

    def test_failed_operation_unlocks_controls_and_shows_error(self):
        app = self.open_app()
        controller = app.session_state["operation_controller"]

        def failing_operation(_state):
            raise OSError("test failure")

        self.assertTrue(controller.start(failing_operation))
        controller.wait(2)
        app.run()

        self.assertFalse(app.text_input(key="folder").disabled)
        start = next(button for button in app.button
                     if button.label == "Скачать и отфильтровать")
        self.assertFalse(start.disabled)
        self.assertTrue(any("OSError: test failure" in item.value for item in app.error))

    def test_pause_cancel_confirmation_back_and_confirm(self):
        marker = Path(self.tmp.name) / "existing.tsv"
        marker.write_text("keep", encoding="utf-8")
        app = self.open_app()
        controller = app.session_state["operation_controller"]
        ready = threading.Event()
        finish = threading.Event()

        def operation(state):
            state.begin_download(100)
            ready.set()
            while not finish.is_set():
                state.wait_download_permission()
                state.check_cancelled()
                time.sleep(0.001)
            state.begin_filtering()
            return {
                "path": str(marker),
                "filter_result": {"checked": 0, "matched": 0, "malformed": 0,
                                  "preview": []},
                "archive_note": "Тест завершён.", "archive": None,
            }

        self.assertTrue(controller.start(operation))
        self.assertTrue(ready.wait(1))
        app.run()
        self.assertEqual(self.button(app, "Пауза").key, "pause_resume")
        self.button(app, "Пауза").click().run()
        for _ in range(100):
            if controller.snapshot().status == "paused":
                break
            time.sleep(0.001)
        app.run()
        self.assertEqual(controller.snapshot().status, "paused")
        self.assertEqual(self.button(app, "Продолжить").key, "pause_resume")

        self.button(app, "Отменить").click().run()
        self.assertEqual(controller.snapshot().status, "paused")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertTrue(any("Подтвердите отмену" in item.value for item in app.warning))
        self.button(app, "Вернуться").click().run()
        self.assertEqual(controller.snapshot().status, "paused")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.button(app, "Продолжить").key, "pause_resume")

        self.button(app, "Отменить").click().run()
        self.button(app, "Подтвердить отмену").click().run()
        controller.wait(2)
        app.run()
        self.assertEqual(controller.snapshot().status, "cancelled")
        self.assertTrue(any("операция отменена" in item.value for item in app.info))
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertFalse(app.text_input(key="folder").disabled)

    def test_filtering_has_cancel_but_no_pause_button(self):
        app = self.open_app()
        controller = app.session_state["operation_controller"]
        ready = threading.Event()

        def operation(state):
            state.begin_filtering()
            ready.set()
            while True:
                state.check_cancelled()
                time.sleep(0.001)

        self.assertTrue(controller.start(operation))
        self.assertTrue(ready.wait(1))
        app.run()
        labels = [button.label for button in app.button]
        self.assertIn("Отменить", labels)
        self.assertNotIn("Пауза", labels)
        self.assertNotIn("Продолжить", labels)

        self.button(app, "Отменить").click().run()
        self.button(app, "Подтвердить отмену").click().run()
        controller.wait(2)
        app.run()
        self.assertEqual(controller.snapshot().status, "cancelled")


if __name__ == "__main__":
    unittest.main()
