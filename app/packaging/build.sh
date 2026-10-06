#!/bin/sh
# Builds dist/transcritor-linux-x86_64 inside Debian 11 (glibc 2.31), so the
# binary also runs on older distros (Ubuntu 20.04+, Debian 11+, Mint 20+).
#
# The binary is the whole distribution: on first run it installs itself
# (~/.local/bin, a .desktop entry, an icon) and `transcritor --uninstall`
# removes it again. Nothing else needs to be shipped alongside it.
set -e
APP=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(dirname "$APP")
OUT="$ROOT/dist"
mkdir -p "$OUT"

docker run --rm -v "$APP:/src:ro" -v "$OUT:/out" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  python:3.12-slim-bullseye sh -ec '
    # Debian 11 is end-of-life, so its packages live on archive.debian.org now.
    printf "deb http://archive.debian.org/debian bullseye main\n" > /etc/apt/sources.list
    apt-get -o Acquire::Check-Valid-Until=false update -qq
    apt-get install -y -qq binutils >/dev/null
    pip install -q assemblyai==1.6.1 python-docx==1.2.0 python-dotenv==1.2.4 pyinstaller
    cp -r /src /build && cd /build
    pyinstaller --onefile --clean --noconfirm --name transcritor --paths /build \
      --add-data transcritor/static:transcritor/static \
      --add-data transcritor/assets:transcritor/assets \
      --collect-data docx \
      packaging/run_transcritor.py
    cp dist/transcritor /out/transcritor-linux-x86_64
    chown "$HOST_UID:$HOST_GID" /out/transcritor-linux-x86_64
  '
echo "Built $OUT/transcritor-linux-x86_64"
