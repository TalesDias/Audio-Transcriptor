"""Re-encode uploaded audio when its container can't be seeked accurately.

A VBR MP3 carries only a 100-entry Xing seek table, so a player maps a
timestamp to a byte offset by interpolating between anchors that sit
duration/100 apart - a fixed budget however long the recording is. At 3.5
minutes that's ~2.2s per anchor and measured seek error reaches 1.25s, enough
that the highlighted word audibly disagrees with the audio; at an hour it
would be 36s per anchor. Constant bitrate makes byte offset a linear function
of time, which brings the error down to a single frame (~25ms).

Only MP3 needs this. WAV is linear already, and MP4/M4A, FLAC, Ogg and WebM
all carry real per-frame indexes.
"""

import shutil
import subprocess
from pathlib import Path

# Under this length the Xing table is dense enough (better than ~0.9s per
# anchor) that the error stays well inside a single word, so re-encoding would
# cost quality for no audible gain.
MIN_DURATION = 90.0
BITRATE = "128k"
SAMPLE_RATES_V1 = (44100, 48000, 32000, 0)
HEADER_SCAN = 1 << 16


def _first_frame_rate(data: bytes) -> int | None:
    """Sample rate from the first MPEG-1 Layer III frame header."""
    i = data.find(b"\xff")
    while 0 <= i < len(data) - 4:
        b1, b2 = data[i + 1], data[i + 2]
        if (b1 & 0xE0) == 0xE0 and (b1 >> 3) & 3 == 3 and (b1 >> 1) & 3 == 1:
            if (b2 >> 4) & 0x0F not in (0, 15) and (b2 >> 2) & 3 != 3:
                return SAMPLE_RATES_V1[(b2 >> 2) & 3]
        i = data.find(b"\xff", i + 1)
    return None


def vbr_duration(path: Path) -> float | None:
    """Duration in seconds if this is a VBR MP3 with a Xing seek table,
    otherwise None (CBR files carry an "Info" tag instead and are fine)."""
    try:
        data = path.open("rb").read(HEADER_SCAN)
    except OSError:
        return None
    x = data.find(b"Xing")
    if x < 0:
        return None
    flags = int.from_bytes(data[x + 4:x + 8], "big")
    if flags & 0x05 != 0x05:  # need both a frame count and a TOC
        return None
    frames = int.from_bytes(data[x + 8:x + 12], "big")
    rate = _first_frame_rate(data)
    if not frames or not rate:
        return None
    return frames * 1152 / rate


def to_cbr(path: Path) -> bool:
    """Re-encode in place at a constant bitrate. False if ffmpeg is missing or
    fails, in which case the original is left untouched."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    tmp = path.with_name(path.name + ".cbr.mp3")
    try:
        subprocess.run(
            [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(path),
             "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", BITRATE, "-abr", "0",
             "-map_metadata", "-1", str(tmp)],
            check=True, timeout=900,
        )
    except (subprocess.SubprocessError, OSError):
        tmp.unlink(missing_ok=True)
        return False
    if not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


def ensure_seekable(path: Path) -> str | None:
    """Normalise the file if its seek accuracy would be poor. Returns a short
    description of what was done, or None if it was left alone."""
    if path.suffix.lower() != ".mp3":
        return None
    duration = vbr_duration(path)
    if duration is None or duration < MIN_DURATION:
        return None
    return f"cbr {BITRATE}" if to_cbr(path) else None
