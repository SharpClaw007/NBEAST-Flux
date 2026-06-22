#!/usr/bin/env bash
# NBEAST launcher.
#
# Starts the desktop GUI and, when the window closes (or this script is
# interrupted), reaps the app's entire process group so no OpenMC worker
# subprocess is left running.
set -u

NBEAST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${NBEAST_PYTHON:-$HOME/miniforge3/envs/nbeast/bin/python}"

export OPENMC_CROSS_SECTIONS="${OPENMC_CROSS_SECTIONS:-$NBEAST_DIR/data/cross_sections.xml}"
export FI_PROVIDER="${FI_PROVIDER:-tcp}"

# Job control so the backgrounded app becomes its own process-group leader
# (PGID == its PID); that lets us signal the whole group at once.
set -m
"$PYTHON" -m nbeast.gui.app &
APP_PGID=$!

cleanup() {
  # Graceful first, then force — covers the GUI and any lingering workers.
  kill -TERM -"$APP_PGID" 2>/dev/null || true
  sleep 1
  kill -KILL -"$APP_PGID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$APP_PGID"
