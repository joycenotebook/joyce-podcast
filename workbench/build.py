#!/usr/bin/env python3
"""播客产线工作台生成器：扫描仓库真实文件 → workbench/data.json，并内嵌进 index.html（file:// 也能打开）。

只读仓库，不改任何发布文件。用法：python3 workbench/build.py
"""
from __future__ import annotations

import hashlib
import sys
import html
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WB = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.company_facts import load_companies  # noqa: E402
SITE = "https://joycenotebook.github.io/joyce-podcast/"
REPO = "https://github.com/joycenotebook/joyce-podcast"
CST = timezone(timedelta(hours=8))

# 产线阶段：全部来自 scripts/publish_episode.py、scripts/rss_gen.py 与 git 提交记录
STAGES = [
    {"key": "source", "name": "选题·原文", "icon": "◎",
     "evidence": "Show Notes 首段「原文：…」记录一手来源（Lenny's / Lex / 斯坦福 MS&E 435 等）；提交记录 “from the Feishu archive”。"},
    {"key": "script", "name": "讲解稿确认", "icon": "✎",
     "evidence": "publish_episode.py 必须 CONFIRMED=yes 才出声（“需要 Joyce 明确「确认上线」”）；脚本 ≤10000 字；提交 “approved Feishu script”。讲解稿存于飞书，仓库内以成片存在为准推定。"},
    {"key": "audio", "name": "音色朗读·成片", "icon": "♪",
     "evidence": "ListenHub flow-speech 克隆音色朗读 → ffmpeg 缝合 assets/intro.mp3 片头（7s 渐入渐出 + 1.2s 交叉淡化）→ loudnorm -14 LUFS → 192k MP3 写入 audio/。"},
    {"key": "qa", "name": "试听·返工", "icon": "↻",
     "evidence": "提交记录大量 Rerecord / Retake / fix reading，音频版本号 -v2…-v8 / -r2，换 enclosure 或 guid 逼小宇宙重抓。"},
    {"key": "notes", "name": "Show Notes", "icon": "❡",
     "evidence": "shownotes/<id>.html，统一模板：课程导读·公司近况 / 访谈嘉宾 / 主要话题时间线 / 延伸阅读 / 听友群海报。"},
    {"key": "captions", "name": "字幕（可选）", "icon": "≡", "optional": True,
     "evidence": "transcripts/<id>.srt|.vtt → rss_gen 写入 podcast:transcript，供小宇宙字幕同步（目前仅 ep-011、ep-014）。"},
    {"key": "page", "name": "节目页·首页", "icon": "▣",
     "evidence": "rss_gen.py 用 Show Notes 渲染 <id>.html 与 index.html。"},
    {"key": "rss", "name": "RSS·小宇宙", "icon": "◉",
     "evidence": "rss_gen.py 从 episodes.json 生成 feed.xml（enclosure + guid + 完整 Show Notes），提交信息 “so Xiaoyuzhou can pull the new enclosure”。"},
]


