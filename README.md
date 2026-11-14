# ALU40 ZMK Repository

## Instructions

1. [Fork this repository](https://docs.github.com/en/get-started/quickstart/fork-a-repo#forking-a-repository).
2. [Click the **Actions** tab and make sure the workflow is enabled](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow#enabling-a-workflow).
3. Review the pinned projects in [`config/west.yml`](config/west.yml). The build retains the pinned `alu40-module` and also supplies this checkout as a Zephyr module, matching the previous reusable workflow.

**If you already have a ZMK config repository, [you can add this one as a module instead of forking](https://zmk.dev/docs/features/modules#building-with-modules).**

## Build firmware

Pushes, pull requests and manual workflow dispatches build every entry in
[`build.yaml`](build.yaml): normal ALU40, Studio over USB, and settings reset.
The workflow publishes the `firmware` artifact after every target succeeds. It
contains the existing UF2 names, `SHA256SUMS`, and diagnostics with each target's
Kconfig, devicetree and compiler log. Failed builds publish diagnostics without
publishing a partial firmware bundle.

Docker runs the same build locally:

```sh
docker build --tag alu40-firmware .
mkdir -p firmware
docker run --rm --network none \
  --env SOURCE_REVISION="$(git rev-parse HEAD)" \
  --env SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)" \
  --volume "$PWD/firmware:/output" \
  alu40-firmware
```

[`Dockerfile`](Dockerfile) owns the compiler image digest. The West manifest is
the actual flattened, frozen dependency graph, with no imported or named
revisions resolved during builds. The source keymap, module revision and ZMK
revision are unchanged by this build migration. The small owned workflow
replaces the moving upstream generic workflow; targets share one dependency
setup and run serially, while all targets are attempted if a compilation fails.
The Zephyr build-version label is fixed to the first 12 characters of its locked
commit, currently `dacab4875df7`, instead of changing when upstream adds tags.
Dependency fetches also exclude tags, keeping ZMK's generated application-version
metadata tied to its source commit.

The build report records the compiler image, architecture, source-file hashes, the resolved West manifest,
`SOURCE_DATE_EPOCH`, and the optional `SOURCE_REVISION` label. The label alone
does not prove that a local checkout was clean. Repeat-build comparisons must
use identical source bytes and timestamp inputs; ordinary builds with different
inputs are not promised to be byte-identical. Updating build inputs requires a
reviewed new image digest or frozen manifest and rebuilding every matrix entry.

The image build needs network access to prepare dependencies. Compilation runs
without network access and copies configuration into its disposable runtime.
Source and dependencies share one filesystem layer to avoid repeated toolchain
copies with Docker's VFS driver; changing source reruns dependency preparation.
It does not rewrite the host checkout or flash a device. A failed compilation
does not publish new firmware files; existing files in a reused output directory
remain, so use a fresh directory when collecting a new release.

## Update build inputs

The repository maintainer owns deliberate updates; there is no dependency update
bot in this repository. Edit the intended ZMK or module commit in
[`config/west-input.yml`](config/west-input.yml), then regenerate the complete
runtime lock with the current pinned compiler image:

```sh
compiler_image=$(sed -n 's/^FROM //p' Dockerfile)
docker run --rm \
  --user "$(id -u):$(id -g)" --env HOME=/tmp \
  --volume "$PWD:/config" \
  --entrypoint python3 "$compiler_image" /config/scripts/update_west.py
git diff -- config/west-input.yml config/west.yml
```

This intentional network operation resolves upstream imports in a temporary
workspace, preserves inactive projects and group filters, validates the flattened
graph, and replaces the lock only after the active graph is unchanged by
flattening. Builds read `config/west.yml` only. A refresh failure leaves the old
lock intact. Review every changed project before rebuilding all three targets.
For a compiler update, replace the digest in `Dockerfile`, then rebuild all
targets and repeat the same-input comparison. Retain the previous commit and
firmware bundle for rollback; a software build does not verify physical hardware.

## Notes

[`config/alu40.keymap`](config/alu40.keymap) contains [several reserved layers labeled `extra1-4`](https://zmk.dev/docs/features/studio#including-extra-layers) for use with [ZMK Studio](https://zmk.studio). If you intend to use [Keymap Editor](https://nickcoutsos.github.io/keymap-editor), these will need to be removed.
