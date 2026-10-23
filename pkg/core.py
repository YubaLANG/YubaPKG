"""Project manifests, dependency locking, and installation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MANIFEST_NAME = "yuba.json"
LOCK_NAME = "yuba.lock.json"
LOCK_VERSION = 1
SUPPORTED_YUBALANG = "1.2"
PACKAGE_CACHE = Path(".yuba") / "packages"
_PACKAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_COMMIT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class PackageError(ValueError):
    """An actionable project or dependency error."""


def find_project_root(path: Path) -> Path | None:
    path = path.resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if (candidate / MANIFEST_NAME).is_file():
            return candidate
    return None


def _validate_name(name: Any) -> None:
    if not isinstance(name, str) or not _PACKAGE_NAME.fullmatch(name):
        raise PackageError(
            f"Invalid package name '{name}'; use a letter followed by letters, "
            "digits, underscores, or hyphens."
        )


def _validate_source(name: str, source: Any) -> None:
    if not isinstance(source, dict):
        raise PackageError(f"Dependency '{name}' must specify a path or Git source.")
    if set(source) == {"path"}:
        if not isinstance(source["path"], str) or not source["path"]:
            raise PackageError(f"Dependency '{name}' has an invalid path source.")
        return
    if set(source) in ({"git"}, {"git", "rev"}):
        if not isinstance(source["git"], str) or not source["git"]:
            raise PackageError(f"Dependency '{name}' has an invalid Git URL.")
        if "rev" in source and (
            not isinstance(source["rev"], str) or not source["rev"]
        ):
            raise PackageError(f"Dependency '{name}' has an invalid Git revision.")
        return
    raise PackageError(
        f"Dependency '{name}' must specify either {{'path': ...}} "
        "or {{'git': ..., 'rev': ...}}."
    )


def read_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PackageError(f"Cannot read manifest '{path}': {error}") from error
    except UnicodeError as error:
        raise PackageError(f"Manifest '{path}' is not valid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise PackageError(
            f"Invalid JSON in '{path}' at line {error.lineno}, column {error.colno}: "
            f"{error.msg}"
        ) from error
    if not isinstance(data, dict):
        raise PackageError(f"Manifest '{path}' must contain a JSON object.")
    for field in ("name", "version", "entry", "yubalang"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise PackageError(f"Manifest '{path}' requires a non-empty '{field}' string.")
    _validate_name(data["name"])
    if data["yubalang"] != SUPPORTED_YUBALANG:
        raise PackageError(
            f"Manifest '{path}' requires YubaLANG {data['yubalang']}; "
            f"this runtime supports {SUPPORTED_YUBALANG}."
        )
    dependencies = data.setdefault("dependencies", {})
    if not isinstance(dependencies, dict):
        raise PackageError(f"Manifest '{path}' field 'dependencies' must be an object.")
    for name, source in dependencies.items():
        _validate_name(name)
        _validate_source(name, source)
    return data


def _read_existing_lock(root: Path) -> dict[str, Any]:
    path = root / LOCK_NAME
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except UnicodeError as error:
        raise PackageError(f"Lockfile '{path}' is not valid UTF-8: {error}") from error
    except json.JSONDecodeError as error:
        raise PackageError(
            f"Invalid JSON in '{path}' at line {error.lineno}, column {error.colno}: "
            f"{error.msg}"
        ) from error
    except OSError as error:
        raise PackageError(f"Cannot read lockfile '{path}': {error}") from error
    if not isinstance(lock, dict):
        raise PackageError(f"Lockfile '{path}' must contain a JSON object.")
    dependencies = lock.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise PackageError(f"Lockfile '{path}' has an invalid dependencies object.")
    return lock


def read_lockfile(root: Path) -> dict[str, Any]:
    path = root / LOCK_NAME
    lock = _read_existing_lock(root)
    if (
        lock.get("lock_version") != LOCK_VERSION
        or not isinstance(lock.get("dependencies"), dict)
    ):
        raise PackageError(
            f"Unsupported or malformed lockfile '{path}'; run 'yubapkg package install'."
        )
    return lock


def _write_json(path: Path, data: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(data, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary_path, path)
    except OSError as error:
        raise PackageError(f"Cannot write '{path}': {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        raise PackageError(f"Cannot run Git: {error}") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PackageError(f"Git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def _resolve_git_revision(url: str, requested: str | None, root: Path) -> str:
    reference = requested or "HEAD"
    result = _git(root, "ls-remote", url, reference, f"{reference}^{{}}")
    revisions = [
        line.split() for line in result.splitlines() if len(line.split()) == 2
    ]
    peeled = [revision for revision, ref in revisions if ref.endswith("^{}")]
    matching = [revision for revision, _ in revisions]
    revision = (peeled or matching or [None])[0]
    if revision is None:
        raise PackageError(f"Git source '{url}' has no revision matching '{reference}'.")
    if not _COMMIT_ID.fullmatch(revision):
        raise PackageError(f"Git source '{url}' returned an invalid commit ID.")
    return revision


def _dependency_lock(
    root: Path,
    name: str,
    source: dict[str, str],
    old_entry: Any,
    update: bool,
) -> dict[str, Any]:
    if "path" in source:
        path = (root / source["path"]).resolve()
        if not path.is_dir():
            raise PackageError(f"Path dependency '{name}' does not exist: {path}")
        if not (path / MANIFEST_NAME).is_file():
            raise PackageError(f"Path dependency '{name}' has no {MANIFEST_NAME}: {path}")
        return {
            "source": source,
            "resolved": {"path": Path(source["path"]).as_posix()},
        }

    url = source["git"]
    old_source = old_entry.get("source") if isinstance(old_entry, dict) else None
    old_resolved = old_entry.get("resolved") if isinstance(old_entry, dict) else None
    if (
        not update
        and source.get("rev") is None
        and old_source == {"git": url}
        and isinstance(old_resolved, dict)
        and isinstance(old_resolved.get("rev"), str)
        and _COMMIT_ID.fullmatch(old_resolved["rev"])
    ):
        revision = old_resolved["rev"]
    else:
        revision = _resolve_git_revision(url, source.get("rev"), root)
    lock_source = {"git": url}
    if "rev" in source:
        lock_source["rev"] = source["rev"]
    return {"source": lock_source, "resolved": {"rev": revision}}


def _install_git(root: Path, name: str, url: str, revision: str) -> Path:
    if not _COMMIT_ID.fullmatch(revision):
        raise PackageError(f"Lockfile has an invalid Git revision for '{name}'.")
    destination = root / PACKAGE_CACHE / name
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PackageError(f"Cannot create package cache '{destination.parent}': {error}") from error
    if (destination / ".git").is_dir():
        origin = _git(destination, "remote", "get-url", "origin")
        if origin != url:
            _git(destination, "remote", "set-url", "origin", url)
        _git(destination, "fetch", "--quiet", "origin")
    elif destination.exists():
        raise PackageError(
            f"Package cache path exists but is not a Git checkout: {destination}"
        )
    else:
        _git(root, "clone", "--quiet", "--no-checkout", url, str(destination))
    _git(destination, "checkout", "--quiet", "--detach", revision)
    if not (destination / MANIFEST_NAME).is_file():
        raise PackageError(f"Git dependency '{name}' has no {MANIFEST_NAME}.")
    return destination


def _validate_dependency(root: Path, name: str, dependency_root: Path) -> None:
    dependency_manifest = read_manifest(dependency_root)
    if dependency_manifest["name"] != name:
        raise PackageError(
            f"Dependency '{name}' points to package "
            f"'{dependency_manifest['name']}' at {dependency_root}."
        )
    resolve_entry(dependency_root, dependency_manifest)


def install(root: Path, update: bool | set[str] = False) -> dict[str, Any]:
    manifest = read_manifest(root)
    old_dependencies = _read_existing_lock(root).get("dependencies", {})
    locked: dict[str, Any] = {}
    for name in sorted(manifest["dependencies"]):
        source = manifest["dependencies"][name]
        entry = _dependency_lock(
            root,
            name,
            source,
            old_dependencies.get(name),
            update is True or isinstance(update, set) and name in update,
        )
        locked[name] = entry
        resolved = entry["resolved"]
        if "path" in resolved:
            dependency_root = (root / resolved["path"]).resolve()
        else:
            dependency_root = _install_git(root, name, source["git"], resolved["rev"])
        _validate_dependency(root, name, dependency_root)

    lock = {"lock_version": LOCK_VERSION, "dependencies": locked}
    _write_json(root / LOCK_NAME, lock)
    return lock


def check(root: Path) -> None:
    manifest = read_manifest(root)
    lock = read_lockfile(root)
    manifest_dependencies = manifest["dependencies"]
    locked_dependencies = lock["dependencies"]
    if set(manifest_dependencies) != set(locked_dependencies):
        raise PackageError(
            "Manifest dependencies do not match the lockfile; run "
            "'yubapkg package install'."
        )
    for name, source in manifest_dependencies.items():
        entry = locked_dependencies.get(name)
        if not isinstance(entry, dict) or entry.get("source") != source:
            raise PackageError(
                f"Dependency '{name}' differs from the lockfile; "
                "run 'yubapkg package install'."
            )
        resolved = entry.get("resolved")
        if not isinstance(resolved, dict):
            raise PackageError(f"Lockfile entry for '{name}' is malformed.")
        if "path" in source:
            expected_path = Path(source["path"]).as_posix()
            if resolved.get("path") != expected_path:
                raise PackageError(f"Lockfile path for '{name}' is inconsistent.")
            dependency_root = (root / resolved["path"]).resolve()
            if not dependency_root.is_dir():
                raise PackageError(f"Path dependency '{name}' is missing: {dependency_root}")
        else:
            revision = resolved.get("rev")
            if not isinstance(revision, str) or not _COMMIT_ID.fullmatch(revision):
                raise PackageError(f"Lockfile entry for '{name}' has no valid Git revision.")
            dependency_root = root / PACKAGE_CACHE / name
            if not (dependency_root / ".git").is_dir():
                raise PackageError(
                    f"Git dependency '{name}' is not installed; run "
                    "'yubapkg package install'."
                )
            installed_revision = _git(dependency_root, "rev-parse", "HEAD")
            if installed_revision != revision:
                raise PackageError(
                    f"Installed Git dependency '{name}' is at {installed_revision}, "
                    f"not locked revision {revision}."
                )
            origin = _git(dependency_root, "remote", "get-url", "origin")
            if origin != source["git"]:
                raise PackageError(
                    f"Installed Git dependency '{name}' has origin '{origin}', "
                    f"not '{source['git']}'."
                )
        _validate_dependency(root, name, dependency_root)


def resolve_dependency(root: Path, name: str) -> Path | None:
    manifest = read_manifest(root)
    if name not in manifest["dependencies"]:
        return None
    check(root)
    entry = read_lockfile(root)["dependencies"][name]
    resolved = entry["resolved"]
    if "path" in resolved:
        return (root / resolved["path"]).resolve()
    return (root / PACKAGE_CACHE / name).resolve()


def resolve_entry(root: Path, manifest: dict[str, Any]) -> Path:
    entry = Path(manifest["entry"])
    package_root = root.resolve()
    resolved = (package_root / entry).resolve()
    if entry.is_absolute() or package_root not in resolved.parents:
        raise PackageError(
            f"Package entry '{manifest['entry']}' must stay inside {package_root}."
        )
    if not resolved.is_file():
        raise PackageError(f"Package entry file does not exist: {resolved}")
    return resolved


def initialize_project(path: Path) -> Path:
    root = path.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PackageError(f"Cannot create project directory '{root}': {error}") from error
    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists():
        raise PackageError(f"Manifest already exists: {manifest_path}")
    name = re.sub(r"[^A-Za-z0-9_-]", "-", root.name) or "project"
    if not name[0].isalpha():
        name = f"project-{name}"
    _validate_name(name)
    _write_json(
        manifest_path,
        {
            "name": name,
            "version": "0.1.0",
            "entry": "main.yl",
            "yubalang": SUPPORTED_YUBALANG,
            "dependencies": {},
        },
    )
    entry = root / "main.yl"
    if not entry.exists():
        try:
            entry.write_text('text output "Hello from YubaLANG!"\n', encoding="utf-8")
        except OSError as error:
            manifest_path.unlink(missing_ok=True)
            raise PackageError(f"Cannot create entry file '{entry}': {error}") from error
    return root
