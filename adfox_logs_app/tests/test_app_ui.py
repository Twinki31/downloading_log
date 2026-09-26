import os
import json
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import streamlit as st
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
        self.button(app, "＋ Добавить фильтр").click().run()
        self.assertEqual(len(app.text_area), 3)
        app.text_area[2].set_value("последний\nC").run()

        [button for button in app.button if button.label == "Удалить"][1].click().run()
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

    def test_field_selector_uses_short_descriptions(self):
        app = self.open_app()
        options = app.selectbox[0].options
        self.assertIn("useragent (данные браузера и устройства)", options)
        self.assertIn("oc63 (доп. характеристика 63)", options)
        self.assertNotIn("нет описания", "\n".join(options[:97]))

    def test_legacy_filter_explanation_is_not_shown(self):
        app = self.open_app()
        captions = "\n".join(item.value for item in app.caption)
        self.assertNotIn("перенесён из исходного скрипта", captions)

    def test_short_date_and_hour_labels_without_raw_archive_caption(self):
        app = self.open_app()
        self.assertEqual(app.date_input[0].label, "Дата")
        self.assertEqual(app.number_input[0].label, "Час")
        self.assertEqual(app.date_input[0].min, date(2020, 1, 1))
        self.assertEqual(app.date_input[0].max, date.today())
        self.assertEqual(app.number_input[0].max, datetime.now().hour)
        captions = "\n".join(item.value for item in app.caption)
        self.assertNotIn("Если выключить флажок, новый архив удалится", captions)

    def test_json_import_applies_date_and_hour(self):
        app = self.open_app()
        imported = dict(app.session_state["settings"])
        imported.update({"selected_date": "2020-07-08", "hour": 6})
        app.file_uploader[0].set_value(
            ("settings.json", json.dumps(imported).encode("utf-8"), "application/json")
        ).run()
        self.button(app, "Применить настройки").click().run()

        self.assertEqual(app.date_input[0].value, date(2020, 7, 8))
        self.assertEqual(app.number_input[0].value, 6)

    def test_newer_json_import_recovers_known_fields_and_warns_once(self):
        app = self.open_app()
        imported = dict(app.session_state["settings"])
        imported.update({
            "schema_version": 999,
            "folder": str(Path(self.tmp.name) / "known"),
            "profile": "known-profile",
            "proxy": "not-a-boolean",
            "future_setting": {"enabled": True},
        })
        app.file_uploader[0].set_value(
            ("settings.json", json.dumps(imported).encode("utf-8"), "application/json")
        ).run()
        self.button(app, "Применить настройки").click().run()

        warnings = "\n".join(item.value for item in app.warning)
        self.assertIn("версия файла настроек новее поддерживаемой", warnings)
        self.assertIn("часть полей могла не восстановиться", warnings)
        self.assertEqual(app.text_input(key="folder").value,
                         str(Path(self.tmp.name) / "known"))
        self.assertEqual(app.text_input(key="profile").value, "known-profile")
        self.assertFalse(app.checkbox(key="proxy").value)
        self.assertNotIn("future_setting", app.session_state["settings"])
        self.assertEqual(app.session_state["settings"]["schema_version"], 1)
        self.assertEqual(
            json.loads(Path(self.state_file).read_text(encoding="utf-8"))["schema_version"],
            1,
        )

        app.run()
        warnings = "\n".join(item.value for item in app.warning)
        self.assertNotIn("версия файла настроек новее поддерживаемой", warnings)

    def test_legacy_json_import_has_no_schema_warning(self):
        app = self.open_app()
        imported = {
            "folder": str(Path(self.tmp.name) / "legacy"),
            "rules": [
                {"field": "banner_id", "operator": "Одно из значений", "text": "42"}
            ],
        }
        app.file_uploader[0].set_value(
            ("settings.json", json.dumps(imported).encode("utf-8"), "application/json")
        ).run()
        self.button(app, "Применить настройки").click().run()

        self.assertEqual(app.text_input(key="folder").value,
                         str(Path(self.tmp.name) / "legacy"))
        self.assertEqual(app.text_area[0].value, "42")
        self.assertNotIn(
            "версия файла настроек",
            "\n".join(item.value for item in app.warning),
        )

    def test_invalid_import_does_not_change_current_settings(self):
        app = self.open_app()
        original_folder = app.text_input(key="folder").value
        imported = dict(app.session_state["settings"])
        imported["folder"] = ["not", "a", "string"]
        app.file_uploader[0].set_value(
            ("settings.json", json.dumps(imported).encode("utf-8"), "application/json")
        ).run()
        self.button(app, "Применить настройки").click().run()

        self.assertTrue(any("Не удалось прочитать настройки" in item.value
                            for item in app.error))
        self.assertEqual(app.text_input(key="folder").value, original_folder)

    def test_malformed_json_import_does_not_change_current_settings(self):
        app = self.open_app()
        original_settings = dict(app.session_state["settings"])
        app.file_uploader[0].set_value(
            ("settings.json", b'{"folder": ', "application/json")
        ).run()
        self.button(app, "Применить настройки").click().run()

        self.assertTrue(any("Не удалось прочитать настройки" in item.value
                            for item in app.error))
        self.assertEqual(app.session_state["settings"], original_settings)

    def test_credentialed_endpoint_never_reaches_state_ui_or_export(self):
        password = "FIXTURE_PASSWORD_8d37"
        captured_exports = []
        original_download_button = st.download_button

        def capture_download(*args, **kwargs):
            captured_exports.append(args[1] if len(args) > 1 else kwargs["data"])
            return original_download_button(*args, **kwargs)

        app = self.open_app()
        with patch.object(st, "download_button", side_effect=capture_download):
            app.text_input(key="endpoint").set_value(
                f"https://login:{password}@s3.example"
            ).run()

        saved = Path(self.state_file).read_text(encoding="utf-8")
        exported = json.loads(captured_exports[-1])
        self.assertEqual(app.text_input(key="endpoint").value,
                         app.session_state["settings"]["endpoint"])
        self.assertEqual(exported["endpoint"], app.session_state["settings"]["endpoint"])
        self.assertIn("AWS-профиль", "\n".join(item.value for item in app.warning))
        self.assertNotIn(password, saved)
        self.assertNotIn(password, captured_exports[-1])
        self.assertNotIn(password, str(app))

    def test_imported_credentialed_endpoint_is_reset_before_export(self):
        password = "FIXTURE_PASSWORD_8d37"
        app = self.open_app()
        imported = dict(app.session_state["settings"])
        imported["endpoint"] = f"https://login:{password}@s3.example"
        app.file_uploader[0].set_value(
            ("settings.json", json.dumps(imported).encode("utf-8"), "application/json")
        ).run()

        captured_exports = []
        original_download_button = st.download_button

        def capture_download(*args, **kwargs):
            captured_exports.append(args[1] if len(args) > 1 else kwargs["data"])
            return original_download_button(*args, **kwargs)

        with patch.object(st, "download_button", side_effect=capture_download):
            self.button(app, "Применить настройки").click().run()

        exported = json.loads(captured_exports[-1])
        self.assertEqual(exported["endpoint"], app.text_input(key="endpoint").value)
        self.assertNotIn("@", exported["endpoint"])
        self.assertIn("AWS-профиль", "\n".join(item.value for item in app.warning))
        self.assertNotIn(password, Path(self.state_file).read_text(encoding="utf-8"))
        self.assertNotIn(password, captured_exports[-1])
        self.assertNotIn(password, str(app))

    def test_past_date_allows_any_hour(self):
        app = self.open_app()
        app.date_input[0].set_value(date.today() - timedelta(days=1)).run()
        self.assertEqual(app.number_input[0].max, 23)

    def test_keep_raw_persists_and_is_disabled_for_local_source(self):
        app = self.open_app()
        checkbox_labels = [checkbox.label for checkbox in app.checkbox]
        self.assertLess(
            checkbox_labels.index("Разрешить замену существующих файлов с теми же именами"),
            checkbox_labels.index("Оставить сырой лог"),
        )
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
