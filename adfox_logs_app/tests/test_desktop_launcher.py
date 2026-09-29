from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import desktop_launcher


class DesktopLauncherTests(unittest.TestCase):
    def test_development_path_is_next_to_launcher(self):
        expected = Path(desktop_launcher.__file__).resolve().parent / "app.py"
        self.assertEqual(desktop_launcher.bundled_path("app.py"), expected)

    def test_bundled_path_uses_pyinstaller_directory(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(desktop_launcher.sys, "_MEIPASS", root, create=True):
                self.assertEqual(
                    desktop_launcher.bundled_path("app.py"),
                    Path(root) / "app.py",
                )

    def test_streamlit_is_available_only_on_localhost(self):
        arguments = desktop_launcher.streamlit_arguments(Path("/tmp/app.py"))
        self.assertIn("--server.address=127.0.0.1", arguments)
        self.assertIn("--server.port=8501", arguments)
        self.assertIn("--server.headless=false", arguments)
        self.assertIn("--server.showEmailPrompt=false", arguments)
        self.assertIn("--logger.hideWelcomeMessage=true", arguments)
        self.assertNotIn("0.0.0.0", arguments)

    def test_browser_opens_after_server_becomes_ready(self):
        checks = iter((False, False, True))
        opened = []
        with patch.object(desktop_launcher.time, "sleep") as sleep:
            result = desktop_launcher.open_browser_when_ready(
                ready=lambda: next(checks), opener=opened.append,
                attempts=3, delay=0.01,
            )
        self.assertTrue(result)
        self.assertEqual(opened, [desktop_launcher.APP_URL])
        self.assertEqual(sleep.call_count, 2)

    def test_browser_is_not_opened_when_server_never_starts(self):
        opened = []
        with patch.object(desktop_launcher.time, "sleep"):
            result = desktop_launcher.open_browser_when_ready(
                ready=lambda: False, opener=opened.append,
                attempts=2, delay=0,
            )
        self.assertFalse(result)
        self.assertEqual(opened, [])
