#!/bin/sh
# Container side of build-appimage.sh. Runs inside python:3.12-slim-bullseye
# (Debian 11, glibc 2.31) so the result also runs on older distros.
#
# Expects /src = the app directory (read-only), /out = where the AppImage goes.
set -e

FFMPEG_VERSION=7.1.1
FFMPEG_SHA256=733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1
APPIMAGETOOL_VERSION=1.9.1
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0

fetch() {  # url sha256 dest
    curl -fsSL "$1" -o "$3"
    echo "$2  $3" | sha256sum -c - >/dev/null
}

# Debian 11 is end-of-life, so its packages live on archive.debian.org now.
# Check-Valid-Until is off because the archived Release files are expired by
# design; the package hashes in them are still what apt verifies against.
printf 'deb http://archive.debian.org/debian bullseye main\n' > /etc/apt/sources.list
printf 'deb http://archive.debian.org/debian-security bullseye-security main\n' >> /etc/apt/sources.list
apt-get -o Acquire::Check-Valid-Until=false update -qq
apt-get install -y -qq build-essential nasm pkg-config libmp3lame-dev \
    binutils curl xz-utils file desktop-file-utils >/dev/null

# --- ffmpeg -----------------------------------------------------------------
# audioprep.to_cbr() is the only thing that shells out to ffmpeg, and it only
# ever re-encodes an MP3 to a constant bitrate. Building just that pipeline
# gives a ~3MB static binary instead of the ~150MB a general-purpose build
# costs, and keeps the AppImage self-contained: no system ffmpeg needed.
# LGPL only (libmp3lame is LGPL, and --enable-gpl is deliberately absent).
mkdir -p /build/ffmpeg
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256" /tmp/ffmpeg.tar.xz
tar xf /tmp/ffmpeg.tar.xz -C /build/ffmpeg --strip-components=1
cd /build/ffmpeg
./configure \
    --disable-everything --disable-doc --disable-debug --disable-network \
    --disable-autodetect --disable-shared --enable-static --enable-small \
    --disable-ffplay --disable-ffprobe \
    --enable-libmp3lame \
    --enable-demuxer=mp3 --enable-muxer=mp3 \
    --enable-decoder=mp3,mp3float --enable-encoder=libmp3lame \
    --enable-parser=mpegaudio --enable-protocol=file --enable-bsf=null \
    --enable-filter=aresample,aformat,anull,abuffer,abuffersink \
    --pkg-config-flags=--static --extra-ldflags=-static >/dev/null
make -j"$(nproc)" ffmpeg >/dev/null
strip ffmpeg

# --- the app binary ---------------------------------------------------------
pip install -q assemblyai==1.6.1 python-docx==1.2.0 python-dotenv==1.2.4 pyinstaller
cp -r /src /build/app
cd /build/app
pyinstaller --onefile --clean --noconfirm --name transcritor --paths /build/app \
    --add-data transcritor/static:transcritor/static \
    --add-data transcritor/assets:transcritor/assets \
    --collect-data docx \
    packaging/run_transcritor.py >/dev/null

# --- AppDir -----------------------------------------------------------------
APPDIR=/build/AppDir
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
         "$APPDIR/usr/share/doc/ffmpeg"

cp /build/app/dist/transcritor "$APPDIR/usr/bin/transcritor"
cp /build/ffmpeg/ffmpeg "$APPDIR/usr/bin/ffmpeg"

# AppRun puts the bundled ffmpeg on PATH before anything else, so
# shutil.which("ffmpeg") finds it whether or not the host has one installed.
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE=$(dirname "$(readlink -f "$0")")
export PATH="$HERE/usr/bin:$PATH"
exec "$HERE/usr/bin/transcritor" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# The bundled .desktop entry needs a plain Exec; the one the app installs into
# ~/.local/share/applications on first run is written from the same template
# by selfinstall.py, with @BIN@ pointing at the copied AppImage.
sed 's|@BIN@|transcritor|' /src/transcritor/assets/transcritor.desktop \
    > "$APPDIR/transcritor.desktop"
cp "$APPDIR/transcritor.desktop" "$APPDIR/usr/share/applications/transcritor.desktop"
desktop-file-validate "$APPDIR/transcritor.desktop"

cp /src/transcritor/assets/transcritor.svg "$APPDIR/transcritor.svg"
cp "$APPDIR/transcritor.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/transcritor.svg"
cp "$APPDIR/transcritor.svg" "$APPDIR/.DirIcon"

cp /build/ffmpeg/COPYING.LGPLv2.1 "$APPDIR/usr/share/doc/ffmpeg/COPYING.LGPLv2.1"
cat > "$APPDIR/usr/share/doc/ffmpeg/README.source" <<EOF
The bundled usr/bin/ffmpeg is FFmpeg $FFMPEG_VERSION, built from the unmodified
upstream release at
  https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz
  sha256 $FFMPEG_SHA256
configured without --enable-gpl, so it is covered by the LGPL v2.1 text next to
this file. The exact configure flags are in app/packaging/appimage.sh in the
Transcritor source tree.
EOF

# --- package ----------------------------------------------------------------
fetch "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage" \
    "$APPIMAGETOOL_SHA256" /tmp/appimagetool
chmod +x /tmp/appimagetool
# No FUSE inside the container, so let appimagetool unpack itself instead.
cd /build
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 /tmp/appimagetool --no-appstream \
    "$APPDIR" /out/Transcritor-x86_64.AppImage

chown "$HOST_UID:$HOST_GID" /out/Transcritor-x86_64.AppImage
