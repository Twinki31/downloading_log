import unittest

from ui_localization import (ELEMENT_TRANSLATIONS, PREFIX_TRANSLATIONS,
                             TRANSLATIONS, localization_html)


class UiLocalizationTests(unittest.TestCase):
    def test_all_visible_toolbar_labels_are_translated(self):
        expected = {
            "Deploy", "System", "Light", "Dark", "Rerun", "Auto rerun",
            "Clear cache", "Print", "Record screen", "Main menu",
        }
        self.assertTrue(expected.issubset(TRANSLATIONS))
        self.assertIn("Made with Streamlit v", PREFIX_TRANSLATIONS)
        self.assertIn("[data-testid='stScreencastInstruction']", ELEMENT_TRANSLATIONS)

    def test_script_observes_streamlit_updates_and_translates_accessibility_labels(self):
        html = localization_html()
        self.assertIn("window.parent.document", html)
        self.assertIn("MutationObserver", html)
        self.assertIn('"aria-label"', html)
        self.assertIn("Опубликовать", html)
        self.assertIn("Записать экран", html)


if __name__ == "__main__":
    unittest.main()
