from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

from fields import FIELDS


APP = Path(__file__).parents[1] / "app.py"
PAGE = "pages/1_Описание_полей.py"


class FieldReferenceUiTests(unittest.TestCase):
    def test_page_shows_all_full_descriptions_without_selector(self):
        app = AppTest.from_file(str(APP), default_timeout=10).run()
        app.switch_page(PAGE).run()
        self.assertFalse(list(app.exception))
        self.assertEqual(app.title[0].value, "Описание полей")
        self.assertFalse(list(app.selectbox))
        self.assertEqual(len(app.table), 1)

        reference = app.table[0].value
        expected_fields = [
            "oc1–oc63" if field == "oc1" else field
            for field in FIELDS
            if field == "oc1" or not field.startswith("oc")
        ]
        self.assertEqual(list(reference["Поле"]), expected_fields)
        self.assertIn("oc1–oc63", reference["Поле"].values)
        self.assertNotIn("oc1", reference["Поле"].values)
        self.assertNotIn("oc63", reference["Поле"].values)
        self.assertIn("ya_device_type", reference["Поле"].values)
        device_description = reference.loc[
            reference["Поле"] == "ya_device_type", "Описание"
        ].iloc[0]
        self.assertIn("Smartphone", device_description)
        self.assertEqual(
            device_description.splitlines(),
            [
                "Тип устройства:",
                "0 — неизвестный",
                "1 — Desktop (компьютер)",
                "2 — Smartphone (смартфон)",
                "3 — Tablet (планшет)",
                "4 — Phone (телефон)",
                "5 — TV.",
            ],
        )
        self.assertEqual(len(reference), len(FIELDS) - 62)

        back = next(button for button in app.button
                    if button.label == "← Вернуться к фильтрам")
        back.click().run()
        self.assertEqual(app.title[0].value, "Логи AdFox")


if __name__ == "__main__":
    unittest.main()
