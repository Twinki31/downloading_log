import unittest

from fields import FIELDS, description, label


class FieldDescriptionTests(unittest.TestCase):
    def test_documented_fields_have_short_and_full_descriptions(self):
        documented = FIELDS[:97]
        for field in documented:
            with self.subTest(field=field):
                self.assertNotIn("описание требует уточнения", label(field))
                self.assertNotIn("пока не указано", description(field))

    def test_oc_fields_share_detailed_explanation(self):
        self.assertEqual(description("oc1"), description("oc63"))
        self.assertIn("puid", description("oc1"))

    def test_undocumented_field_is_marked_explicitly(self):
        self.assertEqual(label("multi_banner_type"), "multi_banner_type (уточняется)")
        self.assertEqual(description("multi_banner_type"), "Уточняется.")


if __name__ == "__main__":
    unittest.main()
