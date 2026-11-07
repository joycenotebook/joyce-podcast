"""一条命令：确认稿 → 预处理 → TTS → 拼接 → Show Notes → 站点 rss_gen。

默认 dry-run：产物只进输出目录，不改仓库里的 feed / 节目页 / 音频。
真上线必须 mode=live 且 CONFIRMED=yes（或「确认上线」）且 ALLOW_LISTENHUB=yes。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .audio import placeholder_opening, safe_filename, stitch
from .config import DEFAULT_SPEAKER, SHOW_TITLE, confirmed
from .preprocess import Segment, preprocess
from .providers import provider_for
from .qc import Report, check_catalog, check_script, check_shownotes
from .shownotes import render_shownotes

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "pipeline" / "samples" / "rehearsal-doordash"
CST = timezone(timedelta(hours=8))


def _die(message: str, code: int = 1) -> None:
    print(f"blocked: {message}", file=sys.stderr)
    raise SystemExit(code)


def _load_job(path: Path) -> tuple[str, dict]:
    if path.is_dir():
        script_path = path / "script.md"
        meta_path = path / "meta.json"
    else:
        script_path = path
        meta_path = path.with_name("meta.json")
    if not script_path.exists():
        _die(f"找不到脚本 {script_path}")
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.setdefault("title", "")
    return script_path.read_text(encoding="utf-8"), meta


def _episode_row(meta: dict, filename: str, seconds: int, size: int) -> dict:
    row = {
        "id": meta["id"],
        "title": meta["title"],
        "file": filename,
        "duration_sec": seconds,
        "size_bytes": size,
        "desc": meta.get("desc") or meta["title"],
        "pub_date": meta.get("pub_date") or datetime.now(CST).date().isoformat(),
        "listed": True,
    }
    if meta.get("guid"):
        row["guid"] = meta["guid"]
    return row


def _prepare_site(out: Path, episode: dict, notes: str) -> Path:
    site = out / "site"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    (site / "audio").mkdir()
    (site / "shownotes").mkdir()
    (site / "transcripts").mkdir()
    catalog = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    if catalog.get("podcast", {}).get("title") != SHOW_TITLE:
        _die("线上 episodes.json 的频道标题被动过，停止")
    catalog["episodes"] = [ep for ep in catalog["episodes"] if ep.get("id") != episode["id"]]
    catalog["episodes"].insert(0, episode)
    (site / "episodes.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    src_notes = ROOT / "shownotes"
    if src_notes.exists():
        for html in src_notes.glob("*.html"):
            shutil.copy2(html, site / "shownotes" / html.name)
    (site / "shownotes" / f"{episode['id']}.html").write_text(notes, encoding="utf-8")
    env = os.environ.copy()
    env["PODCAST_ROOT"] = str(site)
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "rss_gen.py")], cwd=ROOT, env=env)
    produced = out / "audio" / episode["file"]
    shutil.copy2(produced, site / "audio" / episode["file"])
    return site


def _guards(mode: str, meta: dict) -> None:
    if mode not in {"dry-run", "live"}:
        _die(f"未知 mode: {mode}")
    if mode == "dry-run":
        return
    if not confirmed():
        _die("真上线被拒绝。把 CONFIRMED 设为 yes，或由 Joyce 明确说「确认上线」。当前默认只彩排。")
    if os.environ.get("ALLOW_LISTENHUB", "").strip().lower() not in {"yes", "true", "1"}:
        _die("真上线还要 ALLOW_LISTENHUB=yes。没有这道开关就不会调用 ListenHub。")
    if meta.get("rehearsal") or str(meta.get("id", "")).startswith("ep-900"):
        _die("彩排样本不能真上线")
    if str(meta.get("title", "")).startswith("[彩排]"):
        _die("彩排标题不能真上线")


def _apply_live(episode: dict, notes: str, audio: Path) -> None:
    """只有闸门都通过才写仓库。本函数不自己决定能不能上线。"""
    catalog_path = ROOT / "episodes.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    ids = {ep.get("id") for ep in catalog["episodes"]}
    if episode["id"] in ids and os.environ.get("REPLACE_EPISODE", "").strip().lower() not in {"yes", "true", "1"}:
        _die(f"{episode['id']} 已在 episodes.json。要覆盖必须再设 REPLACE_EPISODE=yes")
    dest = ROOT / "audio" / episode["file"]
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(audio, dest)
    (ROOT / "shownotes" / f"{episode['id']}.html").write_text(notes, encoding="utf-8")
    catalog["episodes"] = [ep for ep in catalog["episodes"] if ep.get("id") != episode["id"]]
    catalog["episodes"].insert(0, episode)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "rss_gen.py")], cwd=ROOT)


def _assert_source(source: Path, mode: str) -> None:
    resolved = source.resolve()
    root = ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        _die("稿件必须在这个仓库里面")
    if mode == "live":
        queue = (root / "queue").resolve()
        if resolved != queue and queue not in resolved.parents:
            _die("真上线只读取 queue/ 里的稿，不会拿彩排样本去出声")


def run_job(source: Path, out: Path, mode: str, *, episode_id: str = "", title: str = "") -> dict:
    _assert_source(source, mode)
    script, meta = _load_job(source)
    if episode_id:
        meta["id"] = episode_id
    if title:
        meta["title"] = title
    if not meta.get("id"):
        _die("meta.json 缺少 id")
    _guards(mode, meta)
    if mode == "dry-run" and out.resolve() == ROOT.resolve():
        _die("彩排不能写到仓库根目录")
    prepared, script_report = check_script(script, title=meta.get("title") or "")
    if not meta.get("title"):
        meta["title"] = prepared.title
    if not script_report.ok():
        for issue in script_report.errors:
            print(f"qc: {issue.message}", file=sys.stderr)
        _die("稿件质检没过，停止。不调用 TTS。")
    if not prepared.title and not meta.get("title"):
        _die("没有标题")
    meta["title"] = meta.get("title") or prepared.title

    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (out / "spoken.txt").write_text(prepared.spoken_text + "\n", encoding="utf-8")

    speaker = (meta.get("speaker_id") or os.environ.get("SPEAKER_ID") or DEFAULT_SPEAKER).strip()
    provider = provider_for(mode, speaker)
    parts = provider.synthesize(prepared.segments, work)

    opening = ROOT / "assets" / "opening-zh.mp3"
    opening_note = "assets/opening-zh.mp3"
    if not opening.exists():
        opening = work / "opening-placeholder.mp3"
        placeholder_opening(opening)
        opening_note = "缺失 assets/opening-zh.mp3，彩排用提示音占位。真上线前要把 EP20 定稿的开场成片放进 assets/opening-zh.mp3，不要每期重录开场两句。"
    intro = ROOT / "assets" / "intro.mp3"
    if not intro.exists():
        _die("缺少 assets/intro.mp3")
    filename = safe_filename(f"{meta['id']}.mp3")
    audio_out = out / "audio" / filename
    stitched = stitch(work=work, parts=parts, intro=intro, opening=opening, out=audio_out)

    seg_dump = [
        {"text": seg.text, "lang": seg.lang, "role": seg.role}
        for seg in prepared.segments
        if isinstance(seg, Segment)
    ]
    notes = render_shownotes(meta, seg_dump, stitched["markers"])
    (out / "shownotes.html").write_text(notes, encoding="utf-8")
    notes_report = Report()
    check_shownotes(notes, meta["id"], notes_report)
    if not notes_report.ok():
        for issue in notes_report.errors:
            print(f"qc: {issue.message}", file=sys.stderr)
        _die("Show Notes 质检没过")

    episode = _episode_row(meta, filename, int(stitched["sec"]), int(stitched["size"]))
    if mode == "live":
        _apply_live(episode, notes, audio_out)
        site = ROOT
        catalog_report = check_catalog(ROOT, only_ids={meta["id"]})
    else:
        site = _prepare_site(out, episode, notes)
        catalog_report = check_catalog(site, only_ids={meta["id"]})
    if not catalog_report.ok():
        for issue in catalog_report.errors:
            print(f"qc: {issue.target} {issue.message}", file=sys.stderr)
        _die("成片和 feed 对不上，停止")

    summary = {
        "result": "dry-run" if mode == "dry-run" else "published",
        "provider": provider.name,
        "id": meta["id"],
        "title": meta["title"],
        "audio": str(audio_out if mode == "dry-run" else ROOT / "audio" / filename),
        "duration_sec": episode["duration_sec"],
        "size_bytes": episode["size_bytes"],
        "site": str(site),
        "opening": opening_note,
        "committed": mode == "live",
        "listenhub_called": provider.name == "listenhub",
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发声播客上线（默认彩排）")
    parser.add_argument("--input", default="", help="队列目录、script.md，或留空使用内置彩排样本")
    parser.add_argument("--sample", action="store_true", help="使用内置彩排样本")
    parser.add_argument("--out", default="artifacts/dry-run")
    parser.add_argument("--mode", choices=("dry-run", "live"), default="dry-run")
    parser.add_argument("--episode-id", default="")
    parser.add_argument("--title", default="")
    args = parser.parse_args(argv)
    mode = args.mode
    if os.environ.get("PUBLISH_MODE", "").strip() == "live":
        mode = "live"
    if os.environ.get("PUBLISH_MODE", "").strip() == "dry-run":
        mode = "dry-run"
    source = Path(args.input) if args.input else SAMPLE
    if args.sample:
        source = SAMPLE
    if not source.is_absolute():
        source = ROOT / source
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    run_job(source, out, mode, episode_id=args.episode_id, title=args.title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
