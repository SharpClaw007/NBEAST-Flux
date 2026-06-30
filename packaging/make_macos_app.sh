#!/usr/bin/env bash
# Build a minimal double-clickable NBEAST.app bundle (macOS).
#
# This is NOT a standalone/distributable bundle — it's a thin launcher that runs
# NBEAST from your existing conda env, with no Terminal window. Double-click it,
# pin it to the Dock, or find it via Spotlight. Re-run this script if you move the
# repo or recreate the env.
#
#   ./packaging/make_macos_app.sh            # builds ./NBEAST.app
#   ./packaging/make_macos_app.sh /Applications/NBEAST.app
#
# Override the interpreter with NBEAST_PYTHON if your env lives elsewhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${1:-$REPO/NBEAST.app}"
PYTHON_BIN="${NBEAST_PYTHON:-$HOME/miniforge3/envs/nbeast/bin/python}"
ENTRY="$(dirname "$PYTHON_BIN")/nbeast"
XS="$REPO/data/cross_sections.xml"
ICON_SRC="$REPO/renders/godiva_flux_volume.png"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "error: interpreter not found at $PYTHON_BIN (set NBEAST_PYTHON)" >&2
  exit 1
fi

# The command that actually starts the GUI (console script if present, else -m).
if [[ -x "$ENTRY" ]]; then
  EXEC_LINE="exec \"$ENTRY\" \"\$@\""
else
  EXEC_LINE="exec \"$PYTHON_BIN\" -m nbeast.gui.app \"\$@\""
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/MacOS/NBEAST" <<EOF
#!/bin/bash
# Launched by macOS LaunchServices (no inherited shell env — so no MATLAB DYLD).
export OPENMC_CROSS_SECTIONS="$XS"
export FI_PROVIDER="tcp"
$EXEC_LINE
EOF
chmod +x "$APP/Contents/MacOS/NBEAST"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>NBEAST</string>
  <key>CFBundleDisplayName</key><string>NBEAST</string>
  <key>CFBundleIdentifier</key><string>org.nbeast.desktop</string>
  <key>CFBundleVersion</key><string>0.0.1</string>
  <key>CFBundleShortVersionString</key><string>0.0.1</string>
  <key>CFBundleExecutable</key><string>NBEAST</string>
  <key>CFBundleIconFile</key><string>NBEAST</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# Optional icon from a flux render.
if [[ -f "$ICON_SRC" ]] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  ICONSET="$(mktemp -d)/NBEAST.iconset"
  mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z "$((s * 2))" "$((s * 2))" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/NBEAST.icns"
  rm -rf "$(dirname "$ICONSET")"
  echo "icon: built from $(basename "$ICON_SRC")"
else
  echo "icon: skipped (no source image or iconutil/sips) — app uses the generic icon"
fi

echo "built: $APP"
echo
echo "Next: drag $APP to /Applications (and to your Dock), or launch it via Spotlight (⌘-Space → NBEAST)."
echo "First launch may need: right-click → Open (unsigned app)."
