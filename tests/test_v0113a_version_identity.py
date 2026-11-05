from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from local_presence_miner import __version__
from local_presence_miner.cli import main as cli_main
from local_presence_miner.config import AppConfig
from local_presence_miner.database.engine import create_session_factory
from local_presence_miner.database.migrations import initialize_database
from local_presence_miner.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_and_package_versions_are_v0115() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    identity = json.loads(
        (ROOT / "packaging" / "release_identity.json").read_text(encoding="utf-8")
    )
    assert __version__ == "0.1.16"
    assert pyproject["project"]["version"] == "0.1.16"
    assert identity == {
        "human_version": "0.1.16",
        "release_label": "v0.1.16",
        "windows_file_version": "0.1.16.0",
        "windows_product_version": "0.1.16.0",
        "windows_numeric_version": [0, 1, 16, 0],
    }
    build_script = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
    assert '"packaging\\release_identity.json"' in build_script
    assert '"RELEASE_IDENTITY.json"' in build_script


def test_windows_build_uses_verified_pyside_runtime_version() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "PySide6==6.7.3" in pyproject["project"]["dependencies"]
    assert "PySide6==6.7.3" in requirements


def test_cli_version_reports_corrected_identity(capsys) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli_main(["--version"])
    assert stopped.value.code == 0
    assert capsys.readouterr().out.strip() == "MarketLens Local 0.1.16"


def test_main_window_and_sidebar_report_corrected_identity(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    config = AppConfig(
        app_data_dir=tmp_path,
        database_path=tmp_path / "version-ui.sqlite3",
        log_path=tmp_path / "version-ui.log",
        output_dir=tmp_path / "output",
    )
    factory = create_session_factory(config.database_path)
    initialize_database(factory)
    window = MainWindow(config, factory)
    try:
        window.show()
        app.processEvents()
        assert window.windowTitle() == "MarketLens Local 0.1.16"
        labels = {label.text() for label in window.findChildren(QLabel)}
        assert "v0.1.16 · Business opportunity workstation" in labels
    finally:
        window.close()
        app.processEvents()
        factory.kw["bind"].dispose()


def test_windows_metadata_distinguishes_corrected_executable() -> None:
    version_text = (ROOT / "packaging" / "windows" / "version_info.txt").read_text(
        encoding="utf-8"
    )
    assert "filevers=(0, 1, 16, 0)" in version_text
    assert "prodvers=(0, 1, 16, 0)" in version_text
    assert "flags=0x20" in version_text
    assert "StringStruct('FileVersion', '0.1.16.0')" in version_text
    assert "StringStruct('ProductVersion', '0.1.16.0')" in version_text
    assert "StringStruct('SpecialBuild', 'MarketLens Local 0.1.16')" in version_text


def test_release_documentation_uses_corrected_human_identity() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    windows_readme = (ROOT / "packaging" / "windows" / "README.md").read_text(
        encoding="utf-8"
    )
    assert readme.startswith("# MarketLens Local v0.1.16")
    assert windows_readme.startswith("# MarketLens Local v0.1.16")
    assert "FileVersion and ProductVersion are 0.1.16.0" in windows_readme
