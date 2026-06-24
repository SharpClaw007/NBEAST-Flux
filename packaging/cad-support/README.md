# Distributing CAD geometry support (Phase 6, Stage F)

NBEAST v1 ships the lean `nodagmc` app. **CAD geometry is an optional Apple-Silicon
add-on** — the app already gates it on `nbeast.core.cad.is_available()` (File ▸ Import
CAD geometry appears only when the envs below exist).

## Why two envs (not one bundled installer)

The CAD feature needs two conda envs that **can't be merged**: `cad_to_dagmc` pins
`numpy<=1.26.4`, while the dagmc-OpenMC we built is `numpy 2`. NBEAST runs in its own env
and drives both as subprocesses. So distribution is a **channel + setup script**, not a
single constructor bundle.

## What's custom vs. from conda-forge

Everything comes from conda-forge **except** the two packages we built (no arm64 upstream):

| Package | Source |
|---|---|
| `dagmc 3.2.4` (Stage B) | built here → channel |
| `openmc 0.15.3` `dagmc` variant (Stage C) | built here → channel |
| `moab` library, `cad_to_dagmc`, `cadquery`, `ocp`, `gmsh`, … | conda-forge arm64 |

## Workflow

### Users — one command

The channel is **published** as a release asset, so on Apple Silicon (with Miniforge):

```sh
./setup_cad_support.sh        # fetches the published channel + creates both envs
```

Published channel:
<https://github.com/SharpClaw007/NBEAST-Flux/releases/tag/cad-channel-osx-arm64-1>
(NBEAST can also run this for you — see *In-app setup* below.) Env names/locations can be
overridden with `NBEAST_CAD_PYTHON` / `NBEAST_DAGMC_PYTHON`.

### Maintainers — rebuild + republish the channel

```sh
# 1. build the custom artifacts (once)
../dagmc-arm64/build_dagmc_arm64.sh
../openmc-arm64/build_openmc_dagmc_arm64.sh /tmp/dagmc-arm64-build

# 2. gather them into a channel
./assemble_channel.sh                     # -> ./channel/osx-arm64/*.conda  (gitignored)

# 3. publish (tar + a non-v* release tag so it doesn't trigger the installer build)
tar -czf nbeast-cad-channel-osx-arm64.tar.gz -C . channel
gh release create cad-channel-osx-arm64-2 nbeast-cad-channel-osx-arm64.tar.gz
```

`setup_cad_support.sh` also accepts a tarball URL, a local tarball, or a local channel dir.

**Validated:** `assemble_channel.sh` produces an indexed channel, a dry-run solve installs
`openmc(dagmc)` + `dagmc` from it (`moab` from conda-forge), and the channel is published.

### In-app setup

When the CAD envs are absent, NBEAST shows **File ▸ Set up CAD geometry support…**, which
runs `setup_cad_support.sh` (fetch channel + create envs) off the UI thread and enables the
feature when done.

## Remaining (execution / future)

- **Publish** the channel artifacts (a tagged release asset or a hosted conda channel) —
  the binaries aren't committed to the repo.
- Optional: an **in-app "Set up CAD support"** action that runs `setup_cad_support.sh`,
  and macOS **notarization** of the CAD envs.
