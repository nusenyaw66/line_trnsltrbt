#!/usr/bin/env python3
"""Benchmark burst-send Live Translate vs STT + Translate + Grok/Cloud TTS.

Usage:
  poetry run python scripts/spike_live_translate_latency.py
  poetry run python scripts/spike_live_translate_latency.py path/to/a.ogg path/to/b.ogg

Without OGG arguments, synthesizes ~3s / ~8s / ~20s English clips via Grok TTS
(or Cloud TTS) and times japanese-mode translation (English → Japanese).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from gemini_live_translate import live_translate_voice_note  # noqa: E402
from gemini_voice import GeminiVoiceError, speak_translation  # noqa: E402

SHORT_TEXT = "Hello, how are you today? I hope you are doing well."
MEDIUM_TEXT = (
    "Good afternoon. I wanted to let you know that our meeting has been moved to "
    "Thursday at three o'clock. Please bring the quarterly report and any questions "
    "about the budget. If you cannot attend, send a short message so we can reschedule."
)
LONG_TEXT = (
    "This is a longer spoken update covering several topics. First, the product launch "
    "is still planned for next month, and the design team will share mockups on Monday. "
    "Second, customer support asked us to improve the onboarding emails because new users "
    "are getting stuck on language settings. Third, we should review the translation quality "
    "for Japanese and Traditional Chinese before we expand to more markets. Finally, please "
    "reply with your availability for a follow-up call so we can decide what to do next."
)

CLIP_SPECS: List[Tuple[str, str]] = [
    ("~3s", SHORT_TEXT),
    ("~8s", MEDIUM_TEXT),
    ("~20s", LONG_TEXT),
]


def _ffprobe_duration(path: Path) -> Optional[float]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def _synthesize_ogg(text: str, dest: Path) -> None:
    if os.getenv("XAI_API_KEY"):
        from grok_voice import grok_tts_ogg

        dest.write_bytes(grok_tts_ogg(text, gender="female", mode="american"))
        return
    from gemini_voice import cloud_tts_ogg

    dest.write_bytes(cloud_tts_ogg(text, gender="female", mode="american"))


def _current_pipeline(ogg: bytes) -> Tuple[str, Dict[str, float]]:
    """Japanese-mode-ish STT (en-US first) + Translate + TTS. Optimistic STT."""
    from gcs_audio import speech_to_text
    from gcs_translate import detect_and_translate

    times: Dict[str, float] = {}
    t0 = time.perf_counter()
    transcribed = speech_to_text(
        ogg,
        "ja-JP",
        alternative_language_codes=["en-US", "zh-TW", "es-ES", "zh-CN"],
        premium_access=True,
    )
    times["stt_s"] = time.perf_counter() - t0
    t1 = time.perf_counter()
    translated = detect_and_translate(
        transcribed,
        enabled=True,
        source_lang=None,
        target_lang="ja",
        mode="japanese",
    )
    times["translate_s"] = time.perf_counter() - t1
    t2 = time.perf_counter()
    speak_translation(translated, gender="female", mode="japanese")
    times["tts_s"] = time.perf_counter() - t2
    times["total_s"] = time.perf_counter() - t0
    return translated, times


def _bench_one(label: str, ogg: bytes, duration_s: Optional[float]) -> None:
    dur = f"{duration_s:.1f}s" if duration_s is not None else "?"
    print(f"\n=== {label} (clip {dur}, {len(ogg)} bytes) ===", flush=True)

    live_metrics: Dict[str, Any] = {}
    live_t0 = time.perf_counter()
    live_err = ""
    live_text = ""
    print("Live Translate: starting...", flush=True)
    try:
        _, live_text = live_translate_voice_note(ogg, mode="japanese", metrics=live_metrics)
    except Exception as exc:  # noqa: BLE001
        live_err = str(exc)
    live_total = time.perf_counter() - live_t0

    if live_err:
        print(f"Live Translate FAILED after {live_total:.2f}s: {live_err}", flush=True)
        if live_metrics:
            print(f"  metrics={live_metrics}", flush=True)
    else:
        print(
            f"Live Translate: connect={live_metrics.get('connect_s', 0):.2f}s "
            f"first_audio={live_metrics.get('first_audio_s', 0):.2f}s "
            f"complete={live_metrics.get('complete_s', live_total):.2f}s "
            f"out_pcm={live_metrics.get('output_pcm_s', 0):.1f}s "
            f"wall={live_total:.2f}s",
            flush=True,
        )
        preview = (live_text or "")[:120].replace("\n", " ")
        print(f"  transcript: {preview}", flush=True)

    current_err = ""
    current_text = ""
    current_times: Dict[str, float] = {}
    print("Current STT + Translate + TTS: starting...", flush=True)
    try:
        current_text, current_times = _current_pipeline(ogg)
    except Exception as exc:  # noqa: BLE001
        current_err = str(exc)
        current_times["total_s"] = 0.0

    if current_err:
        print(f"Current pipeline FAILED: {current_err}", flush=True)
    else:
        print(
            f"Current pipeline: stt={current_times.get('stt_s', 0):.2f}s "
            f"translate={current_times.get('translate_s', 0):.2f}s "
            f"tts={current_times.get('tts_s', 0):.2f}s "
            f"total={current_times.get('total_s', 0):.2f}s",
            flush=True,
        )
        preview = (current_text or "")[:120].replace("\n", " ")
        print(f"  transcript: {preview}", flush=True)

    if not live_err and not current_err:
        delta = live_total - current_times["total_s"]
        winner = "Live Translate" if delta < 0 else "current pipeline"
        print(f"  delta (live - current) = {delta:+.2f}s  winner={winner}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Translate vs STT+TTS latency spike")
    parser.add_argument("ogg_files", nargs="*", type=Path, help="Optional real Telegram OGG files")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run ~3s, ~8s, and ~20s clips (default is the short clip only)",
    )
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set; Live Translate path will fail.", flush=True)
    if not os.getenv("XAI_API_KEY"):
        print("XAI_API_KEY is not set; synthesis/TTS may use Cloud TTS.", flush=True)

    specs = CLIP_SPECS if args.all or args.ogg_files else CLIP_SPECS[:1]
    clips: List[Tuple[str, bytes, Optional[float]]] = []
    tmpdir: Optional[tempfile.TemporaryDirectory[str]] = None
    try:
        if args.ogg_files:
            for path in args.ogg_files:
                data = path.read_bytes()
                clips.append((path.name, data, _ffprobe_duration(path)))
        else:
            tmpdir = tempfile.TemporaryDirectory(prefix="live-translate-spike-")
            tmp = Path(tmpdir.name)
            for label, text in specs:
                dest = tmp / f"{label.replace('~', '').replace('s', '')}s.ogg"
                print(f"Synthesizing {label} clip...", flush=True)
                _synthesize_ogg(text, dest)
                clips.append((label, dest.read_bytes(), _ffprobe_duration(dest)))

        for label, ogg, duration in clips:
            _bench_one(label, ogg, duration)
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
