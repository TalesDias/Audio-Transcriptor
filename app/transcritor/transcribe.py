"""Background AssemblyAI jobs. Each job survives an app restart: once submitted,
the AssemblyAI transcript id is stored and polling resumes on next launch."""

import threading

import assemblyai as aai

from . import store
from .config import ASSEMBLYAI_API_KEY, LANGUAGE, SPEECH_MODELS

aai.settings.api_key = ASSEMBLYAI_API_KEY

SENTENCE_END = (".", "?", "!", "…")

_active: set[str] = set()
_active_lock = threading.Lock()


def active_count() -> int:
    with _active_lock:
        return len(_active)


def build_turns(words):
    """Group flat words ({start, end, text, speaker}, seconds) into speaker
    turns, each split into sentences on terminal punctuation."""
    turns = []
    for w in words:
        word = {"start": w["start"], "end": w["end"], "text": w["text"]}
        if not turns or turns[-1]["speaker"] != w["speaker"]:
            turns.append({"speaker": w["speaker"], "start": w["start"], "sentences": []})
        sentences = turns[-1]["sentences"]
        if not sentences or sentences[-1]["words"][-1]["text"].endswith(SENTENCE_END):
            sentences.append({"start": w["start"], "end": w["end"], "words": []})
        sentences[-1]["words"].append(word)
        sentences[-1]["end"] = w["end"]
    return turns


def start(item_id: str):
    with _active_lock:
        if item_id in _active:
            return
        _active.add(item_id)
    threading.Thread(target=_run, args=(item_id,), daemon=True).start()


def resume_pending():
    for item in store.list_items():
        if item.get("status") in ("uploading", "processing"):
            start(item["id"])


def _run(item_id: str):
    try:
        meta = store.read_meta(item_id)
        if meta.get("assemblyai_id"):
            transcript = aai.Transcript.get_by_id(meta["assemblyai_id"])
        else:
            store.update_meta(item_id, status="uploading")
            config = aai.TranscriptionConfig(
                speech_models=SPEECH_MODELS,
                language_code=LANGUAGE,
                punctuate=True,
                # Keep spoken numbers as words ("um jeito", not "1 jeito")
                format_text=False,
                speaker_labels=True,
                speakers_expected=meta.get("speakers_expected") or None,
                keyterms_prompt=meta.get("keyterms") or None,
            )
            transcript = aai.Transcriber(config=config).submit(str(store.audio_path(item_id)))
            store.update_meta(item_id, status="processing", assemblyai_id=transcript.id)

        if transcript.status not in (aai.TranscriptStatus.completed, aai.TranscriptStatus.error):
            transcript = transcript.wait_for_completion()

        if transcript.status == aai.TranscriptStatus.error:
            store.update_meta(item_id, status="error", error=str(transcript.error))
            return

        words = [
            {"start": w.start / 1000, "end": w.end / 1000, "text": w.text, "speaker": w.speaker}
            for w in transcript.words or []
        ]
        turns = build_turns(words)
        store.write_transcript(item_id, {"turns": turns})
        store.update_meta(
            item_id,
            status="done",
            duration=transcript.audio_duration,
            speakers=sorted({t["speaker"] for t in turns}),
        )
    except Exception as e:  # network errors, deleted item, etc.
        try:
            store.update_meta(item_id, status="error", error=str(e))
        except OSError:
            pass
    finally:
        with _active_lock:
            _active.discard(item_id)
