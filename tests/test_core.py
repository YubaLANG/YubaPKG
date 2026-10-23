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
            self.assertTrue((project / "main.yl").is_file())

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
            check(project)
            self.assertEqual(
                install(project)["dependencies"]["library"]["resolved"]["rev"],
                first_revision,
            )

if __name__ == "__main__":
    unittest.main()
