"""片头交叉淡化、开场硬接、正文硬拼、-14 LUFS。彩排用短提示音，不生成真人口播。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .preprocess import Segment

INTRO_FADE = 1.2
LUFS = "loudnorm=I=-14:TP=-1.5:LRA=11"


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("未找到 ffmpeg")
    return exe


def ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("未找到 ffprobe")
    return exe


def run(cmd: list[str]) -> None:
    if cmd and Path(cmd[0]).name.startswith("ffmpeg"):
        cmd = [cmd[0], "-hide_banner", "-loglevel", "error", *cmd[1:]]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or b"").decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(tail or f"command failed: {cmd[0]}") from exc


def duration_seconds(path: Path) -> float:
    out = subprocess.check_output(
        [
            ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


def _tone(path: Path, *, seconds: float, freq: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds:.2f},volume=-18dB",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(path),
        ]
    )


def synthesize_mock(segments: list[Segment], work: Path) -> list[Path]:
    """每个口播段一段短提示音。时长只为让拼接可测，不是真人口播时长。"""
    work.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    meta = []
    for i, seg in enumerate(segments):
        seconds = min(1.2, max(0.55, 0.35 + len(seg.text) / 400))
        freq = 392 if seg.lang == "zh" else 494
        path = work / f"part-{i:02d}.mp3"
        _tone(path, seconds=seconds, freq=freq)
        paths.append(path)
        meta.append({"file": path.name, "lang": seg.lang, "role": seg.role, "chars": len(seg.text), "mock_sec": seconds})
    (work / "segments.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return paths


def placeholder_opening(path: Path) -> None:
    """仓库里没有 opening-zh.mp3 时，彩排用另一段提示音占位。"""
    _tone(path, seconds=0.9, freq=330)


def _to_wav(src: Path, dst: Path) -> None:
    run([ffmpeg(), "-y", "-i", str(src), "-ar", "44100", "-ac", "2", str(dst)])


def _concat(wavs: list[Path], dst: Path) -> None:
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file '{p}'\n" for p in wavs), encoding="utf-8")
    run([ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dst)])


def stitch(*, work: Path, parts: list[Path], intro: Path, opening: Path | None, out: Path) -> dict:
    if not parts:
        raise RuntimeError("没有可拼接的口播段")
    wavs = []
    durs = []
    for part in parts:
        wav = work / f"{part.stem}.wav"
        _to_wav(part, wav)
        wavs.append(wav)
        durs.append(duration_seconds(wav))
    body = work / "body-concat.wav"
    _concat(wavs, body)

    if opening and opening.exists():
        opening_wav = work / "opening.wav"
        _to_wav(opening, opening_wav)
        opening_d = duration_seconds(opening_wav)
        with_open = work / "opening-body.wav"
        _concat([opening_wav, body], with_open)
        body = with_open
    else:
        opening_d = 0.0

    intro_wav = work / "intro.wav"
    _to_wav(intro, intro_wav)
    intro_d = duration_seconds(intro_wav)
    merged = work / "merged.wav"
    run(
        [
            ffmpeg(),
            "-y",
            "-i",
            str(intro_wav),
            "-i",
            str(body),
            "-filter_complex",
            f"[0:a][1:a]acrossfade=d={INTRO_FADE}:c1=tri:c2=tri[out]",
            "-map",
            "[out]",
            str(merged),
        ]
    )
    final_wav = work / "final.wav"
    run([ffmpeg(), "-y", "-i", str(merged), "-af", LUFS, "-ar", "44100", "-ac", "2", str(final_wav)])
    out.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg(),
            "-y",
            "-i",
            str(final_wav),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(out),
        ]
    )
    # 片头交叉淡化吃掉 INTRO_FADE；开场成片在淡化之后开始。
    offset = intro_d - INTRO_FADE
    markers = []
    if opening_d:
        markers.append({"t": _fmt(offset), "label": "固定开场", "lang": "zh"})
        offset += opening_d
    seg_meta = []
    seg_path = work / "segments.json"
    if seg_path.exists():
        seg_meta = json.loads(seg_path.read_text(encoding="utf-8"))
    for i, dur in enumerate(durs):
        label = "口播"
        lang = "?"
        if i < len(seg_meta):
            lang = seg_meta[i].get("lang", "?")
            label = "英文" if lang == "en" else "中文"
        markers.append({"t": _fmt(offset), "label": label, "lang": lang})
        offset += dur
    probed = duration_seconds(out)
    meta = {
        "sec": round(probed),
        "duration": probed,
        "size": out.stat().st_size,
        "markers": markers,
        "stitch": "concat_body+hard_opening+acrossfade_intro",
        "lufs": -14,
        "intro_fade_sec": INTRO_FADE,
    }
    (work / "markers.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def _fmt(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


def safe_filename(name: str) -> str:
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.mp3", name):
        raise ValueError(f"音频文件名不合法: {name}")
    return name
