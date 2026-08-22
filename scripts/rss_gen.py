#!/usr/bin/env python3
"""从 episodes.json 生成 feed.xml。"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

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


def build_rss(cfg: dict, episodes: list[dict]) -> str:
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
        item.append(E("title", ep["title"]))
        item.append(E("link", website))
        item.append(E("description", ep.get("desc", "")))
        item.append(E("pubDate", _rfc2822(ep["pub_date"])))
        audio_url = base_url.rstrip("/") + "/" + fname.lstrip("/")
        item.append(E("enclosure", attrs={
            "url": audio_url, "type": "audio/mpeg",
            "length": str(ep.get("size_bytes", 0))
        }))
        item.append(E("guid", audio_url, attrs={"isPermaLink": "true"}))
        item.append(E(f"{{{ITUNES}}}duration", _fmt_duration(ep.get("duration_sec"))))
        item.append(E(f"{{{ITUNES}}}title", ep["title"]))
        item.append(E(f"{{{ITUNES}}}subtitle", ep.get("desc", "")[:120]))
        item.append(E(f"{{{ITUNES}}}summary", ep.get("desc", "")))
        channel.append(item)

    root = ET.Element("rss", {"version": "2.0"})
    root.append(channel)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def render_index(cfg: dict, episodes: list[dict]) -> str:
    items = []
    for ep in episodes:
        items.append(
            f"""    <div class="ep">
      <strong>{ep["title"]}</strong>
      <p>{ep.get("desc", "")}</p>
      <audio controls preload="none" src="./audio/{ep["file"]}"></audio>
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
    :root {{ color-scheme: dark; }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; background: #1c1917; color: #fafaf9; }}
    main {{ max-width: 640px; margin: 0 auto; padding: 48px 24px 80px; }}
    img.cover {{ width: 100%; max-width: 360px; border-radius: 16px; display: block; }}
    h1 {{ font-weight: 600; font-size: 28px; margin: 24px 0 8px; }}
    p {{ color: #a8a29e; line-height: 1.6; }}
    a {{ color: #c4a574; }}
    .ep {{ margin-top: 28px; padding-top: 20px; border-top: 1px solid #292524; }}
    audio {{ width: 100%; margin-top: 8px; }}
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
    (root / "feed.xml").write_text(build_rss(cfg, episodes), encoding="utf-8")
    (root / "index.html").write_text(render_index(cfg, episodes), encoding="utf-8")
    print(f"feed.xml + index.html ({len(episodes)} 期)")


if __name__ == "__main__":
    main()
