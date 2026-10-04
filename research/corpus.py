"""Evaluation corpora: manifest creation and audio loading.

A *manifest* is a JSONL file with one utterance per line::

    {"id": "...", "lang": "el", "path": "relative/or/absolute.wav",
     "reference": "...", "duration_s": 9.1, "speaker": "M"}

Manifests are committed to the repository (``research/data/manifests``) so the
exact utterance set behind every reported number is reproducible. Audio is
not committed; ``research/data/fetch_fleurs.py`` re-downloads it.
"""

from __future__ import annotations

import csv
import json
import random
import wave
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"
MANIFEST_DIR = DATA_DIR / "manifests"
FLEURS_DIR = DATA_DIR / "fleurs"
SAMPLE_RATE = 16000

FLEURS_LANGS = {"el": "el_gr", "en": "en_us"}


def _read_riff(path: Path) -> tuple[np.ndarray, int, int]:
    """Minimal RIFF/WAVE reader for PCM16 and IEEE-float32 (FLEURS uses float32)."""
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF/WAVE file")
    pos, fmt, payload = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], int.from_bytes(data[pos + 4 : pos + 8], "little")
        body = data[pos + 8 : pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            payload = body
        pos += 8 + size + (size & 1)
    if fmt is None or payload is None:
        raise ValueError(f"{path}: missing fmt/data chunk")
    tag = int.from_bytes(fmt[0:2], "little")
    channels = int.from_bytes(fmt[2:4], "little")
    sr = int.from_bytes(fmt[4:8], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if tag == 0xFFFE:  # WAVE_FORMAT_EXTENSIBLE: real tag is the subformat GUID's first 2 bytes
        tag = int.from_bytes(fmt[24:26], "little")
    if tag == 1 and bits == 16:
        audio = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
    elif tag == 3 and bits == 32:
        audio = np.frombuffer(payload, dtype="<f4").astype(np.float32)
    else:
        raise ValueError(f"{path}: unsupported WAV encoding (tag={tag}, bits={bits})")
    return audio, sr, channels


def load_wav(path: str | Path) -> np.ndarray:
    """Load a PCM16 or float32 WAV as float32 mono at 16 kHz."""
    audio, sr, channels = _read_riff(Path(path))
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if sr != SAMPLE_RATE:
        # Linear-interpolation resample; adequate for evaluation input that is
        # already band-limited speech. FLEURS is natively 16 kHz.
        n_out = int(round(audio.size * SAMPLE_RATE / sr))
        audio = np.interp(np.linspace(0, audio.size - 1, n_out), np.arange(audio.size), audio).astype(np.float32)
    return audio


def save_wav(path: str | Path, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def read_manifest(path: str | Path) -> list[dict]:
    path = Path(path)
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for item in items:
        p = Path(item["path"])
        if not p.is_absolute():
            item["path"] = str((DATA_DIR / p).resolve())
    return items


def build_fleurs_manifest(lang: str, n: int | None, seed: int = 20261004) -> Path:
    """One recording per distinct sentence, shuffled with a fixed seed.

    FLEURS repeats each sentence for up to three speakers; keeping one per
    sentence avoids over-weighting sentences in corpus-level WER.
    """
    folder = FLEURS_DIR / FLEURS_LANGS[lang]
    rows: dict[str, list[list[str]]] = {}
    with open(folder / "test.tsv", encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(row) >= 7 and (folder / "audio" / row[1]).exists():
                rows.setdefault(row[0], []).append(row)
    rng = random.Random(seed)
    picked = [rng.choice(rows[k]) for k in sorted(rows)]
    rng.shuffle(picked)
    if n is not None:
        picked = picked[:n]
    name = f"fleurs_{lang}_{'all' if n is None else n}.jsonl"
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    out = MANIFEST_DIR / name
    with open(out, "w", encoding="utf-8") as f:
        for row in picked:
            f.write(
                json.dumps(
                    {
                        "id": f"fleurs-{lang}-{row[0]}-{Path(row[1]).stem}",
                        "lang": lang,
                        "path": f"fleurs/{FLEURS_LANGS[lang]}/audio/{row[1]}",
                        "reference": row[2],
                        "duration_s": round(int(row[5]) / SAMPLE_RATE, 3),
                        "speaker": row[6],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build seeded FLEURS manifests")
    ap.add_argument("--n", type=int, default=200, help="utterances per language (0 = all)")
    args = ap.parse_args()
    for lang in FLEURS_LANGS:
        print(build_fleurs_manifest(lang, args.n or None))
