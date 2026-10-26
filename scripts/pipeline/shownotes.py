"""公开 Show Notes：五节骨架。没有一手新闻就不硬凑第 4 节。不写飞书、不写产线细节。"""
from __future__ import annotations

import html

POSTER = "https://joycenotebook.github.io/joyce-podcast/assets/listen-group-poster-v3.png"
GROUP = "加入听友群获取课程逐字稿、精读讲解稿、行业金句与核心思维模型等学习素材。"


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _topic(text: str) -> str:
    line = text.replace("\n", " ").strip()
    for sep in ("。", "？", "！", ".", "?"):
        if sep in line:
            line = line.split(sep, 1)[0] + sep
            break
    if len(line) > 72:
        line = line[:71] + "…"
    return line


def render_shownotes(meta: dict, segments: list[dict], markers: list[dict]) -> str:
    source = meta.get("source") or ""
    hook = meta.get("hook") or meta.get("desc") or ""
    guest = meta.get("guest") or "见本期口播"
    parts = [
        f"<p>透过AI播客学英文课。原文：{_esc(source)}。定位：{_esc(hook)}</p>",
        "<h2>1. 课程导读 · 公司近况</h2>",
        f"<p>{_esc(hook)}</p>",
        "<h2>2. 访谈嘉宾</h2>",
        "<ul>",
        f"<li>{_esc(guest)}</li>",
        f"<li>原访谈：{_esc(source)}</li>",
        "</ul>",
        "<h2>3. 主要话题时间线</h2>",
        "<table><thead><tr><th>时间</th><th>话题</th></tr></thead><tbody>",
    ]
    body = [s for s in segments if s.get("role") != "opening"]
    used = 0
    for marker in markers:
        if marker.get("label") == "固定开场":
            topic = "固定开场：欢迎回来，一起打磨输入输出系统。"
        elif used < len(body):
            topic = _topic(body[used]["text"])
            used += 1
        else:
            topic = marker.get("label") or "口播"
        parts.append(f"<tr><td>{_esc(marker.get('t', ''))}</td><td>{_esc(topic)}</td></tr>")
    parts.append("</tbody></table>")
    reading = [item for item in (meta.get("reading") or []) if str(item).strip()]
    if reading:
        parts.append("<h2>4. 延伸阅读</h2>")
        parts.append("<ul>")
        for item in reading:
            parts.append(f"<li>{_esc(str(item))}</li>")
        parts.append("</ul>")
    parts.extend(
        [
            "<h2>5. 听友群</h2>",
            f"<p>{GROUP}</p>",
            f'<p><img src="{POSTER}" alt="加入好事发声听友群" /></p>',
        ]
    )
    return "\n".join(parts) + "\n"
