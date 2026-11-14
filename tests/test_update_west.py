import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/update_west.py"
SPEC = importlib.util.spec_from_file_location("update_west", SCRIPT)
UPDATER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATER)


class FreezeTests(unittest.TestCase):
    def test_transient_update_failure_is_retried(self):
        with patch.object(UPDATER.subprocess, "run", side_effect=[subprocess.CalledProcessError(1, "west"), None]) as run:
            with patch.object(UPDATER.time, "sleep"):
                UPDATER.update_projects(Path("/workspace"))
        self.assertEqual(run.call_count, 2)

    def test_persistent_update_failure_remains_fatal(self):
        with patch.object(UPDATER.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "west")) as run:
            with patch.object(UPDATER.time, "sleep"):
                with self.assertRaises(subprocess.CalledProcessError):
                    UPDATER.update_projects(Path("/workspace"))
        self.assertEqual(run.call_count, 3)

    def test_full_graph_keeps_inactive_projects_and_group_filters(self):
        manifest = {"manifest": {
            "group-filter": ["-optional"],
            "projects": [
                {"name": "zephyr", "revision": "v3.5.0+zmk-fixes", "path": "zephyr"},
                {"name": "inactive", "revision": "b" * 40, "groups": ["optional"]},
            ],
            "self": {"path": "config"},
        }}
        with patch.object(UPDATER, "output", return_value="a" * 40 + "\n") as lookup:
            frozen = UPDATER.freeze_manifest(manifest, Path("/workspace"))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(frozen["manifest"]["projects"][0]["revision"], "a" * 40)
        self.assertEqual(frozen["manifest"]["projects"][1], manifest["manifest"]["projects"][1])
        self.assertEqual(frozen["manifest"]["group-filter"], ["-optional"])
        self.assertEqual(manifest["manifest"]["projects"][0]["revision"], "v3.5.0+zmk-fixes")

    def test_unresolved_inactive_ref_preserves_existing_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "config").mkdir()
            (source / "config/west-input.yml").write_text("manifest: {}\n")
            lock = source / "config/west.yml"
            lock.write_text("existing lock\n")
            responses = [
                "manifest: {projects: []}",
                "manifest: {projects: [{name: inactive, revision: main}]}",
                subprocess.CalledProcessError(128, "git"),
            ]
            with patch.object(UPDATER.subprocess, "run"), patch.object(UPDATER, "output", side_effect=responses):
                with self.assertRaises(subprocess.CalledProcessError):
                    UPDATER.refresh(source)
            self.assertEqual(lock.read_text(), "existing lock\n")


if __name__ == "__main__":
    unittest.main()
