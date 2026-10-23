"""Command-line interface for YubaPKG."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from yubapkg.core import (
    MANIFEST_NAME,
    PackageError,
    check,
    find_project_root,
    initialize_project,
    install,
    read_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yubapkg", description="YubaLANG package manager")
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create a YubaLANG project")
    init_parser.add_argument("directory", nargs="?", default=".")

    package_parser = commands.add_parser("package", help="manage project dependencies")
    package_commands = package_parser.add_subparsers(dest="package_command", required=True)

    package_init = package_commands.add_parser("init", help="create a project")
    package_init.add_argument("directory", nargs="?", default=".")

    add = package_commands.add_parser("add", help="add a path or Git dependency")
    add.add_argument("name")
    sources = add.add_mutually_exclusive_group(required=True)
    sources.add_argument("--path")
    sources.add_argument("--git")
    add.add_argument("--rev", help="Git branch, tag, or commit")

    remove = package_commands.add_parser("remove", help="remove a dependency")
    remove.add_argument("name")

    package_commands.add_parser("install", help="install locked dependencies")
    update = package_commands.add_parser("update", help="update Git dependencies")
    update.add_argument("name", nargs="?")
    package_commands.add_parser("list", help="list project dependencies")
    package_commands.add_parser("check", help="verify lockfile and installed dependencies")
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


def _run(args: argparse.Namespace) -> int:
    if args.command == "init" or (
        args.command == "package" and args.package_command == "init"
    ):
        root = initialize_project(Path(args.directory))
        print(f"Created YubaLANG project at {root}")
        return 0

    root = _project_root()
    command = args.package_command
    if command == "add":
        source = {"path": args.path} if args.path is not None else {"git": args.git}
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
        install(root)
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
            value = source.get("path", source.get("git", ""))
            print(f"{name}: {value}")
    elif command == "check":
        check(root)
        print("Manifest, lockfile, and installed dependencies are consistent.")
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
