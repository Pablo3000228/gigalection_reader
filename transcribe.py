"""Транскрибация лекций через GigaAM (onnx-asr) + извлечение ключевых кадров.

Структура:
    input/<Предмет>/<лекция>.mp4   ->  output/<Предмет>/<лекция>/transcript.md
                                        output/<Предмет>/<лекция>/frames/HH-MM-SS.jpg

Запуск:
    python transcribe.py                 # обработать всё новое из input/
    python transcribe.py --force         # переделать уже обработанные
    python transcribe.py --no-frames     # без ключевых кадров
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "input"
OUTPUT = ROOT / "output"
NO_SUBJECT = "Без предмета"

VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus"}


def hms(seconds: float, sep: str = ":") -> str:
    s = int(seconds)
    return f"{s // 3600:02d}{sep}{s % 3600 // 60:02d}{sep}{s % 60:02d}"


def run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def extract_audio(src: Path, wav: Path) -> None:
    r = run_ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg не смог извлечь звук:\n{r.stderr[-2000:]}")


def extract_frames(src: Path, frames_dir: Path, scene: float, min_gap: float, interval: float) -> list[float]:
    """Сохраняет кадр при смене слайда. Возвращает список времён (сек) сохранённых кадров."""
    tmp = frames_dir / "_tmp"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    tmp.mkdir(parents=True)

    # 1 кадр/с для анализа; первый кадр берём всегда, далее — при заметной смене картинки
    # (слайды) и не реже раза в interval секунд (доска, которую исписывают постепенно)
    vf = (f"fps=1,select='eq(n\\,0)+gt(scene\\,{scene})+gte(t-prev_selected_t\\,{interval})',"
          f"showinfo,scale='min(1280,iw)':-2")
    r = run_ffmpeg(["-i", str(src), "-an", "-vf", vf, "-fps_mode", "vfr", "-q:v", "3", str(tmp / "%05d.jpg")])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg не смог извлечь кадры:\n{r.stderr[-2000:]}")

    times = [float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    files = sorted(tmp.glob("*.jpg"))

    # Слайды с анимацией дают серию кадров подряд — оставляем последний из серии (полный слайд)
    kept: list[tuple[float, Path]] = []
    for t, f in zip(times, files):
        if kept and t - kept[-1][0] < min_gap:
            kept[-1] = (t, f)
        else:
            kept.append((t, f))

    for t, f in kept:
        f.rename(frames_dir / f"{hms(t, '-')}.jpg")
    shutil.rmtree(tmp)
    return [t for t, _ in kept]


def transcribe(model, wav: Path, out_md: Path, title: str, frame_times: list[float],
               duration: float, para_gap: float, para_max: float) -> None:
    partial = out_md.with_suffix(".md.partial")
    frames = list(frame_times)
    started = time.perf_counter()

    with partial.open("w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"Длительность: {hms(duration)}. Расшифровка GigaAM v3, возможны ошибки в терминах.\n\n")

        para: list[str] = []
        para_start = prev_end = None

        def flush() -> None:
            nonlocal para
            if para:
                f.write(f"[{hms(para_start)}] " + " ".join(para) + "\n\n")
                f.flush()
                para = []

        for seg in model.recognize(str(wav)):
            text = seg.text.strip()
            if not text:
                continue
            new_para = (
                para_start is None
                or seg.start - prev_end > para_gap
                or seg.start - para_start > para_max
                or (frames and frames[0] <= seg.start)  # смена слайда — обычно новая мысль
            )
            if new_para:
                flush()
                para_start = seg.start
                # Кадры, появившиеся до начала этого абзаца, ставим перед ним
                while frames and frames[0] <= seg.start:
                    f.write(f"![кадр {hms(frames[0])}](frames/{hms(frames.pop(0), '-')}.jpg)\n\n")
            para.append(text)
            prev_end = seg.end
            elapsed = time.perf_counter() - started
            if duration:
                print(f"\r  распознано {hms(seg.end)} / {hms(duration)}  ({seg.end / elapsed:.0f}x)",
                      end="", flush=True)
        flush()
        for t in frames:
            f.write(f"![кадр {hms(t)}](frames/{hms(t, '-')}.jpg)\n\n")

    print()
    partial.replace(out_md)


def find_lectures() -> list[tuple[str, Path]]:
    found = []
    for p in sorted(INPUT.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXT | AUDIO_EXT:
            rel = p.relative_to(INPUT)
            subject = rel.parts[0] if len(rel.parts) > 1 else NO_SUBJECT
            found.append((subject, p))
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="переобработать уже готовые лекции")
    ap.add_argument("--no-frames", action="store_true", help="не извлекать кадры из видео")
    ap.add_argument("--no-int8", action="store_true", help="полная точность модели (медленнее)")
    ap.add_argument("--model", default="gigaam-v3-e2e-rnnt", help="модель onnx-asr")
    ap.add_argument("--max-seg", type=float, default=20, help="макс. длина сегмента VAD, сек")
    ap.add_argument("--para-gap", type=float, default=5.0, help="пауза для нового абзаца, сек")
    ap.add_argument("--para-max", type=float, default=90, help="макс. длина абзаца, сек")
    ap.add_argument("--scene", type=float, default=0.12, help="порог смены кадра (0..1, меньше = больше кадров)")
    ap.add_argument("--frame-gap", type=float, default=8, help="кадры ближе этого интервала схлопываются, сек")
    ap.add_argument("--frame-every", type=float, default=90, help="снимок не реже чем раз в N сек (для доски)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg не найден в PATH. Установите: winget install Gyan.FFmpeg и перезапустите терминал.")

    INPUT.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)

    todo = []
    for subject, src in find_lectures():
        out_dir = OUTPUT / subject / src.stem
        if (out_dir / "transcript.md").exists() and not args.force:
            continue
        todo.append((subject, src, out_dir))

    if not todo:
        print("Новых лекций нет. Положите файлы в input/<Предмет>/ и запустите снова.")
        return

    print(f"К обработке: {len(todo)}")
    for subject, src, _ in todo:
        print(f"  {subject} / {src.name}")

    import onnx_asr  # импорт здесь, чтобы --help и «нечего делать» работали мгновенно

    print("\nЗагрузка модели (при первом запуске скачивается с Hugging Face)...")
    model = onnx_asr.load_model(args.model, quantization=None if args.no_int8 else "int8")
    vad = onnx_asr.load_vad("silero")
    model = model.with_vad(vad, max_speech_duration_s=args.max_seg, min_silence_duration_ms=300, speech_pad_ms=100)

    for i, (subject, src, out_dir) in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {subject} / {src.name}")
        out_dir.mkdir(parents=True, exist_ok=True)
        duration = probe_duration(src)
        t0 = time.perf_counter()

        frame_times: list[float] = []
        if src.suffix.lower() in VIDEO_EXT and not args.no_frames:
            print("  извлечение ключевых кадров...")
            frame_times = extract_frames(src, out_dir / "frames", args.scene, args.frame_gap, args.frame_every)
            print(f"  кадров: {len(frame_times)}")

        wav = out_dir / "_audio.wav"
        print("  извлечение звука...")
        extract_audio(src, wav)
        try:
            transcribe(model, wav, out_dir / "transcript.md", src.stem, frame_times,
                       duration, args.para_gap, args.para_max)
        finally:
            wav.unlink(missing_ok=True)

        spent = time.perf_counter() - t0
        speed = f", {duration / spent:.0f}x реального времени" if duration else ""
        print(f"  готово за {hms(spent)}{speed} -> {out_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
