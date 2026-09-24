import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_state import default_state, load_state, normalise_state, remove_rule, save_state
from fields import FIELDS
from filtering import OPERATORS


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "settings" / "state.json"
        self.defaults = default_state()

    def load(self):
        return load_state(self.path, self.defaults, FIELDS, OPERATORS)

    def test_first_open_without_file(self):
        state, warning = self.load()
        self.assertEqual(state, self.defaults)
        self.assertIsNone(warning)
        self.assertFalse(self.path.exists())

    def test_write_and_read_settings(self):
        state = default_state()
        state.update({"folder": "D:/Логи", "profile": "adfox", "proxy": True,
                      "mode": "Локальный файл", "local_path": "D:/вход.tsv.gz",
                      "output_name": "готово.tsv", "hour": 23})
        save_state(self.path, state)
        loaded, warning = self.load()
        self.assertEqual(loaded, state)
        self.assertIsNone(warning)

    def test_unicode_and_multiline_filter_values(self):
        state = default_state()
        state["rules"][0]["text"] = "Привет, мир\nвторая строка\n значение с пробелом "
        save_state(self.path, state)
        loaded, _ = self.load()
        self.assertEqual(loaded["rules"][0]["text"], state["rules"][0]["text"])
        self.assertIn("Привет", self.path.read_text(encoding="utf-8"))

    def test_corrupt_json_uses_defaults(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"folder": ', encoding="utf-8")
        state, warning = self.load()
        self.assertEqual(state, self.defaults)
        self.assertIn("повреждён", warning)

    def test_unknown_and_old_fields_are_compatible(self):
        raw = {"unknown": "ignored", "folder": "/tmp/result", "rules": [
            {"field": "banner_id", "operator": "Одно из значений", "text": "1"}
        ]}
        state, warning = normalise_state(raw, self.defaults, FIELDS, OPERATORS, recover=True)
        self.assertEqual(state["folder"], "/tmp/result")
        self.assertEqual(state["rules"][0]["text"], "1")
        self.assertTrue(state["rules"][0]["id"])
        self.assertNotIn("unknown", state)
        self.assertIsNone(warning)

    def test_newer_file_recovers_known_fields_with_warning(self):
        raw = {"schema_version": 999, "folder": "/known", "future": True}
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        state, warning = self.load()
        self.assertEqual(state["folder"], "/known")
        self.assertIn("новее", warning)

    def test_atomic_write_removes_part_after_replace_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("old state", encoding="utf-8")
        with patch("app_state.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                save_state(self.path, self.defaults)
        self.assertFalse(list(self.path.parent.glob("*.part")))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old state")


class RuleManagementTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {"id": "first", "field": "banner_id", "operator": "Содержит", "text": "A"},
            {"id": "middle", "field": "campaign_id", "operator": "Содержит", "text": "B"},
            {"id": "last", "field": "useragent", "operator": "Содержит", "text": "C"},
        ]

    def test_remove_first_preserves_remaining_values(self):
        self.assertEqual([(r["id"], r["text"]) for r in remove_rule(self.rules, "first")],
                         [("middle", "B"), ("last", "C")])

    def test_remove_middle_preserves_remaining_values(self):
        self.assertEqual([(r["id"], r["text"]) for r in remove_rule(self.rules, "middle")],
                         [("first", "A"), ("last", "C")])

    def test_remove_last_preserves_remaining_values(self):
        self.assertEqual([(r["id"], r["text"]) for r in remove_rule(self.rules, "last")],
                         [("first", "A"), ("middle", "B")])

    def test_cannot_remove_only_rule(self):
        with self.assertRaises(ValueError):
            remove_rule(self.rules[:1], "first")


if __name__ == "__main__":
    unittest.main()
