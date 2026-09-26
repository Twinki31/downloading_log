from importlib import metadata
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import launcher_env


class Result:
    def __init__(self, returncode):
        self.returncode = returncode


class LauncherEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.requirements = self.root / "requirements.txt"
        self.stamp = self.root / "requirements.sha256"
        self.requirements.write_text(
            "streamlit>=1.40,<2\nboto3>=1.35,<2\n", encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def versions(values):
        def get_version(name):
            if name not in values:
                raise metadata.PackageNotFoundError(name)
            return values[name]

        return get_version

    def test_python_311_or_newer_is_required(self):
        self.assertFalse(launcher_env.python_is_supported((3, 10, 20)))
        self.assertTrue(launcher_env.python_is_supported((3, 11, 0)))
        self.assertTrue(launcher_env.python_is_supported((3, 14, 7)))

    def test_clean_environment_installs_and_writes_stamp(self):
        installed = {}
        calls = []

        def runner(command):
            calls.append(command)
            installed.update(streamlit="1.40.0", boto3="1.35.0")
            return Result(0)

        self.assertTrue(
            launcher_env.sync_requirements(
                self.requirements,
                self.stamp,
                runner=runner,
                version_getter=self.versions(installed),
                import_checker=lambda _name: True,
                output=lambda _message: None,
            )
        )
        self.assertEqual(
            calls,
            [[sys.executable, "-m", "pip", "install", "-r", str(self.requirements)]],
        )
        self.assertTrue(launcher_env.stamp_matches(self.requirements, self.stamp))

    def test_unchanged_satisfied_requirements_do_not_run_pip(self):
        launcher_env.write_stamp(self.requirements, self.stamp)
        calls = []
        self.assertTrue(
            launcher_env.sync_requirements(
                self.requirements,
                self.stamp,
                runner=lambda command: calls.append(command),
                version_getter=self.versions(
                    {"streamlit": "1.50.0", "boto3": "1.40.0"}
                ),
                import_checker=lambda _name: True,
                output=lambda _message: None,
            )
        )
        self.assertEqual(calls, [])

    def test_changed_requirements_run_pip_and_replace_stamp(self):
        launcher_env.write_stamp(self.requirements, self.stamp)
        old_stamp = self.stamp.read_text(encoding="ascii")
        self.requirements.write_text(
            "streamlit>=1.41,<2\nboto3>=1.35,<2\n", encoding="utf-8"
        )
        calls = []

        def runner(command):
            calls.append(command)
            return Result(0)

        self.assertTrue(
            launcher_env.sync_requirements(
                self.requirements,
                self.stamp,
                runner=runner,
                version_getter=self.versions(
                    {"streamlit": "1.50.0", "boto3": "1.40.0"}
                ),
                import_checker=lambda _name: True,
                output=lambda _message: None,
            )
        )
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(self.stamp.read_text(encoding="ascii"), old_stamp)

    def test_failed_pip_does_not_write_new_stamp(self):
        launcher_env.write_stamp(self.requirements, self.stamp)
        old_stamp = self.stamp.read_text(encoding="ascii")
        self.requirements.write_text("streamlit>=1.60,<2\n", encoding="utf-8")

        self.assertFalse(
            launcher_env.sync_requirements(
                self.requirements,
                self.stamp,
                runner=lambda _command: Result(1),
                version_getter=self.versions({"streamlit": "1.50.0"}),
                import_checker=lambda _name: True,
                output=lambda _message: None,
            )
        )
        self.assertEqual(self.stamp.read_text(encoding="ascii"), old_stamp)

    def test_out_of_range_installed_version_runs_pip(self):
        launcher_env.write_stamp(self.requirements, self.stamp)
        installed = {"streamlit": "1.39.0", "boto3": "1.40.0"}
        calls = []

        def runner(command):
            calls.append(command)
            installed["streamlit"] = "1.40.0"
            return Result(0)

        self.assertTrue(
            launcher_env.sync_requirements(
                self.requirements,
                self.stamp,
                runner=runner,
                version_getter=self.versions(installed),
                import_checker=lambda _name: True,
                output=lambda _message: None,
            )
        )
        self.assertEqual(len(calls), 1)

    def test_partial_install_with_broken_key_import_runs_pip(self):
        launcher_env.write_stamp(self.requirements, self.stamp)
        imports_work = {"value": False}
        calls = []

        def runner(command):
            calls.append(command)
            imports_work["value"] = True
            return Result(0)

        self.assertTrue(
            launcher_env.sync_requirements(
                self.requirements,
                self.stamp,
                runner=runner,
                version_getter=self.versions(
                    {"streamlit": "1.50.0", "boto3": "1.40.0"}
                ),
                import_checker=lambda _name: imports_work["value"],
                output=lambda _message: None,
            )
        )
        self.assertEqual(len(calls), 1)

    def test_fingerprint_cli_accepts_path_with_spaces(self):
        spaced_root = self.root / "project with spaces"
        spaced_root.mkdir()
        requirements = spaced_root / "requirements file.txt"
        requirements.write_text("streamlit>=1.40,<2\n", encoding="utf-8")
        helper = Path(launcher_env.__file__)
        result = subprocess.run(
            [sys.executable, str(helper), "fingerprint", str(requirements)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.strip(), launcher_env.requirements_fingerprint(requirements)
        )

    def test_launchers_quote_paths_and_use_the_shared_helper(self):
        app_root = Path(__file__).parents[1]
        macos = (app_root / "start.command").read_text(encoding="utf-8")
        windows = (app_root / "start_windows.bat").read_text(encoding="utf-8")

        self.assertIn('cd "$(dirname "$0")"', macos)
        self.assertIn('".venv/bin/python" launcher_env.py sync', macos)
        self.assertIn('cd /d "%~dp0"', windows)
        self.assertIn('".venv\\Scripts\\python.exe" launcher_env.py sync', windows)
        self.assertNotIn("requirements-tested.txt", macos + windows)
        self.assertNotIn("import streamlit, boto3", macos + windows)


if __name__ == "__main__":
    unittest.main()
