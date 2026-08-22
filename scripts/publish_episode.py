#!/usr/bin/env python3
"""代可行执行器：仅处理已确认脚本。ListenHub 朗读 → 缝合片头 → 写 RSS。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

API_BASE = "https://api.marswave.ai/openapi/v1"
CLIENT_ID = "PJBkELS1o_q9nJ~NzF2_Fmr21TNX&~eoJR49FFdFhD3U"
DEFAULT_SPEAKER = "voice-clone-6a0326b627c53bd759c30acb"
ROOT = Path(__file__).resolve().parent.parent


def die(msg: str, code: int = 1) -> None:
    print(f"blocked: {msg}", file=sys.stderr)
    raise SystemExit(code)


def api(method: str, path: str, body: dict | None = None) -> dict:
    key = os.environ.get("LISTENHUB_API_KEY") or ""
    if not key:
        die("缺少 LISTENHUB_API_KEY")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "x-marswave-client-id": CLIENT_ID,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        die(f"ListenHub HTTP {e.code}: {detail[:500]}")


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], text=True)
    return float(out.strip())


def splice(raw: Path, intro: Path, out: Path) -> None:
    work = raw.parent
    body = work / "body.wav"
    intro_cut = work / "intro-cut.wav"
    mixed = work / "mixed.wav"
    run(["ffmpeg", "-y", "-i", str(raw), "-ar", "44100", "-ac", "2", str(body)])
    # 片头取前 7 秒，1.5s 渐入、末 1.2s 渐出，再与口播 acrossfade 1.2s
    run([
        "ffmpeg", "-y", "-i", str(intro), "-t", "7",
        "-af", "afade=t=in:st=0:d=1.5,afade=t=out:st=5.8:d=1.2",
        "-ar", "44100", "-ac", "2", str(intro_cut),
    ])
    run([
        "ffmpeg", "-y", "-i", str(intro_cut), "-i", str(body),
        "-filter_complex", "acrossfade=d=1.2:c1=tri:c2=tri,loudnorm=I=-14:LRA=11:TP=-1.5",
        str(mixed),
    ])
    run(["ffmpeg", "-y", "-i", str(mixed), "-codec:a", "libmp3lame", "-b:a", "192k", str(out)])


def next_episode_id(episodes: list[dict]) -> str:
    nums = []
    for ep in episodes:
        eid = ep.get("id", "")
        if eid.startswith("ep-"):
            try:
                nums.append(int(eid.split("-", 1)[1]))
            except ValueError:
                pass
    return f"ep-{max(nums, default=0) + 1:03d}"


def main() -> None:
    confirmed = (os.environ.get("CONFIRMED") or "").strip().lower()
    if confirmed not in {"yes", "true", "1", "confirmed"}:
        die("未确认脚本，拒绝出声。需要 Joyce 明确「确认上线」。")

    title = (os.environ.get("EPISODE_TITLE") or "").strip()
    script = (os.environ.get("EPISODE_SCRIPT") or "").strip()
    desc = (os.environ.get("EPISODE_DESC") or "").strip()
    speaker = (os.environ.get("SPEAKER_ID") or DEFAULT_SPEAKER).strip()
    episode_id = (os.environ.get("EPISODE_ID") or "").strip()
    if not title or not script:
        die("缺少 EPISODE_TITLE 或 EPISODE_SCRIPT")
    if len(script) > 10000:
        die("脚本超过 10000 字，ListenHub 不收")

    speakers = api("GET", "speakers/list?language=zh")
    items = (speakers.get("data") or {}).get("items") or speakers.get("items") or []
    match = [x for x in items if x.get("speakerId") == speaker]
    if not match:
        die(f"音色对不上：{speaker}。先核对 get-speakers。")
    print(f"speaker ok: {match[0].get('name')} {speaker}")

    created = api("POST", "flow-speech/episodes", {
        "sources": [{"type": "text", "content": script}],
        "speakers": [{"speakerId": speaker}],
        "language": "zh",
        "mode": "direct",
    })
    episode_lh = (created.get("data") or {}).get("episodeId") or created.get("episodeId")
    if not episode_lh:
        die(f"ListenHub 未返回 episodeId: {created}")
    print(f"listenhub episode: {episode_lh}")

    audio_url = ""
    for i in range(90):
        st = api("GET", f"flow-speech/episodes/{episode_lh}")
        data = st.get("data") or st
        status = data.get("processStatus") or "unknown"
        print(f"poll {i+1}: {status}")
        if status in {"success", "completed"}:
            audio_url = data.get("audioUrl") or ""
            break
        if status in {"failed", "error"}:
            die(f"ListenHub 生成失败: {st}")
        time.sleep(10)
    if not audio_url:
        die("ListenHub 超时，仍未完成")

    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    raw = work / "raw.mp3"
    urllib.request.urlretrieve(audio_url, raw)

    catalog = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    if not episode_id:
        episode_id = next_episode_id(catalog["episodes"])
    audio_name = f"{episode_id}.mp3"
    out = ROOT / "audio" / audio_name
    out.parent.mkdir(exist_ok=True)
    intro = ROOT / "assets" / "intro.mp3"
    if intro.exists():
        splice(raw, intro, out)
        print("spliced intro")
    else:
        run(["ffmpeg", "-y", "-i", str(raw), "-af", "loudnorm=I=-14:LRA=11:TP=-1.5",
             "-codec:a", "libmp3lame", "-b:a", "192k", str(out)])
        print("no intro, loudnorm only")

    size = out.stat().st_size
    duration = round(ffprobe_duration(out))
    pub_date = date.today().isoformat()
    catalog["episodes"] = [e for e in catalog["episodes"] if e.get("id") != episode_id]
    catalog["episodes"].insert(0, {
        "id": episode_id,
        "title": title,
        "file": audio_name,
        "duration_sec": duration,
        "size_bytes": size,
        "desc": desc or title,
        "pub_date": pub_date,
        "listed": True,
    })
    (ROOT / "episodes.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "rss_gen.py")])
    print(json.dumps({
        "result": "published",
        "id": episode_id,
        "title": title,
        "duration_sec": duration,
        "size_bytes": size,
        "audio": f"https://joycenotebook.github.io/joyce-podcast/audio/{audio_name}",
        "rss": "https://joycenotebook.github.io/joyce-podcast/feed.xml",
        "site": "https://joycenotebook.github.io/joyce-podcast/",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
