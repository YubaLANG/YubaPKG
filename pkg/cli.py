"""Command-line interface for YubaPKG."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Sequence

from .core import (
    MANIFEST_NAME,
    PackageError,
    check,
    find_project_root,
    initialize_project,
    install,
    read_manifest,
    read_lockfile,
)
from .registry import (
    configured_registry_url,
    fetch_metadata,
    registry_url,
    search_registry,
    set_registry_url,
)
from .semver import Version, satisfies


_CACHE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_CACHE_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yubapkg",
        description="YubaLANG package manager",
        epilog=(
            "Examples:\n"
            "  yubapkg package add local_math --path ..\\local_math\n"
            "  yubapkg package add text_utils --git https://example.org/text_utils.git --rev v1.0.0\n"
            "  yubapkg package add text_utils --registry ^1.2.0\n"
            "  yubapkg package install --offline\n"
            "  yubapkg package install --frozen\n"
            "Publishing is not supported; no public registry is operated by YubaPKG."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create a YubaLANG project")
    init_parser.add_argument("directory", nargs="?", default=".")

    package_parser = commands.add_parser(
        "package",
        help="manage project dependencies",
        description="Manage path, Git, and static-registry dependencies.",
        epilog=(
            "Examples:\n"
            "  yubapkg package add local_math --path ..\\local_math\n"
            "  yubapkg package add text_utils --git https://example.org/text_utils.git --rev v1.0.0\n"
            "  yubapkg package add text_utils --registry ^1.2.0\n"
            "  yubapkg package install --offline\n"
            "  yubapkg package install --frozen\n"
            "Publishing is not supported; no public registry is operated by YubaPKG."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    package_commands = package_parser.add_subparsers(dest="package_command", required=True)

    package_init = package_commands.add_parser("init", help="create a project")
    package_init.add_argument("directory", nargs="?", default=".")

    add = package_commands.add_parser(
        "add", help="add a path, Git, or registry dependency"
    )
    add.add_argument("name")
    sources = add.add_mutually_exclusive_group(required=True)
    sources.add_argument("--path")
    sources.add_argument("--git")
    sources.add_argument("--registry", help="semantic-version requirement")
    add.add_argument("--rev", help="Git branch, tag, or commit")

    remove = package_commands.add_parser("remove", help="remove a dependency")
    remove.add_argument("name")

    package_install = package_commands.add_parser(
        "install", help="install dependencies and update the lockfile"
    )
    install_modes = package_install.add_mutually_exclusive_group()
    install_modes.add_argument(
        "--offline", action="store_true", help="use only cached packages and metadata"
    )
    install_modes.add_argument(
        "--frozen", action="store_true", help="verify the lockfile without changing it"
    )
    update = package_commands.add_parser("update", help="update dependencies")
    update.add_argument("name", nargs="?")
    package_commands.add_parser("list", help="list project dependencies")
    package_commands.add_parser("check", help="verify lockfile and installed dependencies")
    search = package_commands.add_parser("search", help="search the configured registry")
    search.add_argument("query", nargs="*", help="case-insensitive name/description terms")
    info = package_commands.add_parser("info", help="show registry package releases")
    info.add_argument("name")
    info.add_argument("version", nargs="?")
    package_commands.add_parser("tree", help="show the locked dependency tree")
    outdated = package_commands.add_parser(
        "outdated", help="report newer compatible registry releases without changing the lock"
    )
    outdated.add_argument("--offline", action="store_true", help="use cached registry metadata only")
    cache = package_commands.add_parser("cache", help="inspect and manage this project's cache")
    cache_commands = cache.add_subparsers(dest="cache_command", required=True)
    cache_commands.add_parser("list", help="list cached metadata, artifacts, and packages")
    cache_commands.add_parser("verify", help="verify the lockfile and installed cache")
    clean = cache_commands.add_parser("clean", help="remove selected cached data")
    clean.add_argument("kind", choices=("metadata", "artifacts", "packages"))
    clean.add_argument("target", nargs="?", help="package name or artifact SHA-256; omit to clear that cache")
    config = package_commands.add_parser("config", help="get or set trusted registry configuration")
    config.add_argument("key", choices=("registry",))
    config.add_argument("url", nargs="?", help="registry HTTPS base URL")
    config.add_argument("--global", dest="global_config", action="store_true", help="use user-level configuration")
    config.add_argument("--unset", action="store_true", help="remove the selected configuration")
    return parser


def _project_root() -> Path:
    root = find_project_root(Path.cwd())
    if root is None:
        raise PackageError(
            f"No {MANIFEST_NAME} found in this directory or its parents; "
            "run 'yubapkg init'."
        )
    return root


def _write_manifest(root: Path, manifest: dict) -> None:
    path = root / MANIFEST_NAME
    try:
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        raise PackageError(f"Cannot write '{path}': {error}") from error


def _change_dependency(root: Path, name: str, source: dict | None) -> None:
    manifest = read_manifest(root)
    previous = (root / MANIFEST_NAME).read_bytes()
    if source is None:
        if name not in manifest["dependencies"]:
            raise PackageError(f"Dependency '{name}' is not in the manifest.")
        del manifest["dependencies"][name]
    else:
        manifest["dependencies"][name] = source
    _write_manifest(root, manifest)
    try:
        install(root)
    except PackageError as error:
        try:
            (root / MANIFEST_NAME).write_bytes(previous)
        except OSError as restore_error:
            raise PackageError(
                f"{error}; additionally failed to restore manifest: {restore_error}"
            ) from restore_error
        raise


def _cache_root(root: Path) -> Path:
    return root / ".yuba"


def _cache_paths(root: Path) -> tuple[Path, Path, Path]:
    cache = _cache_root(root)
    return cache / "registry", cache / "artifacts", cache / "packages"


def _run_cache(root: Path, command: str, kind: str | None = None, target: str | None = None) -> None:
    metadata, artifacts, packages = _cache_paths(root)
    if command == "list":
        found = False
        for label, path in (("metadata", metadata), ("artifacts", artifacts), ("packages", packages)):
            if not path.is_dir():
                continue
            try:
                items = sorted(path.iterdir(), key=lambda entry: entry.name.casefold())
            except OSError as error:
                raise PackageError(f"Cannot inspect {label} cache '{path}': {error}") from error
            for item in items:
                print(f"{label}: {item.name}")
                found = True
        if not found:
            print("Cache is empty.")
        return
    if command == "verify":
        check(root)
        print("Lockfile and cached dependencies are consistent.")
        return

    cache_paths = {"metadata": metadata, "artifacts": artifacts, "packages": packages}
    base = cache_paths[kind]
    if base.is_symlink():
        raise PackageError(f"Refusing to clean cache through symbolic link '{base}'.")
    if target is not None:
        if kind == "artifacts":
            if not _CACHE_DIGEST.fullmatch(target):
                raise PackageError("Artifact cache target must be a lowercase SHA-256 digest.")
            targets = [base / f"{target}.tar.gz"]
        else:
            if (
                not _CACHE_NAME.fullmatch(target)
                or target.casefold() in _WINDOWS_RESERVED_NAMES
            ):
                raise PackageError(f"Invalid {kind[:-1]} cache target '{target}'.")
            targets = [base / f"{target}.json"] if kind == "metadata" else [base / target]
            if kind == "metadata":
                targets.append(base / f"{target}.headers.json")
    else:
        try:
            targets = list(base.iterdir()) if base.is_dir() else []
        except OSError as error:
            raise PackageError(f"Cannot inspect {kind} cache '{base}': {error}") from error
    removed = 0
    try:
        for path in targets:
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            removed += 1
    except OSError as error:
        raise PackageError(f"Cannot clean {kind} cache: {error}") from error
    print(f"Removed {removed} {kind} cache item(s).")


def _run_tree(root: Path, manifest: dict) -> None:
    lock = read_lockfile(root)
    print(manifest["name"])

    def render(dependencies: dict, prefix: str, ancestry: frozenset[str]) -> None:
        entries = sorted(dependencies.items())
        for index, (name, entry) in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("resolved"), dict):
                raise PackageError(f"Lockfile entry for '{name}' is malformed.")
            resolved = entry["resolved"]
            source = entry.get("source")
            if not isinstance(source, dict):
                raise PackageError(f"Lockfile source for '{name}' is malformed.")
            if "version" in resolved:
                identity = f"{resolved['version']} [registry]"
            elif "rev" in resolved:
                identity = f"{str(resolved['rev'])[:12]} [git]"
            else:
                identity = f"{resolved.get('path', 'path')} [path]"
            branch = "\\-- " if index == len(entries) - 1 else "|-- "
            print(f"{prefix}{branch}{name} {identity}")
            if name in ancestry:
                raise PackageError(f"Dependency cycle detected in lockfile at '{name}'.")
            nested = entry.get("dependencies", {})
            if not isinstance(nested, dict):
                raise PackageError(f"Lockfile dependencies for '{name}' are malformed.")
            render(nested, prefix + ("    " if index == len(entries) - 1 else "|   "), ancestry | {name})

    dependencies = lock["dependencies"]
    if not isinstance(dependencies, dict):
        raise PackageError("Lockfile dependencies are malformed.")
    render(dependencies, "", frozenset({manifest["name"]}))


def _run_outdated(root: Path, offline: bool) -> None:
    manifest = read_manifest(root)
    lock = read_lockfile(root)
    outdated: list[str] = []

    def visit(package_root: Path, dependencies: dict, ancestry: frozenset[str]) -> None:
        for name, entry in sorted(dependencies.items()):
            if not isinstance(entry, dict) or not isinstance(entry.get("source"), dict):
                raise PackageError(f"Lockfile entry for '{name}' is malformed.")
            source = entry["source"]
            resolved = entry.get("resolved")
            if not isinstance(resolved, dict):
                raise PackageError(f"Lockfile entry for '{name}' is malformed.")
            if "registry" in source:
                requirement = source.get("registry")
                version = resolved.get("version")
                endpoint = resolved.get("registry")
                if (
                    not isinstance(requirement, str)
                    or not isinstance(version, str)
                    or not isinstance(endpoint, str)
                ):
                    raise PackageError(f"Registry lock entry for '{name}' is malformed.")
                metadata = fetch_metadata(package_root, name, registry_url(endpoint), offline)
                locked_release = metadata["versions"].get(version)
                candidates = sorted(
                    (Version.parse(value) for value in metadata["versions"]),
                    reverse=True,
                )
                latest = next(
                    (
                        candidate for candidate in candidates
                        if satisfies(candidate, requirement)
                        and not metadata["versions"][str(candidate)].get("yanked", False)
                        and "1.3" in metadata["versions"][str(candidate)]["yubalang"]
                    ),
                    None,
                )
                if locked_release is None:
                    outdated.append(f"{name} {version} (release missing from registry metadata)")
                elif locked_release.get("yanked", False):
                    outdated.append(f"{name} {version} (yanked)")
                elif latest is not None and latest > Version.parse(version):
                    outdated.append(f"{name} {version} -> {latest}")
            if name in ancestry:
                raise PackageError(f"Dependency cycle detected in lockfile at '{name}'.")
            nested = entry.get("dependencies", {})
            if not isinstance(nested, dict):
                raise PackageError(f"Lockfile dependencies for '{name}' are malformed.")
            if "path" in resolved:
                child_root = (package_root / resolved["path"]).resolve()
            else:
                child_root = package_root / ".yuba" / "packages" / name
            visit(child_root, nested, ancestry | {name})

    if not isinstance(lock["dependencies"], dict):
        raise PackageError("Lockfile dependencies are malformed.")
    visit(root, lock["dependencies"], frozenset({manifest["name"]}))
    if outdated:
        print("\n".join(outdated))
    else:
        print("All locked registry dependencies are up to date.")


def _run(args: argparse.Namespace) -> int:
    if args.command == "init" or (
        args.command == "package" and args.package_command == "init"
    ):
        root = initialize_project(Path(args.directory))
        print(f"Created YubaLANG project at {root}")
        return 0

    command = args.package_command
    discovered_root = find_project_root(Path.cwd())
    if command == "search":
        endpoint = registry_url(root=discovered_root)
        query = " ".join(args.query)
        results = search_registry(endpoint, query)
        if not results:
            print("No packages found.")
        for result in results:
            suffix = f" - {result['description']}" if result["description"] else ""
            print(f"{result['name']}{suffix}")
        return 0
    if command == "info":
        if (
            not _CACHE_NAME.fullmatch(args.name)
            or args.name.casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise PackageError(f"Invalid package name '{args.name}'.")
        endpoint = registry_url(root=discovered_root)
        metadata = fetch_metadata(
            discovered_root or Path.cwd(),
            args.name,
            endpoint,
            use_cache=discovered_root is not None,
        )
        versions = metadata["versions"]
        if args.version is not None:
            if args.version not in versions:
                raise PackageError(f"Registry has no release {args.name}@{args.version}.")
            selected = [args.version]
        else:
            selected = sorted(
                versions,
                key=Version.parse,
                reverse=True,
            )
        print(args.name)
        for version in selected:
            release = versions[version]
            yanked = " (yanked)" if release.get("yanked", False) else ""
            print(
                f"{version}{yanked}: YubaLANG {', '.join(release['yubalang'])}; "
                f"SHA-256 {release['sha256']}; artifact {release['artifact']}"
            )
        return 0
    if command == "config":
        if args.unset and args.url is not None:
            raise PackageError("Do not provide a URL with --unset.")
        if args.url is None and not args.unset:
            value = configured_registry_url(
                discovered_root, global_config=args.global_config
            )
            print(value if value is not None else "Registry URL is not configured.")
            return 0
        path = set_registry_url(
            None if args.unset else args.url,
            root=discovered_root,
            global_config=args.global_config,
        )
        print(f"Updated registry configuration: {path}")
        return 0

    root = discovered_root or _project_root()
    if command == "add":
        if args.path is not None:
            source = {"path": args.path}
        elif args.git is not None:
            source = {"git": args.git}
        else:
            source = {"registry": args.registry}
        if args.rev:
            if args.git is None:
                raise PackageError("--rev can only be used with --git.")
            source["rev"] = args.rev
        _change_dependency(root, args.name, source)
        print(f"Added dependency '{args.name}'.")
    elif command == "remove":
        _change_dependency(root, args.name, None)
        print(f"Removed dependency '{args.name}'.")
    elif command == "install":
        if args.frozen:
            check(root)
            print("Locked dependencies are installed and consistent.")
        else:
            install(root, offline=args.offline)
            print("Dependencies installed and lockfile updated.")
    elif command == "update":
        manifest = read_manifest(root)
        if args.name and args.name not in manifest["dependencies"]:
            raise PackageError(f"Dependency '{args.name}' is not in the manifest.")
        install(root, update={args.name} if args.name else True)
        print("Dependencies updated.")
    elif command == "list":
        manifest = read_manifest(root)
        if not manifest["dependencies"]:
            print("No dependencies.")
        for name in sorted(manifest["dependencies"]):
            source = manifest["dependencies"][name]
            value = source.get(
                "path", source.get("git", source.get("registry", ""))
            )
            print(f"{name}: {value}")
    elif command == "check":
        check(root)
        print("Manifest, lockfile, and installed dependencies are consistent.")
    elif command == "tree":
        _run_tree(root, read_manifest(root))
    elif command == "outdated":
        _run_outdated(root, args.offline)
    elif command == "cache":
        _run_cache(root, args.cache_command, getattr(args, "kind", None), getattr(args, "target", None))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except PackageError as error:
        print(f"yubapkg: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
