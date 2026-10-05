import os
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "Transcritor"

load_dotenv()

ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY")
if not ASSEMBLYAI_API_KEY:
    raise RuntimeError(
        "ASSEMBLYAI_API_KEY não definida. Crie um arquivo .env na raiz do "
        "projeto (veja .env.example) com ASSEMBLYAI_API_KEY=sua_chave."
    )
SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]

XDG_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
DATA_DIR = XDG_DATA_HOME / "transcritor"

# Stop the server when no browser tab has pinged for this long and nothing is transcribing
IDLE_SHUTDOWN_SECONDS = 120
