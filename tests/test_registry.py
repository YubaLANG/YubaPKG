import hashlib
import contextlib
import io
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pkg.core import PackageError, check, initialize_project, install, resolve_dependency
from pkg.cli import main
from pkg.registry import _extract_archive, _read_response


def package_archive(name, version, dependencies=None):
    files = {
        "yuba.json": json.dumps(
            {
                "name": name,
                "version": version,
                "entry": "main.yl",
                "yubalang": "1.3",
                "dependencies": dependencies or {},
            }
        ).encode("utf-8"),
        "main.yl": b'text output "registry package"\n',
    }
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for filename, contents in files.items():
            member = tarfile.TarInfo(filename)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))
    return output.getvalue()


class RegistryServer:
    def __init__(self):
        self.artifacts = {}
        self.metadata_requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://example.invalid/")
                    self.end_headers()
                    return
                if self.path == "/v1/search.json":
                    body = owner.search_index
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path.startswith("/v1/packages/"):
                    name = self.path.rsplit("/", 1)[-1].removesuffix(".json")
                    owner.metadata_requests.append(
                        (name, self.headers.get("If-None-Match"))
                    )
                    body = owner.metadata[name]
                    etag = f'"{hashlib.sha256(body).hexdigest()}"'
                    if self.headers.get("If-None-Match") == etag:
                        self.send_response(304)
                        self.send_header("ETag", etag)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("ETag", etag)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                artifact = self.path.rsplit("/", 1)[-1]
                body = owner.artifacts[artifact]
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                pass

        self.metadata = {}
        self.search_index = b'{"schema_version":1,"packages":[]}'
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def add_package(self, name, version, dependencies=None):
        artifact = package_archive(name, version, dependencies)
        digest = hashlib.sha256(artifact).hexdigest()
        filename = f"{name}-{version}.tar.gz"
        self.artifacts[filename] = artifact
        self.metadata[name] = json.dumps(
            {
                "schema_version": 1,
                "name": name,
                "versions": {
                    version: {
                        "yubalang": ["1.3"],
                        "artifact": f"artifacts/{filename}",
                        "sha256": digest,
                    }
                },
            }
        ).encode("utf-8")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class RegistryIntegrationTests(unittest.TestCase):
    def test_search_info_and_outdated_leave_lockfile_unchanged(self):
        with RegistryServer() as registry, tempfile.TemporaryDirectory() as directory:
            registry.add_package("widget", "1.0.0")
            root = initialize_project(Path(directory) / "app")
            manifest_path = root / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dependencies"] = {"widget": {"registry": "*"}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch.dict(os.environ, {"YUBAPKG_REGISTRY_URL": registry.endpoint}):
                install(root)
                metadata = json.loads(registry.metadata["widget"])
                metadata["versions"]["1.1.0"] = dict(
                    metadata["versions"]["1.0.0"]
                )
                registry.metadata["widget"] = json.dumps(metadata).encode("utf-8")
                registry.search_index = json.dumps(
                    {
                        "schema_version": 1,
                        "packages": [
                            {
                                "name": "widget",
                                "description": "Small utility helpers",
                            }
                        ],
                    }
                ).encode("utf-8")
                lock_before = (root / "yuba.lock.json").read_bytes()
                with patch("pathlib.Path.cwd", return_value=root):
                    search_output = io.StringIO()
                    with contextlib.redirect_stdout(search_output):
                        self.assertEqual(main(["package", "search", "utility"]), 0)
                    self.assertIn("widget - Small utility helpers", search_output.getvalue())

                    info_output = io.StringIO()
                    with contextlib.redirect_stdout(info_output):
                        self.assertEqual(main(["package", "info", "widget", "1.0.0"]), 0)
                    self.assertIn("1.0.0:", info_output.getvalue())

                    outdated_output = io.StringIO()
                    with contextlib.redirect_stdout(outdated_output):
                        self.assertEqual(main(["package", "outdated"]), 0)
                    self.assertIn("widget 1.0.0 -> 1.1.0", outdated_output.getvalue())
                self.assertEqual((root / "yuba.lock.json").read_bytes(), lock_before)

    def test_installs_transitive_registry_dependencies_and_uses_cache_offline(self):
        with RegistryServer() as registry, tempfile.TemporaryDirectory() as directory:
            registry.add_package("leaf", "1.1.0")
            registry.add_package(
                "widget", "1.4.0", {"leaf": {"registry": "^1.0.0"}}
            )
            widget_metadata = json.loads(registry.metadata["widget"])
            registry.add_package("widget", "1.6.0")
            newest_metadata = json.loads(registry.metadata["widget"])
            newest_metadata["versions"]["1.6.0"]["yanked"] = True
            newest_metadata["versions"].update(widget_metadata["versions"])
            registry.metadata["widget"] = json.dumps(newest_metadata).encode("utf-8")
            root = initialize_project(Path(directory) / "app")
            (root / "main.yl").write_text("import widget\n", encoding="utf-8")

            with patch.dict(os.environ, {"YUBAPKG_REGISTRY_URL": registry.endpoint}):
                with patch("pathlib.Path.cwd", return_value=root):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(
                            main(
                                [
                                    "package",
                                    "add",
                                    "widget",
                                    "--registry",
                                    "^1.2.0",
                                ]
                            ),
                            0,
                        )
                lock = install(root)
                check(root)
                widget = resolve_dependency(root, "widget")
                self.assertEqual(widget, root / ".yuba" / "packages" / "widget")
                self.assertTrue((widget / ".yuba" / "packages" / "leaf").is_dir())
                with patch("pathlib.Path.cwd", return_value=root):
                    with contextlib.redirect_stdout(io.StringIO()):
                        listed = io.StringIO()
                        with contextlib.redirect_stdout(listed):
                            self.assertEqual(main(["package", "list"]), 0)
                        self.assertIn("widget: ^1.2.0", listed.getvalue())
                        self.assertEqual(main(["package", "update", "widget"]), 0)
                        self.assertEqual(main(["package", "install", "--offline"]), 0)
                        self.assertEqual(main(["package", "install", "--frozen"]), 0)

            self.assertEqual(lock["lock_version"], 3)
            self.assertEqual(lock["dependencies"]["widget"]["resolved"]["version"], "1.4.0")
            self.assertTrue(
                any(name == "widget" and etag for name, etag in registry.metadata_requests)
            )
            language_entry = Path(__file__).resolve().parents[2] / "YubaLANG" / "YubaLANG.py"
            if not language_entry.is_file():
                self.skipTest("Adjacent YubaLANG checkout is not available.")
            environment = os.environ.copy()
            environment.pop("YUBAPKG_REGISTRY_URL", None)
            run = subprocess.run(
                [sys.executable, str(language_entry), "run", str(root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("registry package", run.stdout)

    def test_rejects_bad_artifact_digest_before_install(self):
        with RegistryServer() as registry, tempfile.TemporaryDirectory() as directory:
            registry.add_package("widget", "1.0.0")
            metadata = json.loads(registry.metadata["widget"])
            metadata["versions"]["1.0.0"]["sha256"] = "0" * 64
            registry.metadata["widget"] = json.dumps(metadata).encode("utf-8")
            root = initialize_project(Path(directory) / "app")
            manifest_path = root / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dependencies"] = {"widget": {"registry": "*"}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch.dict(os.environ, {"YUBAPKG_REGISTRY_URL": registry.endpoint}):
                with self.assertRaisesRegex(PackageError, "SHA-256 mismatch"):
                    install(root)
            self.assertFalse((root / ".yuba" / "packages" / "widget").exists())

    def test_failed_reinstall_restores_previous_package(self):
        with RegistryServer() as registry, tempfile.TemporaryDirectory() as directory:
            registry.add_package("widget", "1.0.0")
            root = initialize_project(Path(directory) / "app")
            manifest_path = root / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dependencies"] = {"widget": {"registry": "*"}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch.dict(os.environ, {"YUBAPKG_REGISTRY_URL": registry.endpoint}):
                install(root)
                package = root / ".yuba" / "packages" / "widget"
                (package / "main.yl").write_text("modified\n", encoding="utf-8")
                real_replace = os.replace
                calls = 0

                def fail_install_swap(source, destination):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise OSError("simulated replacement failure")
                    return real_replace(source, destination)

                with patch("pkg.registry.os.replace", side_effect=fail_install_swap):
                    with self.assertRaisesRegex(PackageError, "Cannot install 'widget@1.0.0'"):
                        install(root)

            self.assertEqual(
                (package / "main.yl").read_text(encoding="utf-8"),
                "modified\n",
            )
            self.assertEqual(list(package.parent.glob(".widget.previous.*")), [])

    def test_archive_extraction_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "unsafe.tar.gz"
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as archive:
                data = b"escaped"
                member = tarfile.TarInfo("../outside.txt")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            archive_path.write_bytes(payload.getvalue())

            with self.assertRaisesRegex(PackageError, "unsafe archive entry"):
                _extract_archive(archive_path, root / "extract")
            self.assertFalse((root / "outside.txt").exists())

    def test_registry_redirect_cannot_leave_trusted_origin(self):
        with RegistryServer() as registry:
            with self.assertRaisesRegex(PackageError, "redirects must remain"):
                _read_response(f"{registry.endpoint}/redirect", {}, 1024)

    def test_archive_extraction_rejects_reserved_windows_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "reserved.tar.gz"
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as archive:
                data = b"not portable"
                member = tarfile.TarInfo("CON.txt")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            archive_path.write_bytes(payload.getvalue())

            with self.assertRaisesRegex(PackageError, "unsafe archive entry"):
                _extract_archive(archive_path, root / "extract")


if __name__ == "__main__":
    unittest.main()
