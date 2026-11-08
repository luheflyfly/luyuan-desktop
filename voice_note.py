"""路远 P1: one-shot voice note. Record -> transcribe -> save JSON."""
import datetime
import json
import os
import sys
import uuid

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from recorder import record_wav
from stt import transcribe


def load_config():
    with open(os.path.join(BASE, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def save_note(text):
    cfg = load_config()
    notes_dir = os.path.join(BASE, cfg.get("notes_dir", "data/notes"))
    os.makedirs(notes_dir, exist_ok=True)
    note = {
        "id": str(uuid.uuid4()),
        "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "text": text,
        "source": "voice",
        "tags": [],
    }
    fname = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + note["id"][:8] + ".json"
    path = os.path.join(notes_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(note, f, ensure_ascii=False, indent=2)
    return path


def main():
    cfg = load_config()
    secs = float(cfg.get("record_seconds", 6))
    wav = os.path.join(BASE, "temp_rec.wav")

    print("=" * 46)
    print(" 路远 v1-P1  语音记事")
    print("=" * 46)
    try:
        record_wav(wav, duration=secs, samplerate=int(cfg.get("samplerate", 16000)))
    except Exception as e:
        print(f"[ERROR] microphone failed: {e}")
        input("Press Enter to exit...")
        return

    print("  Transcribing (first run downloads the model, please wait)...")
    try:
        text = transcribe(wav)
    except Exception as e:
        print(f"[ERROR] transcription failed: {e}")
        input("Press Enter to exit...")
        return

    print("-" * 46)
    print(" YOU SAID:", text or "(no speech detected)")
    if text.strip():
        print(" SAVED:", save_note(text))
    print("-" * 46)
    try:
        os.remove(wav)
    except OSError:
        pass
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
