"""Local HTTP server: static pages plus a small JSON API over the store."""

import json
import re
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, export, store, transcribe
from .config import APP_NAME

STATIC_DIR = Path(__file__).parent / "static"
CHUNK = 1 << 20
# Cap how much an open-ended Range request ("bytes=N-") gets in one response.
# Browsers don't reliably cancel the previous in-flight request when the user
# seeks again, so without a cap every seek leaves another transfer of the whole
# rest of the file running in the background, and they pile up competing for
# bandwidth with whichever request is actually driving playback. The browser
# re-requests the continuation as it needs it.
MAX_OPEN_RANGE = 4 << 20

last_ping = time.monotonic()


def sniff_audio_type(path: Path) -> str:
    head = path.open("rb").read(12)
    if head[4:8] == b"ftyp":
        return "audio/mp4"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if head[:4] == b"RIFF":
        return "audio/wav"
    if head[:4] == b"OggS":
        return "audio/ogg"
    if head[:4] == b"fLaC":
        return "audio/flac"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    return "application/octet-stream"


class Handler(BaseHTTPRequestHandler):
    server_version = APP_NAME

    def log_message(self, fmt, *args):
        pass

    # --- helpers -----------------------------------------------------------

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/json", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str):
        self._json({"error": message}, status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def _route(self):
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path, urllib.parse.parse_qs(parsed.query)

    def _item_id(self, path: str) -> str | None:
        m = re.match(r"^/api/transcripts/([^/]+)", path)
        if m and store.valid_id(m.group(1)):
            return m.group(1)
        return None

    # --- routes ------------------------------------------------------------

    def do_GET(self):
        global last_ping
        path, query = self._route()

        if path == "/api/ping":
            last_ping = time.monotonic()
            return self._json({"app": APP_NAME})
        if path in ("/", "/index.html"):
            return self._static("library.html")
        if path == "/settings":
            return self._static("settings.html")
        if re.match(r"^/view/[^/]+$", path):
            return self._static("viewer.html")
        if path == "/api/transcripts":
            return self._json(store.list_items())
        if path == "/api/settings":
            return self._json({
                "has_api_key": bool(config.ASSEMBLYAI_API_KEY),
                "key_saved_at": config.api_key_saved_at(),
            })

        item_id = self._item_id(path)
        if item_id is None:
            return self._error(404, "Não encontrado")
        if path == f"/api/transcripts/{item_id}":
            return self._json({"id": item_id, **store.read_meta(item_id), "transcript": store.read_transcript(item_id)})
        if path == f"/api/transcripts/{item_id}/audio":
            return self._audio(item_id)
        m = re.match(rf"^/api/transcripts/{item_id}/export\.(\w+)$", path)
        if m and m.group(1) in export.FORMATS:
            return self._export(item_id, m.group(1), (query.get("v") or [""])[0])
        self._error(404, "Não encontrado")

    do_HEAD = do_GET

    def do_POST(self):
        path, query = self._route()
        if path == "/api/settings":
            return self._save_api_key()
        if path != "/api/transcripts":
            return self._error(404, "Não encontrado")
        if not config.ASSEMBLYAI_API_KEY:
            return self._error(400, "Configure sua chave da AssemblyAI antes de transcrever.")

        filename = Path(urllib.parse.unquote(self.headers.get("X-Filename") or "audio")).name
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._error(400, "Arquivo vazio")

        title = (query.get("title") or [""])[0].strip() or Path(filename).stem
        speakers = (query.get("speakers") or [""])[0].strip()
        keyterms = [t.strip() for t in (query.get("keyterms") or [""])[0].split(",") if t.strip()]
        language = (query.get("language") or [""])[0].strip()

        item_id = store.new_id()
        audio_file = "audio" + (Path(filename).suffix.lower() or ".bin")
        store.create(item_id, {
            "title": title,
            "filename": filename,
            "audio_file": audio_file,
            "created": datetime.now().isoformat(timespec="seconds"),
            "status": "uploading",
            "speakers_expected": int(speakers) if speakers.isdigit() else None,
            "keyterms": keyterms,
            "language": language,
            "speaker_names": {},
        })
        with (store.item_dir(item_id) / audio_file).open("wb") as out:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
        if remaining > 0:
            store.delete(item_id)
            return self._error(400, "Envio interrompido")

        transcribe.start(item_id)
        self._json({"id": item_id}, 201)

    def do_PUT(self):
        path, _ = self._route()
        item_id = self._item_id(path)
        if item_id is None or path != f"/api/transcripts/{item_id}/edited":
            return self._error(404, "Não encontrado")
        turns = self._read_json().get("turns")
        if not isinstance(turns, list):
            return self._error(400, "Corpo inválido")
        store.update_transcript(item_id, edited_turns=turns)
        self._json({"ok": True})

    def do_PATCH(self):
        path, _ = self._route()
        item_id = self._item_id(path)
        if item_id is None or path != f"/api/transcripts/{item_id}":
            return self._error(404, "Não encontrado")
        body = self._read_json()
        changes = {}
        if isinstance(body.get("title"), str) and body["title"].strip():
            changes["title"] = body["title"].strip()
        if isinstance(body.get("speaker_names"), dict):
            changes["speaker_names"] = {str(k): str(v).strip() for k, v in body["speaker_names"].items() if str(v).strip()}
        if isinstance(body.get("speakers"), list):
            changes["speakers"] = sorted({str(s).strip() for s in body["speakers"] if str(s).strip()})
        self._json({"id": item_id, **store.update_meta(item_id, **changes)})

    def do_DELETE(self):
        path, _ = self._route()
        if path == "/api/settings":
            transcribe.clear_api_key()
            return self._json({"ok": True})
        item_id = self._item_id(path)
        if item_id is None or path != f"/api/transcripts/{item_id}":
            return self._error(404, "Não encontrado")
        store.delete(item_id)
        self._json({"ok": True})

    # --- responses ---------------------------------------------------------

    def _save_api_key(self):
        key = str(self._read_json().get("assemblyai_api_key") or "").strip()
        if not key:
            return self._error(400, "Informe uma chave.")
        error = transcribe.validate_api_key(key)
        if error:
            return self._error(400, error)
        transcribe.set_api_key(key)
        self._json({"ok": True})

    def _static(self, name: str):
        self._send(200, (STATIC_DIR / name).read_bytes(), "text/html; charset=utf-8")

    def _export(self, item_id: str, fmt: str, version: str):
        data = store.read_transcript(item_id)
        if data is None:
            return self._error(409, "Transcrição ainda não está pronta")
        turns = data.get("edited_turns") if version == "edited" and data.get("edited_turns") else data["turns"]
        meta = store.read_meta(item_id)
        render, content_type = export.FORMATS[fmt]
        filename = urllib.parse.quote(f"{meta['title']}.{fmt}")
        self._send(200, render(meta, {"turns": turns}), content_type,
                   {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})

    def _audio(self, item_id: str):
        """Serve the audio with HTTP range support so the player can seek."""
        path = store.audio_path(item_id)
        size = path.stat().st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else min(size - 1, start + MAX_OPEN_RANGE - 1)
            else:
                start = max(size - int(m.group(2)), 0)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", sniff_audio_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if self.command == "HEAD":
            return
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = f.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


def make_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server
