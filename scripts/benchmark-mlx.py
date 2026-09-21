"""Repeatable, synthetic Japanese ASR validation; contains no meeting recordings."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import statistics
import sys
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "mlx-validation"
TEXT = "本日の会議を始めます。新しいアプリの公開日は来月十五日です。田中さんは画面の確認を、佐藤さんは資料の作成を担当します。次回の会議は金曜日の午後三時からです。"


def prepare():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    speech = OUTPUT / "japanese.wav"
    if not speech.exists():
        subprocess.run(["say", "-v", "Kyoko", "-r", "180", "-o", str(OUTPUT / "japanese.aiff"), TEXT], check=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(OUTPUT / "japanese.aiff"), "-ar", "16000", "-ac", "1", "-sample_fmt", "s16", str(speech)], check=True)
    with wave.open(str(speech), "rb") as stream:
        frames = stream.readframes(stream.getnframes())
    if not frames:
        raise RuntimeError("Synthetic speech is empty. Run macOS say outside the sandbox, convert to PCM16, then retry.")
    for name, data in [("silence.wav", bytes(16000 * 2 * 10)), ("long-silence.wav", bytes(16000 * 2 * 35) + frames + bytes(16000 * 2 * 35))]:
        with wave.open(str(OUTPUT / name), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(data)
    (OUTPUT / "reference.txt").write_text(TEXT + "\n", encoding="utf-8")
    return speech


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["prepare", "cpu", "mlx"], default="prepare")
    parser.add_argument("--model", default="base")
    parser.add_argument("--cases", nargs="+", default=["japanese", "silence", "long-silence"])
    parser.add_argument("--repeat", type=int, default=4, help="First run plus three warm runs")
    parser.add_argument("--download-only", action="store_true", help="Resolve/download the MLX model without using GPU")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.download_only and args.engine != "mlx":
        parser.error("--download-only requires --engine mlx")
    prepare()
    if args.engine == "prepare":
        print(OUTPUT)
        return
    os.environ.setdefault("HF_HOME", str(Path.home() / "Library/Application Support/Local Meeting Notes/models"))
    result = {"engine": args.engine, "model": args.model, "reference": TEXT, "cases": {}}
    if args.engine == "cpu":
        from faster_whisper import WhisperModel
        start = time.perf_counter()
        model = WhisperModel(args.model, device="cpu", compute_type="int8", local_files_only=True)
        result["load_seconds"] = time.perf_counter() - start
        result["download_seconds"] = 0
        result["download_note"] = "Existing cached model; local_files_only=True"

        def transcribe(path):
            segments, info = model.transcribe(str(path), language="ja", vad_filter=True, beam_size=1, best_of=1)
            return {"segments": [{"start": item.start, "end": item.end, "text": item.text} for item in segments], "runtime_device": "cpu", "compute_type": "int8"}
    else:
        sys.path.insert(0, str(ROOT))
        import importlib
        from backend.mlx_transcription import transcribe as mlx_transcribe, model_path, gpu_runtime
        start = time.perf_counter()
        path = model_path(args.model)
        result["download_seconds"] = time.perf_counter() - start
        result["download_note"] = "Model cache resolution plus download, if missing"
        if args.download_only:
            target = OUTPUT / f"mlx-{args.model}-download.json"
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(target)
            return
        mx = gpu_runtime()
        holder = importlib.import_module("mlx_whisper.transcribe").ModelHolder
        start = time.perf_counter()
        loaded = holder.get_model(path, mx.float16)
        mx.eval(loaded.parameters())
        mx.synchronize()
        result["load_seconds"] = time.perf_counter() - start

        def transcribe(path):
            return mlx_transcribe(path, args.model)

    for case in args.cases:
        path = OUTPUT / f"{case}.wav"
        with wave.open(str(path), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
        timings = []
        for _ in range(args.repeat):
            start = time.perf_counter()
            transcript = transcribe(path)
            timings.append(time.perf_counter() - start)
        result["cases"][case] = {"elapsed_seconds": timings[0], "warm_median_seconds": statistics.median(timings[1:]) if len(timings) > 1 else None, "repeat_seconds": timings, "audio_seconds": duration, **transcript}
        print(json.dumps({case: result["cases"][case]}, ensure_ascii=False), flush=True)
    target = OUTPUT / f"{args.engine}-{args.model}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
