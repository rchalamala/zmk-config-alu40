import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


BUILDER = Path(__file__).resolve().parents[1] / "scripts/build_firmware.py"


class BuildContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "config").mkdir()
        shutil.copy2(BUILDER, self.source / "scripts/build_firmware.py")
        shutil.copy2(BUILDER.with_name("update_west.py"), self.source / "scripts/update_west.py")
        (self.source / "Dockerfile").write_text("FROM test-image@sha256:" + "b" * 64 + "\n")
        (self.source / "config/west.yml").write_text(
            "manifest:\n  projects:\n    - name: zephyr\n      revision: " + "a" * 40 + "\n"
        )
        (self.source / "build.yaml").write_text(
            "include:\n  - board: broken\n  - board: working\n  - board: reset\n"
        )
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        self.output = self.root / "output"
        binaries = self.root / "bin"
        binaries.mkdir()
        west = binaries / "west"
        west.write_text(
            "#!" + sys.executable + "\n"
            "import os, pathlib, sys\n"
            "with pathlib.Path(os.environ['WEST_CALLS']).open('a') as log:\n"
            "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1] == 'manifest':\n"
            "    print('manifest: {}')\n"
            "if sys.argv[1] == 'build':\n"
            "    board = sys.argv[sys.argv.index('-b') + 1]\n"
            "    if board == 'broken':\n"
            "        print('compiler failed for broken target')\n"
            "        sys.exit(17)\n"
            "    output = pathlib.Path(sys.argv[sys.argv.index('-d') + 1]) / 'zephyr'\n"
            "    output.mkdir(parents=True)\n"
            "    (output / 'zmk.uf2').write_bytes(board.encode())\n"
            "    (output / '.config').write_text(board)\n"
        )
        west.chmod(0o755)
        self.calls = self.root / "calls"
        self.environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"])
        self.environment["WEST_CALLS"] = str(self.calls)

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.source / "scripts/build_firmware.py"), *arguments],
            cwd=self.workspace,
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def test_compile_failure_attempts_other_targets_and_withholds_bundle(self):
        result = self.invoke("--output", str(self.output))
        self.assertNotEqual(result.returncode, 0)
        calls = self.calls.read_text()
        for board in ("broken", "working", "reset"):
            self.assertIn("-b " + board + " ", calls)
        self.assertEqual(list(self.output.glob("*.uf2")), [])
        self.assertFalse((self.output / "SHA256SUMS").exists())
        report = json.loads((self.output / "diagnostics/build-report.json").read_text())
        self.assertEqual(report["targets"]["broken-zmk"]["status"], "failed")
        self.assertEqual(report["targets"]["working-zmk"]["status"], "passed")
        self.assertEqual(report["targets"]["reset-zmk"]["status"], "passed")

    def test_named_dependency_is_rejected_before_network_or_workspace_write(self):
        (self.source / "config/west.yml").write_text(
            "manifest:\n  projects:\n    - name: zmk\n      revision: main\n"
        )
        result = self.invoke("--prepare")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("immutable commit", result.stderr)
        self.assertFalse(self.calls.exists())
        self.assertEqual(list(self.workspace.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
