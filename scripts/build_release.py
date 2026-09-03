from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib
import zipfile


PLUGIN_ID = "me_tysmith_LgMonitorControls"
PROJECT_NAME = "streamcontroller-lg-monitor-control"

_VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_COMPRESSION_LEVEL = 9
_ZIP_FILE_MODE = 0o100644
_ZIP_DIRECTORY_MODE = 0o40755
_REQUIRED_ROOT_FILES = (
    "manifest.json",
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
)
_REQUIRED_DIRECTORIES = ("actions", "assets", "locales", "monitors", "store")


class ReleaseError(RuntimeError):
    """Raised when the project cannot produce a valid release artifact."""


class _PublicationRecoveryError(ReleaseError):
    """Raised when transaction backups require manual recovery."""


@dataclass(frozen=True)
class ReleaseArtifacts:
    archive: Path
    checksum: Path
    release_notes: Path


def _read_toml(path: Path) -> dict[str, object]:
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReleaseError(f"required file is missing: {path}") from error
    except UnicodeError as error:
        raise ReleaseError(f"invalid UTF-8 in {path}") from error
    try:
        return tomllib.loads(contents)
    except tomllib.TOMLDecodeError as error:
        raise ReleaseError(f"invalid TOML in {path}: {error}") from error


def _version_from_manifest(path: Path) -> str:
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReleaseError(f"required file is missing: {path}") from error
    except UnicodeError as error:
        raise ReleaseError(f"invalid UTF-8 in {path}") from error
    try:
        manifest = json.loads(contents)
    except json.JSONDecodeError as error:
        raise ReleaseError(f"invalid JSON in {path}: {error}") from error

    if not isinstance(manifest, dict):
        raise ReleaseError(f"manifest version is missing or invalid: {path}")
    if manifest.get("id") != PLUGIN_ID:
        raise ReleaseError(f"manifest id must equal {PLUGIN_ID!r}: {path}")
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ReleaseError(f"manifest version is missing or invalid: {path}")
    return version


def _version_from_pyproject(path: Path) -> str:
    pyproject = _read_toml(path)
    project = pyproject.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise ReleaseError(f"project version is missing or invalid: {path}")
    return project["version"]


def _version_from_lock(path: Path) -> str:
    lock = _read_toml(path)
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ReleaseError(f"lock package list is missing: {path}")

    for package in packages:
        if isinstance(package, dict) and package.get("name") == PROJECT_NAME:
            version = package.get("version")
            if isinstance(version, str):
                return version
            raise ReleaseError(f"lock package version is missing or invalid: {path}")
    raise ReleaseError(f"lock package {PROJECT_NAME!r} is missing: {path}")


def read_versions(root: Path) -> dict[str, str]:
    """Return the release versions recorded by each project metadata source."""
    versions = {
        "manifest": _version_from_manifest(root / "manifest.json"),
        "pyproject": _version_from_pyproject(root / "pyproject.toml"),
        "uv.lock": _version_from_lock(root / "uv.lock"),
    }
    if len(set(versions.values())) != 1:
        sources = ", ".join(f"{source}={value}" for source, value in versions.items())
        raise ReleaseError(f"release version mismatch: {sources}")
    return versions


def extract_changelog(path: Path, version: str) -> str:
    """Extract the non-empty body of an exact second-level changelog heading."""
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReleaseError(f"changelog is missing: {path}") from error
    except UnicodeError as error:
        raise ReleaseError(f"invalid UTF-8 in {path}") from error
    lines = contents.splitlines()

    heading = re.compile(
        rf"^## \[{re.escape(version)}\](?: - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})?$"
    )
    for index, line in enumerate(lines):
        if heading.fullmatch(line):
            body: list[str] = []
            for following_line in lines[index + 1 :]:
                if following_line.startswith("## "):
                    break
                body.append(following_line)
            notes = "\n".join(body).strip()
            if notes:
                return notes
            raise ReleaseError(f"changelog section for {version} is empty")
    raise ReleaseError(f"changelog section for {version} is missing")


def _validate_version(version: str) -> None:
    if not _VERSION_PATTERN.fullmatch(version):
        raise ReleaseError(f"version must use exact X.Y.Z form, got {version!r}")


def _validate_release_sources(root: Path) -> tuple[list[Path], list[Path]]:
    files = [root / name for name in _REQUIRED_ROOT_FILES]
    directories = [root / name for name in _REQUIRED_DIRECTORIES]

    for path in files:
        if path.is_symlink():
            raise ReleaseError(f"symlink is not allowed in release sources: {path}")
        if not path.is_file():
            raise ReleaseError(f"required release file is missing: {path}")
    for path in directories:
        if path.is_symlink():
            raise ReleaseError(f"symlink is not allowed in release sources: {path}")
        if not path.is_dir():
            raise ReleaseError(f"required release directory is missing: {path}")
        for nested_path in path.rglob("*"):
            if nested_path.is_symlink():
                raise ReleaseError(
                    f"symlink is not allowed in release sources: {nested_path}"
                )
    return files, directories


def _ignore_release_extras(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
    }


def _normalized_zip_info(name: str, *, is_directory: bool) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    entry.create_system = 3
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry._compresslevel = _ZIP_COMPRESSION_LEVEL
    entry.external_attr = (
        _ZIP_DIRECTORY_MODE if is_directory else _ZIP_FILE_MODE
    ) << 16
    if is_directory:
        entry.external_attr |= 0x10
    return entry


