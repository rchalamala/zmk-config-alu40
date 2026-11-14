"""Deliberately resolve upstream imports into the manifest used by builds."""

import argparse
import copy
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import yaml


SOURCE = Path(__file__).resolve().parents[1]


def update_projects(workspace):
    command = ["west", "update", "--narrow", "--fetch-opt=--no-tags", "--fetch-opt=--filter=tree:0"]
    for attempt in range(3):
        try:
            subprocess.run(command, cwd=workspace, check=True)
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            print("West update failed; retrying with completed checkouts retained", file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)


def output(command, workspace):
    return subprocess.check_output(command, cwd=workspace, text=True)


def freeze_manifest(resolved, workspace):
    frozen = copy.deepcopy(resolved)
    manifest = frozen["manifest"]
    if "import" in manifest.get("self", {}):
        raise ValueError("resolved manifest still imports another manifest")
    for project in manifest["projects"]:
        if "import" in project:
            raise ValueError(f"{project['name']} still imports another manifest")
        if not re.fullmatch(r"[0-9a-f]{40}", project["revision"]):
            path = workspace / project.get("path", project["name"])
            project["revision"] = output(
                ["git", "-C", str(path), "rev-parse", "manifest-rev^{commit}"], workspace
            ).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", project["revision"]):
            raise ValueError(f"{project['name']} did not resolve to an immutable commit")
    return frozen


def refresh(source):
    with tempfile.TemporaryDirectory(prefix="west-refresh-") as directory:
        workspace = Path(directory)
        config = workspace / "config"
        config.mkdir()
        shutil.copy2(source / "config/west-input.yml", config / "west.yml")
        subprocess.run(["west", "init", "-l", "config"], cwd=workspace, check=True)
        update_projects(workspace)
        active_command = ["west", "manifest", "--freeze", "--active-only"]
        before = yaml.safe_load(output(active_command, workspace))
        resolved = yaml.safe_load(output(["west", "manifest", "--resolve"], workspace))
        frozen = freeze_manifest(resolved, workspace)
        contents = yaml.safe_dump(frozen, sort_keys=False)
        (config / "west.yml").write_text(contents)
        subprocess.run(["west", "manifest", "--validate"], cwd=workspace, check=True)
        after = yaml.safe_load(output(active_command, workspace))
        if before != after:
            raise ValueError("freezing changed the active dependency graph")
        destination = source / "config/west.yml"
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as staged:
            staged.write(contents)
            staged_path = Path(staged.name)
        try:
            staged_path.chmod(destination.stat().st_mode & 0o777)
            staged_path.replace(destination)
        finally:
            staged_path.unlink(missing_ok=True)
        print(f"Updated {destination}; review the diff and rebuild every firmware target.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-workspace", type=Path)
    options = parser.parse_args()
    if options.update_workspace is not None:
        update_projects(options.update_workspace.resolve())
    else:
        refresh(SOURCE)
