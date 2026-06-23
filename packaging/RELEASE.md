# Releasing NBEAST

## 1. Bump the version (one line)

Edit `src/nbeast/__init__.py`:

```python
__version__ = "0.0.2"
```

Everything derives from this: the wheel filename, the installer version/name, and
`construct.yaml` (generated from `construct.yaml.in` by the build script). Reinstall
(`pip install -e .`) so the dev env reports the new version.

## 2. Build the installers

```sh
conda install -n base -c conda-forge constructor
packaging/build_installer.sh osx-arm64    # native Apple Silicon
packaging/build_installer.sh linux-64     # Linux (cross-builds from any host)
```

`osx-arm64` needs the native OpenMC channel; the script builds it via
`openmc-arm64/build_openmc_arm64.sh` (or set `NBEAST_ARM64_CHANNEL` to reuse one).
Installers land in `packaging/dist/NBEAST-<version>-*.sh`.

**Smoke test** each: `bash <installer> -b -p /tmp/t && /tmp/t/bin/python -c "import nbeast, openmc"`.

## 3. (Account-gated) macOS signing & notarization

So users don't hit Gatekeeper, an `.sh` is fine for `-b -p` installs but a signed/notarized
`.pkg` is wanted for a polished download. This needs an **Apple Developer ID** ($99/yr):

```sh
# sketch — to wire in once a Developer ID is available:
#   productsign / codesign the payload, then:
#   xcrun notarytool submit <pkg> --apple-id … --team-id … --wait
#   xcrun stapler staple <pkg>
```

Until then, document the right-click ▸ Open workaround for unsigned builds.

## 4. (Account-gated) Publish

Needs a **GitHub repository**. Then:

- Tag the release (`git tag v0.0.2 && git push --tags`).
- A release CI workflow can build the three installers on GitHub runners (free arm64
  macOS + Linux runners) and attach them to the GitHub Release. Installers are large
  (~750 MB) — within the 2 GB per-asset limit, but consider hosting the data bundle
  separately (e.g. Zenodo) if the installer grows.

## CI

`.github/workflows/ci.yml` runs the test suite (linux-64, native OpenMC) on every push.
A separate release workflow (TODO, once the repo exists) builds + uploads installers on tags.
