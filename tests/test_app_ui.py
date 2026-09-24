import os
from pathlib import Path
import tempfile
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

        self.assertFalse(list(app.exception))
        self.assertTrue(any("Готово:" in item.value for item in app.success))
        self.assertEqual(
            (Path(self.tmp.name) / "result.tsv").read_text(encoding="utf-8"),
            "banner_id\tflag_virtual\tuseragent\n208684\t0\tAndroid\n",
        )


if __name__ == "__main__":
    unittest.main()
