import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pkg.core import PackageError, check, initialize_project, install


def write_package(root: Path, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "yuba.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "entry": "main.yl",
                "yubalang": "1.2",
                "dependencies": {},
            }
        ),
        encoding="utf-8",
    )
    (root / "main.yl").write_text('text output "ok"\n', encoding="utf-8")


class PackageCoreTests(unittest.TestCase):
    def test_init_creates_project_manifest_and_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            project = initialize_project(Path(directory) / "sample")
            manifest = json.loads((project / "yuba.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], "sample")
            self.assertEqual(manifest["yubalang"], "1.3")
            self.assertTrue((project / "main.yl").is_file())

    def test_installs_nested_graph_in_yubalang_lockfile_format(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = initialize_project(root / "project")
            first = root / "first"
            second = root / "second"
            write_package(first, "first")
            write_package(second, "second")

            first_manifest_path = first / "yuba.json"
            first_manifest = json.loads(
                first_manifest_path.read_text(encoding="utf-8")
            )
            first_manifest["dependencies"] = {"second": {"path": "../second"}}
            first_manifest_path.write_text(json.dumps(first_manifest), encoding="utf-8")

            project_manifest_path = project / "yuba.json"
            project_manifest = json.loads(
                project_manifest_path.read_text(encoding="utf-8")
            )
            project_manifest["dependencies"] = {"first": {"path": "../first"}}
            project_manifest_path.write_text(
                json.dumps(project_manifest), encoding="utf-8"
            )

            lock = install(project)
            first_entry = lock["dependencies"]["first"]
            self.assertEqual(lock["lock_version"], 2)
            self.assertEqual(
                first_entry["package"],
                {
                    "name": "first",
                    "version": "0.1.0",
                    "entry": "main.yl",
                    "yubalang": "1.2",
                },
            )
            self.assertIn("second", first_entry["dependencies"])
            self.assertEqual(
                first_entry["dependencies"]["second"]["dependencies"], {}
            )
            self.assertTrue((first / "yuba.lock.json").is_file())
            self.assertTrue((second / "yuba.lock.json").is_file())
            check(project)

    def test_accepts_yubalang_1_2_and_rejects_unsupported_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            project = initialize_project(Path(directory) / "project")
            manifest_path = project / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            manifest["yubalang"] = "1.2"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            install(project)

            manifest["yubalang"] = "1.4"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(PackageError, "supports 1.2 and 1.3"):
                install(project)

    def test_upgrades_format_1_lockfile_without_changing_dependency_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = initialize_project(root / "project")
            dependency = root / "library"
            write_package(dependency, "library")
            manifest_path = project / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dependencies"] = {"library": {"path": "../library"}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            old_lock = {
                "lock_version": 1,
                "dependencies": {
                    "library": {
                        "source": {"path": "../library"},
                        "resolved": {"path": "../library"},
                    }
                },
            }
            (project / "yuba.lock.json").write_text(
                json.dumps(old_lock), encoding="utf-8"
            )

            lock = install(project)

            self.assertEqual(lock["lock_version"], 2)
            self.assertEqual(
                lock["dependencies"]["library"]["source"], {"path": "../library"}
            )
            check(project)

    def test_rejects_dependency_cycles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = initialize_project(root / "project")
            library = root / "library"
            write_package(library, "library")

            project_manifest_path = project / "yuba.json"
            project_manifest = json.loads(
                project_manifest_path.read_text(encoding="utf-8")
            )
            project_manifest["dependencies"] = {"library": {"path": "../library"}}
            project_manifest_path.write_text(
                json.dumps(project_manifest), encoding="utf-8"
            )
            library_manifest_path = library / "yuba.json"
            library_manifest = json.loads(
                library_manifest_path.read_text(encoding="utf-8")
            )
            library_manifest["dependencies"] = {"project": {"path": "../project"}}
            library_manifest_path.write_text(
                json.dumps(library_manifest), encoding="utf-8"
            )

            with self.assertRaisesRegex(
                PackageError, "Dependency cycle detected: .* -> .* -> .*"
            ):
                install(project)

    def test_path_dependency_install_check_and_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = initialize_project(root / "project")
            dependency = root / "library"
            write_package(dependency, "library")
            manifest_path = project / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dependencies"] = {"library": {"path": "../library"}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            lock = install(project)
            self.assertEqual(
                lock["dependencies"]["library"]["resolved"]["path"], "../library"
            )
            check(project)

            manifest["dependencies"]["other"] = {"path": "../library"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(PackageError, "do not match the lockfile"):
                check(project)

    def test_rejects_dependency_entry_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            write_package(package, "package")
            manifest_path = package / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["entry"] = "../outside.yl"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            project = initialize_project(root / "project")
            project_manifest_path = project / "yuba.json"
            project_manifest = json.loads(
                project_manifest_path.read_text(encoding="utf-8")
            )
            project_manifest["dependencies"] = {
                "package": {"path": "../package"}
            }
            project_manifest_path.write_text(
                json.dumps(project_manifest), encoding="utf-8"
            )
            with self.assertRaisesRegex(PackageError, "must stay inside"):
                install(project)

    def test_git_dependency_is_locked_to_commit_and_stays_stable(self):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            write_package(source, "library")
            remote = root / "library.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
            for key, value in (
                ("user.name", "YubaPKG Tests"),
                ("user.email", "tests@example.invalid"),
            ):
                subprocess.run(
                    ["git", "-C", str(source), "config", key, value], check=True
                )
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(source), "commit", "-m", "Initial"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "remote", "add", "origin", str(remote)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "push", "origin", "HEAD"],
                check=True,
                capture_output=True,
            )
            project = initialize_project(root / "project")
            manifest_path = project / "yuba.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dependencies"] = {"library": {"git": str(remote)}}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            first = install(project)
            first_revision = first["dependencies"]["library"]["resolved"]["rev"]
            self.assertRegex(first_revision, r"^[0-9a-f]{40,64}$")
            self.assertEqual(first["lock_version"], 2)
            check(project)
            self.assertEqual(
                install(project)["dependencies"]["library"]["resolved"]["rev"],
                first_revision,
            )

if __name__ == "__main__":
    unittest.main()