def _write_archive(stage_root: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=_ZIP_COMPRESSION_LEVEL,
    ) as archive:
        archive.writestr(
            _normalized_zip_info(f"{PLUGIN_ID}/", is_directory=True),
            b"",
            compress_type=zipfile.ZIP_DEFLATED,
            compresslevel=_ZIP_COMPRESSION_LEVEL,
        )
        for source in sorted(path for path in stage_root.rglob("*") if path.is_file()):
            name = (Path(PLUGIN_ID) / source.relative_to(stage_root)).as_posix()
            archive.writestr(
                _normalized_zip_info(name, is_directory=False),
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=_ZIP_COMPRESSION_LEVEL,
            )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_output_directory(
    root: Path, output_dir: Path, source_directories: list[Path]
) -> Path:
    if output_dir.is_symlink():
        raise ReleaseError(f"output directory must not be a symlink: {output_dir}")
    resolved_output = output_dir.resolve()
    if _is_relative_to(root, resolved_output):
        raise ReleaseError(
            f"output directory must not contain the project root: {output_dir}"
        )
    for source_directory in source_directories:
        if _is_relative_to(resolved_output, source_directory.resolve()):
            raise ReleaseError(
                f"output directory must not be inside runtime source directory: {output_dir}"
            )
    if output_dir.exists() and not output_dir.is_dir():
        raise ReleaseError(f"output directory must be a directory: {output_dir}")
    return resolved_output


def _publish_artifacts(
    staged_paths: list[Path], output_paths: list[Path], temporary: Path
) -> None:
    for output_path in output_paths:
        if output_path.is_symlink():
            raise ReleaseError(
                f"release artifact destination must not be a symlink: {output_path}"
            )
        if output_path.exists() and not output_path.is_file():
            raise ReleaseError(
                f"release artifact destination must be a regular file: {output_path}"
            )

    backup_directory = temporary / "artifact-backup"
    backup_directory.mkdir()
    backups: list[tuple[Path, Path]] = []
    published_paths: list[Path] = []
    try:
        for output_path in output_paths:
            if output_path.exists():
                backup_path = backup_directory / output_path.name
                output_path.replace(backup_path)
                backups.append((output_path, backup_path))
        for staged_path, output_path in zip(staged_paths, output_paths, strict=True):
            staged_path.replace(output_path)
            published_paths.append(output_path)
    except OSError as error:
        rollback_errors: list[OSError] = []
        for output_path in published_paths:
            try:
                output_path.unlink()
            except OSError as rollback_error:
                rollback_errors.append(rollback_error)
        for output_path, backup_path in backups:
            if backup_path.exists():
                try:
                    backup_path.replace(output_path)
                except OSError as rollback_error:
                    rollback_errors.append(rollback_error)
        if rollback_errors:
            raise _PublicationRecoveryError(
                "failed to publish release artifacts and restore backups; "
                f"recovery directory: {temporary}"
            ) from rollback_errors[0]
        raise ReleaseError(f"failed to publish release artifacts: {error}") from error


def build_release(root: Path, version: str, output_dir: Path) -> ReleaseArtifacts:
    """Build an installable release archive and its checksum and release notes."""
    root = root.resolve()
    _validate_version(version)
    versions = read_versions(root)
    project_version = versions["manifest"]
    if version != project_version:
        raise ReleaseError(
            f"requested version {version} does not match project version {project_version}"
        )

    notes = extract_changelog(root / "CHANGELOG.md", version)
    files, directories = _validate_release_sources(root)
    output_dir = _validate_output_directory(root, output_dir, directories)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if not output_dir.exists():
        output_dir.mkdir()

    archive_name = f"{PLUGIN_ID}-{version}.zip"
    checksum_name = f"{archive_name}.sha256"
    temporary_path = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-transaction-", dir=output_dir)
    )
    try:
        stage_root = temporary_path / PLUGIN_ID
        stage_root.mkdir()
        for source in files:
            shutil.copy2(source, stage_root / source.name)
        for source in directories:
            shutil.copytree(
                source,
                stage_root / source.name,
                ignore=_ignore_release_extras,
            )

        staged_output = temporary_path / output_dir.name
        staged_output.mkdir()
        staged_archive = staged_output / archive_name
        _write_archive(stage_root, staged_archive)
        digest = hashlib.sha256(staged_archive.read_bytes()).hexdigest()
        staged_checksum = staged_output / checksum_name
        staged_checksum.write_text(f"{digest}  {archive_name}\n", encoding="utf-8")
        staged_notes = staged_output / "RELEASE_NOTES.md"
        staged_notes.write_text(f"{notes}\n", encoding="utf-8")

        archive = output_dir / archive_name
        checksum = output_dir / checksum_name
        release_notes = output_dir / staged_notes.name
        _publish_artifacts(
            [staged_archive, staged_checksum, staged_notes],
            [archive, checksum, release_notes],
            temporary_path,
        )
    except _PublicationRecoveryError:
        raise
    except Exception:
        shutil.rmtree(temporary_path)
        raise
    else:
        shutil.rmtree(temporary_path)

    return ReleaseArtifacts(
        archive=archive, checksum=checksum, release_notes=release_notes
    )


class _ReleaseArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = _ReleaseArgumentParser(
        description="Build validated StreamController release artifacts."
    )
    parser.add_argument(
        "--version", required=True, help="Release version in X.Y.Z form."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist/release"),
        help="Directory for release artifacts (default: dist/release).",
    )
    arguments = parser.parse_args(argv)
    try:
        project_root = Path(__file__).resolve().parents[1]
        artifacts = build_release(project_root, arguments.version, arguments.output_dir)
    except (ReleaseError, OSError) as error:
        print(f"release build failed: {error}", file=sys.stderr)
        return 1

    print(f"created {artifacts.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
