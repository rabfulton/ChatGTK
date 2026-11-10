"""Exercise the AUR install recipe without installing or downloading packages."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def staged_package(tmp_path_factory):
    build = tmp_path_factory.mktemp("aur-package")
    sources = build / "sources"
    destination = build / "package"
    sources.mkdir()
    destination.mkdir()
    (sources / "ChatGTK").symlink_to(REPOSITORY, target_is_directory=True)
    subprocess.run(
        [
            "bash",
            "-e",
            "-c",
            'source "$1"\nsrcdir=$2\npkgdir=$3\npackage',
            "chatgtk-packaging-test",
            str(REPOSITORY / "PKGBUILD"),
            str(sources),
            str(destination),
        ],
        cwd=build,
        check=True,
        capture_output=True,
        text=True,
    )
    return destination / "usr" / "lib" / "chatgtk_client"


def test_package_includes_all_runtime_python_modules(staged_package):
    expected = {
        path.relative_to(REPOSITORY / "src")
        for path in (REPOSITORY / "src").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    installed = {
        path.relative_to(staged_package) for path in staged_package.rglob("*.py")
    }
    assert expected <= installed, (
        f"Missing packaged modules: {sorted(expected - installed)}"
    )


def test_packaged_application_imports_without_checkout_on_python_path(staged_package):
    environment = {
        **os.environ,
        "PYTHONPATH": str(staged_package),
        "PYTHONDONTWRITEBYTECODE": "1",
        "CHATGTK_DATA_DIR": str(staged_package.parent / "test-data"),
    }
    subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib, pathlib, sys\n"
                "root = pathlib.Path(sys.argv[1]).resolve()\n"
                "for name in ('config', 'model_cards.grok', 'services.streaming_service', "
                "'ui.reasoning_view', 'ChatGTK'):\n"
                "    module = importlib.import_module(name)\n"
                "    assert pathlib.Path(module.__file__).resolve().is_relative_to(root), name\n"
            ),
            str(staged_package),
        ],
        cwd=staged_package.parent,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
