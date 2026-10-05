import json
import os
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "Transcritor"
SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]

load_dotenv()

XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
DATA_DIR = XDG_DATA_HOME / "transcritor"
USER_CONFIG_FILE = DATA_DIR / "config.json"

# Stop the server when no browser tab has pinged for this long and nothing is transcribing
IDLE_SHUTDOWN_SECONDS = 120


def _read_user_config() -> dict:
    try:
        return json.loads(USER_CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_api_key(key: str) -> None:
    """Persists the key for future launches and updates the live value other
    modules already imported."""
    global ASSEMBLYAI_API_KEY
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = _read_user_config()
    cfg["assemblyai_api_key"] = key
    USER_CONFIG_FILE.write_text(json.dumps(cfg))
    ASSEMBLYAI_API_KEY = key


# An env var (e.g. from .env, for development) always wins over a key saved
# through the app's own settings screen.
ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY") or _read_user_config().get("assemblyai_api_key") or None
