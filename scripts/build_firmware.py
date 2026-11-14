import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys

import yaml

from update_west import update_projects


SOURCE = Path(__file__).resolve().parents[1]
WORKSPACE = Path.cwd()


def run(command, **kwargs):
    print("+ " + shlex.join(str(arg) for arg in command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def verify_manifest():
    manifest = yaml.safe_load((SOURCE / "config/west.yml").read_text())["manifest"]
    if "import" in manifest.get("self", {}):
        raise ValueError("the frozen manifest must not import another manifest")
    for project in manifest["projects"]:
        if "import" in project or not re.fullmatch(r"[0-9a-f]{40}", project["revision"]):
            raise ValueError(f"{project['name']} must use an immutable commit without imports")
    return manifest


def prepare():
    verify_manifest()
    (WORKSPACE / "config").mkdir()
    shutil.copy2(SOURCE / "config/west.yml", WORKSPACE / "config/west.yml")
    run(["west", "init", "-l", "config"])
    update_projects(WORKSPACE)
    run(["west", "zephyr-export"])


def targets():
    matrix = yaml.safe_load((SOURCE / "build.yaml").read_text())["include"]
    if not matrix:
        raise ValueError("build.yaml must contain at least one target")
    names = set()
    for target in matrix:
        shield = target.get("shield", "")
        name = target.get("artifact-name", f"{shield + '-' if shield else ''}{target['board']}-zmk")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."} or name in names:
            raise ValueError(f"artifact name must be safe and unique: {name}")
        names.add(name)
        yield name, target


def build(output):
    manifest = verify_manifest()
    zephyr_version = next(project["revision"][:12] for project in manifest["projects"] if project["name"] == "zephyr")
    selected_targets = list(targets())
    diagnostics = output / "diagnostics"
    diagnostics.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE / "config", WORKSPACE / "config", dirs_exist_ok=True)
    shutil.copyfile(SOURCE / "config/west.yml", diagnostics / "west-manifest.yml")
    with (diagnostics / "west-active-manifest.yml").open("w") as destination:
        run(["west", "manifest", "--freeze", "--active-only"], stdout=destination)
    sources = {
        str(path.relative_to(SOURCE)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(SOURCE.rglob("*"))
        if path.is_file()
    }
    report = {
        "compiler_image": (SOURCE / "Dockerfile").read_text().splitlines()[0].removeprefix("FROM "),
        "zephyr_build_version": zephyr_version,
        "architecture": platform.machine(),
        "source_revision_label": os.environ.get("SOURCE_REVISION"),
        "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH"),
        "source_files_sha256": sources,
        "targets": {},
    }
    failures = []
    products = []
    for name, target in selected_targets:
        build_directory = WORKSPACE / "build" / name
        target_diagnostics = diagnostics / name
        target_diagnostics.mkdir(exist_ok=True)
        command = ["west", "build", "-s", "zmk/app", "-d", str(build_directory), "-b", target["board"]]
        if target.get("snippet"):
            command.extend(["-S", target["snippet"]])
        command.extend(["--", f"-DZMK_CONFIG={WORKSPACE / 'config'}", f"-DZMK_EXTRA_MODULES={SOURCE}", f"-DBUILD_VERSION={zephyr_version}"])
        if target.get("shield"):
            command.append(f"-DSHIELD={target['shield']}")
        command.extend(shlex.split(target.get("cmake-args", "")))
        try:
            with (target_diagnostics / "build.log").open("w") as log:
                run(command, stdout=log, stderr=subprocess.STDOUT)
            firmware = build_directory / "zephyr/zmk.uf2"
            checksum = hashlib.sha256(firmware.read_bytes()).hexdigest()
            products.append((firmware, output / f"{name}.uf2"))
            report["targets"][name] = {"status": "passed", "sha256": checksum}
        except (subprocess.CalledProcessError, OSError) as error:
            failures.append(name)
            report["targets"][name] = {"status": "failed", "error": str(error)}
            print(f"{name} failed; see diagnostics/{name}/build.log", file=sys.stderr)
        finally:
            for filename in (".config", "zephyr.dts"):
                source = build_directory / "zephyr" / filename
                if source.exists():
                    shutil.copy2(source, target_diagnostics / filename)
    (diagnostics / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise RuntimeError("firmware build failed: " + ", ".join(failures))
    for source, destination in products:
        shutil.copy2(source, destination)
    (output / "SHA256SUMS").write_text("".join(
        f"{result['sha256']}  {name}.uf2\n" for name, result in report["targets"].items()
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("/output"))
    options = parser.parse_args()
    if options.prepare:
        prepare()
    else:
        build(options.output.resolve())


if __name__ == "__main__":
    main()
