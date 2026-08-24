#!/usr/bin/env python3
"""从 episodes.json 生成 feed.xml。"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

RSS_NS = "http://www.w3.org/2005/Atom"
ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def _rfc2822(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str)
    except ValueError:
        dt = datetime.strptime(dt_str, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def _fmt_duration(sec) -> str:
    if sec is None:
        return "0:00"
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def shownotes_path(root: Path, ep: dict) -> Path:
    return root / "shownotes" / f"{ep['id']}.html"


def load_shownotes(root: Path, ep: dict) -> str:
    p = shownotes_path(root, ep)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def episode_page_url(cfg: dict, ep: dict) -> str:
    website = (cfg.get("website") or "").rstrip("/") + "/"
    return f"{website}{ep['id']}.html"


def episode_rss_description(root: Path, ep: dict) -> str:
    notes = load_shownotes(root, ep)
    return notes or ep.get("desc", "")


PAGE_CSS = """
    :root { color-scheme: dark; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; background: #1c1917; color: #fafaf9; }
    main { max-width: 720px; margin: 0 auto; padding: 48px 24px 80px; }
    img.cover { width: 100%; max-width: 360px; border-radius: 16px; display: block; }
    h1 { font-weight: 600; font-size: 28px; margin: 24px 0 8px; }
    h2 { font-weight: 600; font-size: 18px; margin: 32px 0 12px; }
    h3 { font-weight: 600; font-size: 15px; margin: 20px 0 8px; color: #e7e5e4; }
    p, li { color: #a8a29e; line-height: 1.65; }
    a { color: #c4a574; }
    .ep { margin-top: 28px; padding-top: 20px; border-top: 1px solid #292524; }
    audio { width: 100%; margin-top: 8px; }
    .notes ul { padding-left: 1.2em; }
    .notes li { margin: 0.45em 0; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; margin: 12px 0 24px; }
    th, td { border-bottom: 1px solid #292524; padding: 8px 6px; text-align: left; vertical-align: top; color: #a8a29e; }
    th { color: #fafaf9; font-weight: 600; }
    .back { font-size: 14px; }
""".strip()


def render_episode_page(cfg: dict, ep: dict, notes: str) -> str:
    title = xml_escape(ep["title"])
    show = xml_escape(cfg["title"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} · {show}</title>
  <link rel="alternate" type="application/rss+xml" title="{show}" href="./feed.xml" />
  <style>
    {PAGE_CSS}
  </style>
</head>
<body>
  <main>
    <p class="back"><a href="./">← {show}</a></p>
    <h1>{title}</h1>
    <audio controls preload="none" src="./audio/{xml_escape(ep["file"])}"></audio>
    <div class="notes">
{notes}
    </div>
  </main>
</body>
</html>
"""


def build_rss(cfg: dict, episodes: list[dict], root: Path) -> str:
    ET.register_namespace("itunes", ITUNES)
    ET.register_namespace("atom", RSS_NS)

    def E(tag, text=None, attrs=None):
        el = ET.Element(tag, attrs or {})
        if text:
            el.text = text
        return el

    channel = ET.Element("channel")
    website = cfg.get("website") or ""
    base_url = cfg.get("audio_base_url") or ""
    channel.append(E("title", cfg["title"]))
    channel.append(E("link", website))
    if website:
        feed_url = cfg.get("feed_url") or (website.rstrip("/") + "/feed.xml")
        channel.append(E(f"{{{RSS_NS}}}link", attrs={
            "href": feed_url, "rel": "self", "type": "application/rss+xml"
        }))
    channel.append(E("description", cfg["description"]))
    channel.append(E("language", cfg.get("language", "zh-cn")))
    channel.append(E("lastBuildDate", _rfc2822(datetime.now(timezone.utc).isoformat())))
    channel.append(E("generator", "dai-kexing"))
    if cfg.get("email"):
        ET.SubElement(channel, f"{{{ITUNES}}}owner").append(E("email", cfg["email"]))
    channel.append(E(f"{{{ITUNES}}}author", cfg.get("author", "")))
    channel.append(E(f"{{{ITUNES}}}explicit", "false"))
    channel.append(E(f"{{{ITUNES}}}subtitle", cfg.get("description", "")))
    channel.append(E(f"{{{ITUNES}}}summary", cfg.get("description", "")))
    channel.append(E(f"{{{ITUNES}}}type", "episodic"))
    if cfg.get("cover_url"):
        channel.append(E(f"{{{ITUNES}}}image", attrs={"href": cfg["cover_url"]}))

    for ep in episodes:
        item = ET.Element("item")
        fname = ep["file"]
        desc = episode_rss_description(root, ep)
        short = ep.get("desc", "")
        page = episode_page_url(cfg, ep) if load_shownotes(root, ep) else website
        item.append(E("title", ep["title"]))
        item.append(E("link", page))
        item.append(E("description", desc))
        item.append(E("pubDate", _rfc2822(ep["pub_date"])))
        audio_url = base_url.rstrip("/") + "/" + fname.lstrip("/")
        item.append(E("enclosure", attrs={
            "url": audio_url, "type": "audio/mpeg",
            "length": str(ep.get("size_bytes", 0))
        }))
        item.append(E("guid", audio_url, attrs={"isPermaLink": "true"}))
        item.append(E(f"{{{ITUNES}}}duration", _fmt_duration(ep.get("duration_sec"))))
        item.append(E(f"{{{ITUNES}}}title", ep["title"]))
        item.append(E(f"{{{ITUNES}}}subtitle", short[:120]))
        # Apple 限制 itunes:summary 4000 字；完整 Show Notes 放 description
        item.append(E(f"{{{ITUNES}}}summary", short or desc[:4000]))
        channel.append(item)

    root = ET.Element("rss", {"version": "2.0"})
    root.append(channel)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def render_index(cfg: dict, episodes: list[dict], root: Path) -> str:
    items = []
    for ep in episodes:
        notes_link = ""
        if load_shownotes(root, ep):
            notes_link = f'\n      <p><a href="./{ep["id"]}.html">Show Notes</a></p>'
        items.append(
            f"""    <div class="ep">
      <strong>{ep["title"]}</strong>
      <p>{ep.get("desc", "")}</p>
      <audio controls preload="none" src="./audio/{ep["file"]}"></audio>{notes_link}
    </div>"""
        )
    body = "\n".join(items)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{cfg["title"]}</title>
  <link rel="alternate" type="application/rss+xml" title="{cfg["title"]}" href="./feed.xml" />
  <style>
    {PAGE_CSS}
  </style>
</head>
<body>
  <main>
    <img class="cover" src="./cover.jpg" alt="{cfg["title"]}封面" />
    <h1>{cfg["title"]}</h1>
    <p>{cfg.get("description", "")}</p>
    <p>订阅 RSS：<a href="./feed.xml">feed.xml</a>（可粘贴到小宇宙搜索栏）</p>
{body}
  </main>
</body>
</html>
"""


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    data = json.loads((root / "episodes.json").read_text(encoding="utf-8"))
    cfg = data["podcast"]
    episodes = [e for e in data["episodes"] if e.get("listed", True)]
    episodes = sorted(episodes, key=lambda e: e["pub_date"], reverse=True)
    (root / "feed.xml").write_text(build_rss(cfg, episodes, root), encoding="utf-8")
    (root / "index.html").write_text(render_index(cfg, episodes, root), encoding="utf-8")
    pages = 0
    for ep in episodes:
        notes = load_shownotes(root, ep)
        if notes:
            (root / f"{ep['id']}.html").write_text(
                render_episode_page(cfg, ep, notes), encoding="utf-8"
            )
            pages += 1
    print(f"feed.xml + index.html + {pages} 期 Show Notes ({len(episodes)} 期)")


if __name__ == "__main__":
    main()
