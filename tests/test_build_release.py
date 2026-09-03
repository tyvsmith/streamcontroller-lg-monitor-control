from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

import scripts.build_release as build_release_module
from scripts.build_release import (
    PLUGIN_ID,
    PROJECT_NAME,
    ReleaseError,
    build_release,
    extract_changelog,
    main,
    read_versions,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOP_LEVEL_FILES = {
    "LICENSE",
    "README.md",
    "action_base.py",
    "attribution.json",
    "ddcutil.py",
    "dual_mode_state.py",
    "icons.py",
    "main.py",
    "manifest.json",
    "monitor_profile.py",
    "requirements.txt",
}


def test_read_versions_returns_the_release_version_from_all_sources() -> None:
    versions = read_versions(ROOT)

    assert versions == {
        "manifest": "0.3.0",
        "pyproject": "0.3.0",
        "uv.lock": "0.3.0",
    }


def test_build_release_rejects_a_requested_version_that_does_not_match(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReleaseError, match="requested version 9.9.9.*0.3.0"):
        build_release(ROOT, "9.9.9", tmp_path / "release")


def test_build_release_rejects_non_ascii_version_digits(tmp_path: Path) -> None:
    with pytest.raises(ReleaseError, match="exact X.Y.Z"):
        build_release(ROOT, "١.٢.٣", tmp_path / "release")


@pytest.mark.parametrize("version", ("01.2.3", "1.02.3", "1.2.03"))
def test_build_release_rejects_leading_zero_version_components(
    tmp_path: Path, version: str
) -> None:
    with pytest.raises(ReleaseError, match="exact X.Y.Z"):
        build_release(ROOT, version, tmp_path / "release")


def test_extract_changelog_returns_only_the_requested_section(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## [2.0.0] - 2026-09-02\n\n"
        "- New feature\n\n"
        "## [1.0.0]\n\n"
        "- Old feature\n",
        encoding="utf-8",
    )

    assert extract_changelog(changelog, "2.0.0") == "- New feature"

    with pytest.raises(ReleaseError, match="2.1.0"):
        extract_changelog(changelog, "2.1.0")


def test_extract_changelog_rejects_a_non_date_heading_suffix(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [0.3.0] - not-a-date\n\n- Incorrect heading\n", encoding="utf-8"
    )

    with pytest.raises(ReleaseError, match="0.3.0"):
        extract_changelog(changelog, "0.3.0")


def _create_synthetic_release_root(root: Path) -> None:
    (root / "manifest.json").write_text(
        json.dumps({"id": PLUGIN_ID, "version": "0.3.0"}), encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "0.3.0"\n', encoding="utf-8"
    )
    (root / "uv.lock").write_text(
        f'[[package]]\nname = "{PROJECT_NAME}"\nversion = "0.3.0"\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("## [0.3.0]\n\n- Release\n", encoding="utf-8")
    for name in (
        "requirements.txt",
        "README.md",
        "LICENSE",
        "attribution.json",
        "main.py",
        "action_base.py",
        "ddcutil.py",
        "dual_mode_state.py",
        "icons.py",
        "monitor_profile.py",
    ):
        (root / name).write_text("content\n", encoding="utf-8")
    for name in ("actions", "assets", "locales", "monitors", "store"):
        (root / name).mkdir()


def test_read_versions_rejects_manifest_with_an_unexpected_id(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    (source_root / "manifest.json").write_text(
        json.dumps({"id": "wrong.plugin", "version": "0.3.0"}), encoding="utf-8"
    )

    with pytest.raises(ReleaseError, match="manifest id"):
        read_versions(source_root)


def test_read_versions_rejects_a_non_object_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    (source_root / "manifest.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ReleaseError, match="manifest version is missing or invalid"):
        read_versions(source_root)


def test_read_versions_rejects_invalid_utf8_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    (source_root / "manifest.json").write_bytes(b"\xff")

    with pytest.raises(ReleaseError, match="invalid UTF-8.*manifest.json"):
        read_versions(source_root)


def test_build_release_rejects_a_missing_required_runtime_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    (source_root / "main.py").unlink()

    with pytest.raises(ReleaseError, match="required release file is missing.*main.py"):
        build_release(source_root, "0.3.0", tmp_path / "release")


def test_build_release_rejects_symlinks_in_runtime_directories(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    external_file = tmp_path / "external.txt"
    external_file.write_text("must not be packaged\n", encoding="utf-8")
    linked_file = source_root / "assets" / "external.txt"
    linked_file.symlink_to(external_file)
    output_dir = tmp_path / "release"

    with pytest.raises(ReleaseError, match="symlink.*external.txt"):
        build_release(source_root, "0.3.0", output_dir)

    assert not (output_dir / f"{PLUGIN_ID}-0.3.0.zip").exists()


def test_build_release_rejects_output_inside_a_runtime_directory(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)

    with pytest.raises(ReleaseError, match="output directory.*runtime source"):
        build_release(source_root, "0.3.0", source_root / "assets" / "release")


def test_build_release_rejects_an_existing_output_symlink(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    output_target = tmp_path / "existing-output"
    output_target.mkdir()
    output_dir = tmp_path / "release"
    output_dir.symlink_to(output_target, target_is_directory=True)

    with pytest.raises(ReleaseError, match="output directory.*symlink"):
        build_release(source_root, "0.3.0", output_dir)


def test_build_release_rejects_an_existing_output_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    output_dir = tmp_path / "release"
    output_dir.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(ReleaseError, match="output directory must be a directory"):
        build_release(source_root, "0.3.0", output_dir)


def test_build_release_stages_the_transaction_inside_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    output_dir = tmp_path / "release"
    requested_directories: list[Path] = []
    original_mkdtemp = build_release_module.tempfile.mkdtemp

    def record_mkdtemp(*args: object, **kwargs: object) -> str:
        directory = kwargs.get("dir")
        if directory is None and len(args) >= 3:
            directory = args[2]
        requested_directories.append(Path(directory))
        return original_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(build_release_module.tempfile, "mkdtemp", record_mkdtemp)

    build_release(source_root, "0.3.0", output_dir)

    assert requested_directories == [output_dir]
    assert not any(path.name.startswith(".") for path in output_dir.iterdir())


def test_build_release_replaces_only_owned_artifacts(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    output_dir = tmp_path / "release"
    output_dir.mkdir()
    marker = output_dir / "old-marker.txt"
    marker.write_text("old release\n", encoding="utf-8")
    archive_name = f"{PLUGIN_ID}-0.3.0.zip"
    old_contents = {
        archive_name: b"old archive\n",
        f"{archive_name}.sha256": b"old checksum\n",
        "RELEASE_NOTES.md": b"old notes\n",
    }
    for name, contents in old_contents.items():
        (output_dir / name).write_bytes(contents)

    artifacts = build_release(source_root, "0.3.0", output_dir)

    assert marker.read_text(encoding="utf-8") == "old release\n"
    assert {path.name for path in output_dir.iterdir()} == {
        marker.name,
        artifacts.archive.name,
        artifacts.checksum.name,
        artifacts.release_notes.name,
    }
    assert artifacts.archive.read_bytes() != old_contents[artifacts.archive.name]
    assert artifacts.checksum.read_bytes() != old_contents[artifacts.checksum.name]
    assert (
        artifacts.release_notes.read_bytes()
        != old_contents[artifacts.release_notes.name]
    )


def test_build_release_restores_existing_output_when_publication_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    output_dir = tmp_path / "release"
    output_dir.mkdir()
    marker = output_dir / "old-marker.txt"
    marker.write_text("old release\n", encoding="utf-8")
    archive_name = f"{PLUGIN_ID}-0.3.0.zip"
    old_contents = {
        archive_name: b"old archive\n",
        f"{archive_name}.sha256": b"old checksum\n",
        "RELEASE_NOTES.md": b"old notes\n",
    }
    for name, contents in old_contents.items():
        (output_dir / name).write_bytes(contents)
    original_replace = Path.replace
    transaction_directories: list[Path] = []
    original_mkdtemp = build_release_module.tempfile.mkdtemp
    failed = False

    def record_mkdtemp(*args: object, **kwargs: object) -> str:
        transaction = original_mkdtemp(*args, **kwargs)
        transaction_directories.append(Path(transaction))
        return transaction

    def fail_notes_publication(path: Path, target: Path) -> Path:
        nonlocal failed
        if (
            not failed
            and path.name == "RELEASE_NOTES.md"
            and Path(target) == output_dir / path.name
        ):
            failed = True
            raise OSError("simulated publication failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_notes_publication)
    monkeypatch.setattr(build_release_module.tempfile, "mkdtemp", record_mkdtemp)

    with pytest.raises(ReleaseError, match="publish"):
        build_release(source_root, "0.3.0", output_dir)

    assert marker.read_text(encoding="utf-8") == "old release\n"
    assert {path.name for path in output_dir.iterdir()} == {marker.name, *old_contents}
    for name, contents in old_contents.items():
        assert (output_dir / name).read_bytes() == contents
    assert transaction_directories
    assert not transaction_directories[0].exists()


def test_build_release_preserves_recovery_backups_when_rollback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    output_dir = tmp_path / "release"
    output_dir.mkdir()
    marker = output_dir / "old-marker.txt"
    marker.write_text("old release\n", encoding="utf-8")
    archive_name = f"{PLUGIN_ID}-0.3.0.zip"
    old_contents = {
        archive_name: b"old archive\n",
        f"{archive_name}.sha256": b"old checksum\n",
        "RELEASE_NOTES.md": b"old notes\n",
    }
    for name, contents in old_contents.items():
        (output_dir / name).write_bytes(contents)
    transaction_directories: list[Path] = []
    original_mkdtemp = build_release_module.tempfile.mkdtemp
    original_replace = Path.replace

    def record_mkdtemp(*args: object, **kwargs: object) -> str:
        transaction = original_mkdtemp(*args, **kwargs)
        transaction_directories.append(Path(transaction))
        return transaction

    def fail_publication_and_recovery(path: Path, target: Path) -> Path:
        if path.parent.name == "artifact-backup" and path.name == "RELEASE_NOTES.md":
            raise OSError("simulated recovery failure")
        if path.name == "RELEASE_NOTES.md" and Path(target) == output_dir / path.name:
            raise OSError("simulated publication failure")
        return original_replace(path, target)

    monkeypatch.setattr(build_release_module.tempfile, "mkdtemp", record_mkdtemp)
    monkeypatch.setattr(Path, "replace", fail_publication_and_recovery)

    with pytest.raises(ReleaseError, match="recovery directory") as error:
        build_release(source_root, "0.3.0", output_dir)

    recovery_directory = transaction_directories[0]
    assert str(recovery_directory) in str(error.value)
    assert (
        recovery_directory / "artifact-backup" / "RELEASE_NOTES.md"
    ).read_bytes() == (old_contents["RELEASE_NOTES.md"])
    assert marker.read_text(encoding="utf-8") == "old release\n"


def test_cli_discovers_the_project_root_independent_of_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "release"
    monkeypatch.chdir(tmp_path)

    assert main(["--version", "0.3.0", "--output-dir", str(output_dir)]) == 0
    assert {path.name for path in output_dir.iterdir()} == {
        f"{PLUGIN_ID}-0.3.0.zip",
        f"{PLUGIN_ID}-0.3.0.zip.sha256",
        "RELEASE_NOTES.md",
    }


def test_build_release_preserves_nested_allowlisted_directory_content(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    _create_synthetic_release_root(source_root)
    nested_asset = source_root / "assets" / "docs" / "example.txt"
    nested_asset.parent.mkdir()
    nested_asset.write_text("asset documentation\n", encoding="utf-8")

    artifacts = build_release(source_root, "0.3.0", tmp_path / "release")

    with zipfile.ZipFile(artifacts.archive) as archive:
        assert f"{PLUGIN_ID}/assets/docs/example.txt" in archive.namelist()


def test_build_release_creates_an_installable_validated_archive(tmp_path: Path) -> None:
    output_dir = tmp_path / "release"

    artifacts = build_release(ROOT, "0.3.0", output_dir)

    zip_name = f"{PLUGIN_ID}-0.3.0.zip"
    assert PROJECT_NAME == "streamcontroller-lg-monitor-control"
    assert artifacts.archive == output_dir / zip_name
    assert artifacts.checksum == output_dir / f"{zip_name}.sha256"
    assert artifacts.release_notes == output_dir / "RELEASE_NOTES.md"
    assert artifacts.archive.is_file()

    with zipfile.ZipFile(artifacts.archive) as archive:
        names = set(archive.namelist())

    assert all(name.startswith(f"{PLUGIN_ID}/") for name in names)
    top_level_files = {
        name.removeprefix(f"{PLUGIN_ID}/")
        for name in names
        if name.startswith(f"{PLUGIN_ID}/")
        and not name.endswith("/")
        and "/" not in name.removeprefix(f"{PLUGIN_ID}/")
    }
    assert top_level_files == EXPECTED_TOP_LEVEL_FILES
    assert {
        f"{PLUGIN_ID}/actions/DualMode/DualMode.py",
        f"{PLUGIN_ID}/assets/dual-mode.png",
        f"{PLUGIN_ID}/locales/en_US.json",
        f"{PLUGIN_ID}/monitors/lg_ultragear_45gx950a.toml",
        f"{PLUGIN_ID}/store/Thumbnail.png",
    } <= names
    top_level_excluded_directories = ("docs", "tests", ".github", ".omc")
    assert not any(
        name.startswith(f"{PLUGIN_ID}/{directory}/")
        for name in names
        for directory in top_level_excluded_directories
    )
    top_level_excluded_files = ("pyproject.toml", "uv.lock", "AGENTS.md")
    assert not any(
        name == f"{PLUGIN_ID}/{filename}"
        for name in names
        for filename in top_level_excluded_files
    )
    assert not any("/__pycache__/" in name for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)

    digest = hashlib.sha256(artifacts.archive.read_bytes()).hexdigest()
    assert artifacts.checksum.read_text(encoding="utf-8") == f"{digest}  {zip_name}\n"
    assert artifacts.release_notes.read_text(encoding="utf-8") == (
        extract_changelog(ROOT / "CHANGELOG.md", "0.3.0") + "\n"
    )


def test_build_release_generates_reproducible_zip_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1_700_000_000]
    monkeypatch.setattr(build_release_module.zipfile.time, "time", lambda: clock[0])

    first = build_release(ROOT, "0.3.0", tmp_path / "first")
    clock[0] += 120
    second = build_release(ROOT, "0.3.0", tmp_path / "second")

    assert first.archive.read_bytes() == second.archive.read_bytes()
    assert first.checksum.read_text(encoding="utf-8") == second.checksum.read_text(
        encoding="utf-8"
    )