def sh(*args: str) -> str:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(p: Path):
    if not shutil.which("ffprobe"):
        return None
    out = sh("ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(p))
    try:
        return float(out.strip())
    except ValueError:
        return None


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def classify(title: str, source: str) -> tuple[str, str]:
    """返回 (形式, 来源节目)。"""
    if "十八问" in title:
        fmt = "十八问重构"
    elif "新闻" in title:
        fmt = "新闻精讲"
    elif "斯坦福" in title or "斯坦福" in source:
        fmt = "斯坦福课程精读"
    elif title.startswith("EP"):
        fmt = "访谈精讲"
    else:
        fmt = "独白"
    s = source
    if "MS&E 435" in s or "Supercycle" in s:
        show = "斯坦福 AI 超周期经济学"
    elif "Economics of Generative AI" in s:
        show = "斯坦福 生成式 AI 经济学"
    elif "Lenny" in s:
        show = "Lenny's Podcast"
    elif "Lex Fridman" in s:
        show = "Lex Fridman"
    elif "No Priors" in s:
        show = "No Priors"
    elif "My First Million" in s:
        show = "My First Million"
    elif "Invest Like the Best" in s:
        show = "Invest Like the Best"
    elif "ListenLeap" in s or "AI Chat" in s:
        show = "AI Chat 合集"
    elif "DoorDash" in s:
        show = "DoorDash 访谈"
    elif "Anthropic" in s or "Amol" in s:
        show = "Lenny's Podcast" if "Lenny" in s else "Anthropic 访谈"
    elif "Meta" in title or "Manus" in title:
        show = "AI 新闻播客"
    elif "斯坦福" in title:
        show = "斯坦福 AI 超周期经济学"
    else:
        show = "原创"
    return fmt, show


def parse_srt(text: str, n: int = 8) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        ts = next((l for l in lines if "-->" in l), None)
        if not ts:
            continue
        body = " ".join(l for l in lines[lines.index(ts) + 1:])
        cues.append({"t": ts.split("-->")[0].strip().split(",")[0].split(".")[0], "text": body})
        if len(cues) >= n:
            break
    return cues


def git_history(paths: list[str]) -> list[dict]:
    out = sh("git", "log", "--format=%h\x1f%ad\x1f%s", "--date=iso-strict", "--", *paths)
    rows = []
    for line in out.splitlines():
        h, d, s = line.split("\x1f", 2)
        rows.append({"hash": h, "date": d, "subject": s})
    return rows


def main() -> None:
    cat = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    cfg = cat["podcast"]
    eps = cat["episodes"]

    # feed.xml
    feed_items = {}
    tree = ET.parse(ROOT / "feed.xml")
    ch = tree.getroot().find("channel")
    for it in ch.findall("item"):
        enc = it.find("enclosure")
        url = enc.get("url") if enc is not None else ""
        trs = [t.get("url") for t in it if t.tag.endswith("transcript")]
        feed_items[url] = {
            "title": it.findtext("title"), "guid": it.findtext("guid"),
            "length": enc.get("length") if enc is not None else None,
            "link": it.findtext("link"), "transcripts": trs,
            "pubDate": it.findtext("pubDate"),
        }
    index_html = (ROOT / "index.html").read_text(encoding="utf-8")
    index_audio = set(re.findall(r'src="\./audio/([^"]+)"', index_html))

    audio_dir = ROOT / "audio"
    all_audio = sorted(p.name for p in audio_dir.glob("*.mp3"))
    referenced = set()
    md5_cache: dict[str, str] = {}

    def amd5(name):
        if name not in md5_cache:
            md5_cache[name] = md5(audio_dir / name)
        return md5_cache[name]

    episodes = []
    for ep in eps:
        eid = ep["id"]
        num_internal = int(eid.split("-")[1])
        m = re.match(r"EP\s*(\d+)\.?\s*(.*)", ep["title"])
        pub_no = int(m.group(1)) if m else (1 if eid == "ep-001" else None)
        short_title = m.group(2) if m else ep["title"]
        afile = ep["file"]
        apath = audio_dir / afile
        referenced.add(afile)
        audio_url = cfg["audio_base_url"].rstrip("/") + "/" + afile
        issues = []

        # audio
        a_exists = apath.exists()
        a_size = apath.stat().st_size if a_exists else None
        a_raw = ffprobe(apath) if a_exists else None
        a_dur = round(a_raw) if a_raw is not None else None
        size_ok = a_exists and a_size == ep.get("size_bytes")
        if not a_exists:
            issues.append({"level": "error", "msg": f"audio/{afile} 不存在"})
        elif not size_ok:
            issues.append({"level": "warn", "msg": f"episodes.json size_bytes={ep.get('size_bytes')} 与实际文件 {a_size} 不一致"})
        if a_raw is not None and ep.get("duration_sec") and abs(a_raw - float(ep["duration_sec"])) > 1:
            issues.append({"level": "warn", "msg": f"duration_sec={int(float(ep['duration_sec']))}s，ffprobe 实测 {a_dur}s"})
        versions = sorted(n for n in all_audio if re.fullmatch(rf"{eid}(-[\w-]+)?\.mp3", n))
        referenced.update()  # noqa

        # shownotes
        sn = ROOT / "shownotes" / f"{eid}.html"
        sn_html = sn.read_text(encoding="utf-8") if sn.exists() else ""
        h2 = [strip_tags(x) for x in re.findall(r"<h2>(.*?)</h2>", sn_html)]
        src_m = re.search(r"原文[：是]\s*(.*?)(?:。|：|</p>)", sn_html)
        source = strip_tags(src_m.group(1)) if src_m else ""
        notes_checks = {
            "timeline": any("时间线" in h for h in h2),
            "guest": any("嘉宾" in h for h in h2),
            "reading": any("延伸阅读" in h or "来源" in h for h in h2),
            "group": any("听友群" in h for h in h2),
        }
        if sn_html and not source:
            issues.append({"level": "info", "msg": "Show Notes 未写「原文：」来源行"})
        if sn_html and not all(notes_checks.values()):
            miss = [k for k, v in {"时间线": notes_checks["timeline"], "嘉宾": notes_checks["guest"],
                                   "延伸阅读": notes_checks["reading"], "听友群": notes_checks["group"]}.items() if not v]
            issues.append({"level": "info", "msg": "Show Notes 与通用模板不同，缺：" + "、".join(miss)})

        # transcripts
        trs = sorted(p.name for p in (ROOT / "transcripts").glob(f"{eid}.*"))
        snippet = []
        srt = ROOT / "transcripts" / f"{eid}.srt"
        if srt.exists():
            snippet = parse_srt(srt.read_text(encoding="utf-8"))

        # page
        page = ROOT / f"{eid}.html"
        page_audio = None
        if page.exists():
            mm = re.search(r'src="\./audio/([^"]+)"', page.read_text(encoding="utf-8"))
            page_audio = mm.group(1) if mm else None
            if page_audio:
                referenced.add(page_audio)
            if page_audio and page_audio != afile:
                same = (audio_dir / page_audio).exists() and a_exists and amd5(page_audio) == amd5(afile)
                issues.append({"level": "info" if same else "warn",
                               "msg": f"节目页播放 {page_audio}，episodes.json/RSS 用 {afile}" + ("（文件内容相同，仅缓存版本）" if same else "（内容不同）") + "；下次跑 rss_gen 会被覆盖回 catalog 文件"})
        elif sn_html:
            issues.append({"level": "error", "msg": "有 Show Notes 但缺节目页 " + eid + ".html"})
        in_index = afile in index_audio
        if not in_index:
            issues.append({"level": "warn", "msg": "index.html 未收录这期音频"})

        # rss
        fi = feed_items.get(audio_url)
        if ep.get("listed", True) and not fi:
            issues.append({"level": "error", "msg": "episodes.json 已列出，但 feed.xml 没有对应 enclosure"})
        if fi and fi["length"] and str(fi["length"]) != str(ep.get("size_bytes")):
            issues.append({"level": "warn", "msg": "feed.xml enclosure length 与 episodes.json 不一致"})
        guid = (fi or {}).get("guid")
        if guid and guid != audio_url:
            issues.append({"level": "info", "msg": f"guid 固定为 {guid.rsplit('/',1)[-1]}，enclosure 已换 {afile}（重录保身份）"})

        hist = git_history([f"shownotes/{eid}.html", f"{eid}.html", *[f"audio/{v}" for v in versions]])
        rework_commits = [h for h in hist if re.search(r"(?i)rerecord|retake|re-record|重录|fix|patch|replace|swap|restitch|trim|drop|覆盖", h["subject"])]

        stages = {
            "source": bool(source) or bool(sn_html),
            "script": a_exists,
            "audio": a_exists,
            "qa": a_exists,
            "notes": bool(sn_html),
            "captions": bool(trs),
            "page": ("warn" if (page.exists() and in_index and page_audio and page_audio != afile) else (page.exists() and in_index)),
            "rss": ("warn" if (fi and not size_ok) else bool(fi)),
        }
        req = [s["key"] for s in STAGES if not s.get("optional")]
        done = sum(1 for k in req if stages[k])
        first_open = next((s["key"] for s in STAGES if not s.get("optional") and not stages[s["key"]]), "done")
        fmt, show = classify(ep["title"], source)
        episodes.append({
            "id": eid, "internalNo": num_internal, "publicNo": pub_no,
            "title": ep["title"], "shortTitle": short_title, "desc": ep.get("desc", ""),
            "pubDate": ep["pub_date"], "listed": ep.get("listed", True),
            "durationSec": int(float(ep.get("duration_sec") or 0)), "probedSec": a_dur,
            "sizeBytes": ep.get("size_bytes"), "file": afile, "audioUrl": audio_url,
            "versions": versions, "pageAudio": page_audio,
            "source": source, "format": fmt, "show": show,
            "shownotesHtml": sn_html, "shownotesSections": h2, "shownotesChars": len(strip_tags(sn_html)),
            "transcripts": trs, "transcriptSnippet": snippet,
            "inFeed": bool(fi), "guid": guid, "feedTranscripts": (fi or {}).get("transcripts", []),
            "stages": stages, "done": done, "total": len(req), "column": first_open,
            "issues": issues,
            "commits": hist, "commitCount": len(hist), "reworkCount": len(rework_commits) + max(0, len(versions) - 1),
            "firstCommit": hist[-1]["date"] if hist else None, "lastCommit": hist[0]["date"] if hist else None,
            "links": {
                "page": SITE + f"{eid}.html" if page.exists() else None,
                "audio": audio_url,
                "repoNotes": f"{REPO}/blob/main/shownotes/{eid}.html" if sn_html else None,
                "repoPage": f"{REPO}/blob/main/{eid}.html" if page.exists() else None,
                "repoAudio": f"{REPO}/blob/main/audio/{afile}",
                "transcript": [SITE + "transcripts/" + t for t in trs],
            },
        })

    episodes.sort(key=lambda e: (e["pubDate"], e["internalNo"]), reverse=True)

    # 全局缺口
    nums = sorted(e["internalNo"] for e in episodes)
    missing_internal = [n for n in range(1, max(nums) + 1) if n not in nums]
    def ranges(ns):
        out, start, prev = [], None, None
        for n in ns + [None]:
            if start is None:
                start = prev = n
            elif n is not None and n == prev + 1:
                prev = n
            else:
                out.append(f"ep-{start:03d}" + (f"–{prev:03d}" if prev != start else ""))
                start = prev = n
        return [r for r in out if "None" not in r]
    pub_nos = sorted(e["publicNo"] for e in episodes if e["publicNo"])
    missing_public = [n for n in range(1, max(pub_nos) + 1) if n not in pub_nos]
    orphan_audio = [n for n in all_audio if n not in referenced]
    out_of_order = []
    by_pub = sorted([e for e in episodes if e["publicNo"]], key=lambda e: e["publicNo"])
    for a, b in zip(by_pub, by_pub[1:]):
        if b["internalNo"] < a["internalNo"]:
            out_of_order.append(f"EP {b['publicNo']}（{b['id']}）编号小于 EP {a['publicNo']}（{a['id']}）")
    feed_orphans = [u for u in feed_items if u not in {e["audioUrl"] for e in episodes}]
    unlisted = [e["id"] for e in episodes if not e["listed"]]

    covers = []
    for p in sorted(ROOT.glob("cover*.jpg")):
        covers.append({"file": p.name, "size": p.stat().st_size, "md5": md5(p)[:8],
                       "current": cfg.get("cover_url", "").endswith(p.name)})
    posters = sorted(p.name for p in (ROOT / "assets").glob("listen-group-poster*.png"))

    # 全仓库提交时间（产能热力）
    allc = sh("git", "log", "--format=%ad\x1f%s", "--date=iso-strict")
    commit_days = defaultdict(int)
    for line in allc.splitlines():
        d, _ = line.split("\x1f", 1)
        commit_days[d[:10]] += 1
    head = sh("git", "log", "-1", "--format=%h\x1f%ad\x1f%s", "--date=iso-strict").strip().split("\x1f")

    data = {
        "generatedAt": datetime.now(CST).isoformat(timespec="seconds"),
        "repo": REPO, "site": SITE,
        "head": {"hash": head[0], "date": head[1], "subject": head[2]} if len(head) == 3 else None,
        "podcast": {k: cfg.get(k) for k in ("title", "author", "description", "website", "feed_url", "cover_url")},
        "coverLocal": "../" + cfg.get("cover_url", "cover.jpg").rsplit("/", 1)[-1],
        "speakerId": cat.get("speaker_id"),
        "stages": STAGES,
        "episodes": episodes,
        "gaps": {
            "missingInternal": ranges(missing_internal),
            "missingInternalCount": len(missing_internal),
            "missingPublic": missing_public,
            "outOfOrder": out_of_order,
            "orphanAudio": [{"file": n, "size": (audio_dir / n).stat().st_size} for n in orphan_audio],
            "feedOrphans": feed_orphans,
            "unlisted": unlisted,
            "feedItemCount": len(feed_items),
            "catalogCount": len(episodes),
        },
        "covers": covers, "posters": posters,
        "commitDays": dict(sorted(commit_days.items())),
        "totalCommits": sum(commit_days.values()),
        "audioFiles": len(all_audio),
        "companies": load_companies(ROOT),
    }
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    (WB / "data.json").write_text(payload, encoding="utf-8")

    idx = WB / "index.html"
    src = idx.read_text(encoding="utf-8")
    embedded = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    new = re.sub(r'(<script id="wb-data" type="application/json">)(.*?)(</script>)',
                 lambda m: m.group(1) + embedded + m.group(3), src, flags=re.S)
    idx.write_text(new, encoding="utf-8")
    print(f"✓ {len(episodes)} 期 · feed {len(feed_items)} 条 · 缺口 {ranges(missing_internal)} · 孤立音频 {len(orphan_audio)} → workbench/data.json + index.html")


if __name__ == "__main__":
    main()
