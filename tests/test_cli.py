import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pkg.cli import main


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


class PackageCliTests(unittest.TestCase):
    def test_init_and_path_dependency_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            dependency = root / "library"
            write_package(dependency, "library")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["package", "init", str(project)]), 0)
            self.assertIn("Created YubaLANG project", output.getvalue())

            with patch("pathlib.Path.cwd", return_value=project):
                self.assertEqual(main(["package", "add", "library", "--path", "../library"]), 0)
                self.assertEqual(main(["package", "check"]), 0)
                self.assertEqual(main(["package", "list"]), 0)

            manifest = json.loads((project / "yuba.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["dependencies"]["library"], {"path": "../library"}
            )
            self.assertTrue((project / "yuba.lock.json").is_file())

    def test_failed_add_restores_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            main(["init", str(project)])
            original = (project / "yuba.json").read_bytes()
            errors = io.StringIO()
            with patch("pathlib.Path.cwd", return_value=project):
                with contextlib.redirect_stderr(errors):
                    result = main(
                        ["package", "add", "missing", "--path", "../missing"]
                    )
            self.assertEqual(result, 1)
            self.assertIn("does not exist", errors.getvalue())
            self.assertEqual((project / "yuba.json").read_bytes(), original)

    def test_project_registry_config_precedence_and_tree_cache_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            dependency = Path(directory) / "library"
            write_package(dependency, "library")
            main(["init", str(root)])
            with patch.dict(os.environ, {}, clear=True):
                with patch("pathlib.Path.cwd", return_value=root):
                    self.assertEqual(
                        main(
                            [
                                "package",
                                "config",
                                "registry",
                                "https://packages.example.org",
                            ]
                        ),
                        0,
                    )
                    self.assertEqual(
                        main(["package", "add", "library", "--path", "../library"]),
                        0,
                    )
                    tree = io.StringIO()
                    with contextlib.redirect_stdout(tree):
                        self.assertEqual(main(["package", "tree"]), 0)
                    self.assertIn("library ../library [path]", tree.getvalue())
                    (root / ".yuba" / "registry").mkdir(parents=True)
                    (root / ".yuba" / "registry" / "library.json").write_text(
                        "{}", encoding="utf-8"
                    )
                    (root / ".yuba" / "artifacts").mkdir()
                    (root / ".yuba" / "artifacts" / "artifact.tar.gz").write_bytes(b"x")
                    self.assertEqual(
                        main(["package", "cache", "clean", "metadata", "library"]),
                        0,
                    )
                    self.assertFalse(
                        (root / ".yuba" / "registry" / "library.json").exists()
                    )
                    self.assertTrue(
                        (root / ".yuba" / "artifacts" / "artifact.tar.gz").exists()
                    )
                    config = io.StringIO()
                    with contextlib.redirect_stdout(config):
                        self.assertEqual(
                            main(["package", "config", "registry"]), 0
                        )
                    self.assertIn("https://packages.example.org", config.getvalue())

    def test_package_help_includes_sources_and_offline_examples(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_info:
                main(["package", "--help"])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertIn("--registry", output.getvalue())
        self.assertIn("--offline", output.getvalue())
        self.assertIn("Publishing is not supported", output.getvalue())


if __name__ == "__main__":
    unittest.main()
