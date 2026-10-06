#!/bin/sh
# Builds dist/Transcritor-x86_64.AppImage inside Debian 11 (glibc 2.31), so it
# also runs on older distros (Ubuntu 20.04+, Debian 11+, Mint 20+).
#
# The AppImage carries its own ffmpeg, which build.sh's bare binary does not:
# without one, long VBR MP3s are left unnormalised and seeking in them drifts
# by a second or more (see transcritor/audioprep.py).
#
# All the work happens in packaging/appimage.sh, inside the container.
set -e
APP=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(dirname "$APP")
OUT="$ROOT/dist"
mkdir -p "$OUT"

docker run --rm -v "$APP:/src:ro" -v "$OUT:/out" \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  python:3.12-slim-bullseye sh /src/packaging/appimage.sh

echo "Built $OUT/Transcritor-x86_64.AppImage"
