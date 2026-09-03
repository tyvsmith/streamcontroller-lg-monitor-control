import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_release_metadata_versions_are_consistent() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())

    locked_project = next(
        package
        for package in lock["package"]
        if package["name"] == "streamcontroller-lg-monitor-control"
    )

    assert manifest["version"] == project["project"]["version"]
    assert project["project"]["version"] == locked_project["version"]
