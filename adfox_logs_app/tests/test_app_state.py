import json
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_state import (default_state, load_state, normalise_s3_endpoint,
                       normalise_state, remove_rule, save_state)
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
                      "output_name": "готово.tsv", "selected_date": "2020-01-01",
                      "hour": 23})
        save_state(self.path, state)
        loaded, warning = self.load()
        self.assertEqual(loaded, state)
        self.assertIsNone(warning)

    def test_valid_s3_endpoints_are_normalised(self):
        cases = {
            "https://s3-private.mds.yandex.net": "https://s3-private.mds.yandex.net",
            "HTTP://S3.EXAMPLE:9000/api/v1/": "http://s3.example:9000/api/v1/",
            "localhost:9000/minio": "https://localhost:9000/minio",
            "127.0.0.1:9000": "https://127.0.0.1:9000",
            "http://[::1]:9000/storage": "http://[::1]:9000/storage",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalise_s3_endpoint(raw), expected)

    def test_s3_endpoint_rejects_userinfo_without_echoing_it(self):
        password = "FIXTURE_PASSWORD_8d37"
        for endpoint in (
            f"https://login:{password}@s3.example",
            f"login:{password}@localhost:9000/path",
            "https://login@s3.example",
            "https://@s3.example",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError) as caught:
                normalise_s3_endpoint(endpoint)
            self.assertIn("AWS-профиль", str(caught.exception))
            self.assertNotIn(password, str(caught.exception))

    def test_s3_endpoint_rejects_unsupported_or_ambiguous_parts(self):
        for endpoint in (
            "ftp://s3.example",
            "//s3.example",
            "https:s3.example",
            "https://s3.example/path?region=test",
            "https://s3.example/path#fragment",
            "https://s3.example:wrong",
            "https://s3.example:0",
            "https://[::1",
            "",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                normalise_s3_endpoint(endpoint)

    def test_old_state_with_userinfo_recovers_default_endpoint(self):
        password = "FIXTURE_PASSWORD_8d37"
        raw = default_state()
        raw["endpoint"] = f"https://login:{password}@s3.example"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(raw), encoding="utf-8")

        state, warning = self.load()

        self.assertEqual(state["endpoint"], self.defaults["endpoint"])
        self.assertIn("AWS-профиль", warning)
        self.assertNotIn(password, repr((state, warning)))

    def test_import_with_userinfo_resets_only_endpoint(self):
        raw = {"endpoint": "https://login:secret@s3.example", "folder": "/safe"}
        state, warning = normalise_state(raw, self.defaults, FIELDS, OPERATORS)
        self.assertEqual(state["endpoint"], self.defaults["endpoint"])
        self.assertEqual(state["folder"], "/safe")
        self.assertIn("AWS-профиль", warning)

    def test_save_state_refuses_endpoint_with_userinfo(self):
        password = "FIXTURE_PASSWORD_8d37"
        state = default_state()
        state["endpoint"] = f"https://login:{password}@s3.example"
        with self.assertRaises(ValueError):
            save_state(self.path, state)
        self.assertFalse(self.path.exists())

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

    def test_old_settings_without_keep_raw_use_safe_default(self):
        raw = {"folder": "/tmp/result"}
        state, warning = normalise_state(raw, self.defaults, FIELDS, OPERATORS)
        self.assertTrue(state["keep_raw"])
        self.assertIsNone(warning)

    def test_keep_raw_is_saved_and_restored(self):
        state = default_state()
        state["keep_raw"] = False
        save_state(self.path, state)
        loaded, warning = self.load()
        self.assertFalse(loaded["keep_raw"])
        self.assertIsNone(warning)

    def test_date_and_hour_are_saved_and_restored(self):
        state = default_state()
        state.update({"selected_date": "2021-06-15", "hour": 7})
        save_state(self.path, state)
        loaded, warning = self.load()
        self.assertEqual((loaded["selected_date"], loaded["hour"]), ("2021-06-15", 7))
        self.assertIsNone(warning)

    def test_import_rejects_dates_before_2020_and_future_date_or_hour(self):
        for selected_date, hour in (
            ("2019-12-31", 23),
            ((date.today() + timedelta(days=1)).isoformat(), 0),
            (date.today().isoformat(), datetime.now().hour + 1),
        ):
            if hour > 23:
                continue
            raw = {"selected_date": selected_date, "hour": hour}
            with self.subTest(selected_date=selected_date, hour=hour):
                with self.assertRaises(ValueError):
                    normalise_state(raw, self.defaults, FIELDS, OPERATORS)

    def test_recovery_clamps_out_of_range_date_and_hour(self):
        raw = {"selected_date": (date.today() + timedelta(days=1)).isoformat(), "hour": 23}
        state, warning = normalise_state(raw, self.defaults, FIELDS, OPERATORS, recover=True)
        now = datetime.now()
        self.assertEqual(state["selected_date"], now.date().isoformat())
        self.assertLessEqual(state["hour"], now.hour)
        self.assertIn("будущ", warning)

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
