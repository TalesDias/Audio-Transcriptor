"""On-disk storage: one folder per transcription with meta.json, transcript.json and the audio."""

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from .config import DATA_DIR

ITEMS_DIR = DATA_DIR / "transcripts"
ID_RE = re.compile(r"^[0-9A-Za-z-]+$")

_lock = threading.Lock()


def valid_id(item_id: str) -> bool:
    return bool(ID_RE.match(item_id)) and (ITEMS_DIR / item_id / "meta.json").exists()


def item_dir(item_id: str) -> Path:
    return ITEMS_DIR / item_id


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _write_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def create(item_id: str, meta: dict):
    item_dir(item_id).mkdir(parents=True, exist_ok=True)
    _write_json(item_dir(item_id) / "meta.json", meta)


def read_meta(item_id: str) -> dict:
    return json.loads((item_dir(item_id) / "meta.json").read_text(encoding="utf-8"))


def update_meta(item_id: str, **changes) -> dict:
    with _lock:
        meta = read_meta(item_id)
        meta.update(changes)
        _write_json(item_dir(item_id) / "meta.json", meta)
        return meta


def list_items() -> list[dict]:
    if not ITEMS_DIR.exists():
        return []
    items = []
    for d in sorted(ITEMS_DIR.iterdir(), reverse=True):
        try:
            items.append({"id": d.name, **read_meta(d.name)})
        except (OSError, ValueError):
            continue
    return items


def read_transcript(item_id: str) -> dict | None:
    path = item_dir(item_id) / "transcript.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_transcript(item_id: str, data: dict):
    _write_json(item_dir(item_id) / "transcript.json", data)


def audio_path(item_id: str) -> Path:
    return item_dir(item_id) / read_meta(item_id)["audio_file"]


def delete(item_id: str):
    shutil.rmtree(item_dir(item_id), ignore_errors=True)
