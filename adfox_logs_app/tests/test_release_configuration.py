from pathlib import Path
import tempfile
import unittest

from app_version import APP_VERSION, read_version, require_release_tag


APP_DIR = Path(__file__).parents[1]
ROOT = APP_DIR.parent


class VersionTests(unittest.TestCase):
    def test_displayed_version_comes_from_version_file(self):
        self.assertEqual(APP_VERSION, (APP_DIR / "VERSION").read_text().strip())

    def test_only_plain_semantic_version_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "VERSION"
            for invalid in ("v1.2.3", "1.2", "01.2.3", "1.2.3; echo unsafe"):
                with self.subTest(invalid=invalid):
                    path.write_text(invalid, encoding="ascii")
                    with self.assertRaises(ValueError):
                        read_version(path)

    def test_release_tag_must_match_version(self):
        self.assertEqual(require_release_tag("v1.2.3", "1.2.3"), "v1.2.3")
        with self.assertRaises(ValueError):
            require_release_tag("v1.2.4", "1.2.3")


class ReleaseConfigurationTests(unittest.TestCase):
    def test_workflow_has_manual_artifacts_and_tag_only_release(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("tags:\n      - \"v*\"", workflow)
        self.assertIn("github.event_name == 'push'", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("AWS_EC2_METADATA_DISABLED", workflow)

    def test_release_contains_only_expected_installers(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("AdFox-Logs-Windows-Setup.exe", workflow)
        self.assertIn("AdFox-Logs-macOS.dmg", workflow)
        self.assertIn('find release-assets -type f', workflow)
        self.assertIn("! -name 'AdFox Logs.app' ! -name 'Applications' ! -name '.*'", workflow)

    def test_windows_installer_creates_shortcuts_from_packaged_exe(self):
        installer = (APP_DIR / "windows_installer.iss").read_text(encoding="utf-8")
        self.assertIn('Source: "dist\\{#MyAppExeName}"', installer)
        self.assertIn('Name: "{autoprograms}\\{#MyAppName}"', installer)
        self.assertIn('Name: "{autodesktop}\\{#MyAppName}"', installer)
        self.assertNotIn("*.py", installer)

    def test_windows_build_reads_validated_version_without_shell_execution(self):
        build_script = (APP_DIR / "build_windows.bat").read_text(encoding="utf-8")
        self.assertIn('set /p "APP_VERSION="<VERSION', build_script)
        self.assertNotIn("from app_version import APP_VERSION", build_script)

    def test_readme_has_one_latest_release_link(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(readme.count("/releases/latest"), 1)


if __name__ == "__main__":
    unittest.main()
