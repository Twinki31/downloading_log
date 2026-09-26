"""Checks used by the macOS and Windows launchers.

The file deliberately depends only on Python's standard library and on the copy of
``packaging`` bundled with pip, so it also works in a newly-created virtual
environment before the application dependencies are installed.
"""

import argparse
import hashlib
import importlib
from importlib import metadata
import os
from pathlib import Path
import subprocess
import sys


MINIMUM_PYTHON = (3, 11)
KEY_IMPORTS = {"streamlit": "streamlit", "boto3": "boto3"}


def python_is_supported(version_info=None):
    version_info = sys.version_info if version_info is None else version_info
    return tuple(version_info[:2]) >= MINIMUM_PYTHON


def requirements_fingerprint(requirements_path):
    return hashlib.sha256(Path(requirements_path).read_bytes()).hexdigest()


def _requirement_parser():
    try:
        from pip._vendor.packaging.requirements import Requirement
    except ImportError:
        from packaging.requirements import Requirement
    return Requirement


def read_requirements(requirements_path):
    Requirement = _requirement_parser()
    parsed = []
    for line_number, raw_line in enumerate(
        Path(requirements_path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-", "http://", "https://", "git+")):
            raise ValueError(
                "Unsupported entry in requirements.txt on line {}: {}".format(
                    line_number, line
                )
            )
        parsed.append(Requirement(line))
    return parsed


def _can_import(module_name):
    try:
        importlib.import_module(module_name)
    except Exception:
        return False
    return True


def requirements_are_satisfied(
    requirements_path, version_getter=metadata.version, import_checker=_can_import
):
    for requirement in read_requirements(requirements_path):
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = version_getter(requirement.name)
        except metadata.PackageNotFoundError:
            return False
        if requirement.specifier and installed not in requirement.specifier:
            return False
        module_name = KEY_IMPORTS.get(requirement.name.lower())
        if module_name and not import_checker(module_name):
            return False
    return True


def stamp_matches(requirements_path, stamp_path):
    try:
        saved = Path(stamp_path).read_text(encoding="ascii").strip()
    except (FileNotFoundError, OSError, UnicodeError):
        return False
    return saved == requirements_fingerprint(requirements_path)


def write_stamp(requirements_path, stamp_path):
    stamp = Path(stamp_path)
    temporary = stamp.with_name(stamp.name + ".tmp")
    temporary.write_text(requirements_fingerprint(requirements_path) + "\n", encoding="ascii")
    os.replace(temporary, stamp)


def sync_requirements(
    requirements_path,
    stamp_path,
    runner=subprocess.run,
    version_getter=metadata.version,
    import_checker=_can_import,
    output=print,
):
    requirements_path = Path(requirements_path)
    stamp_path = Path(stamp_path)
    try:
        current = requirements_are_satisfied(
            requirements_path, version_getter, import_checker
        )
        unchanged = stamp_matches(requirements_path, stamp_path)
    except (OSError, UnicodeError, ValueError) as error:
        output("Could not read requirements.txt: {}".format(error))
        return False

    if current and unchanged:
        return True

    output("Installing the required libraries. This needs an internet connection...")
    result = runner(
        [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)]
    )
    if result.returncode != 0:
        output("Dependency installation failed. Check the error above and your internet connection.")
        return False

    try:
        if not requirements_are_satisfied(
            requirements_path, version_getter, import_checker
        ):
            output("The installed libraries still do not satisfy requirements.txt.")
            return False
        write_stamp(requirements_path, stamp_path)
    except (OSError, UnicodeError, ValueError) as error:
        output("Could not verify the installed libraries: {}".format(error))
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-python")
    fingerprint_parser = subparsers.add_parser("fingerprint")
    fingerprint_parser.add_argument("requirements")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("requirements")
    sync_parser.add_argument("stamp")
    arguments = parser.parse_args(argv)

    if arguments.command == "check-python":
        if python_is_supported():
            return 0
        print(
            "Python 3.11 or newer is required; found {}.{}.".format(
                sys.version_info.major, sys.version_info.minor
            )
        )
        return 1
    if arguments.command == "fingerprint":
        print(requirements_fingerprint(arguments.requirements))
        return 0
    return 0 if sync_requirements(arguments.requirements, arguments.stamp) else 1


if __name__ == "__main__":
    raise SystemExit(main())
