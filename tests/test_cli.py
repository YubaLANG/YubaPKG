import contextlib
import io
import json
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


if __name__ == "__main__":
    unittest.main()
