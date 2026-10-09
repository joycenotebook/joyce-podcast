"""发布前质检。线上目录用 --report-only 出报告，不改文件；新稿用严格模式，有阻断就失败。"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .audio import duration_seconds
from .config import SHOW_TITLE
from .preprocess import (
    SHOW_NOTES_LEAKS,
    PreprocessResult,
    preprocess,
    script_structure_issues,
)

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
DURATION_TOLERANCE = 1.0


@dataclass
class Issue:
    level: str  # error | warn | info
    code: str
    message: str
    target: str = ""


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, target: str = "") -> None:
        self.issues.append(Issue(level, code, message, target))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    def ok(self) -> bool:
        return not self.errors


def check_script(md: str, *, title: str = "") -> tuple[PreprocessResult, Report]:
    result = preprocess(md, title=title)
    report = Report()
    for message in script_structure_issues(result):
        code = "script"
        if message.startswith("缺少固定开场"):
            code = "missing_opening"
        elif message.startswith("缺少固定订阅"):
            code = "missing_subscribe"
        elif message.startswith("小标题"):
            code = "unattached_heading"
        elif message.startswith("英文口头禅"):
            code = "english_filler"
        elif message.startswith("数字格式"):
            code = "number_format"
        elif message.startswith("禁用说法") or message.startswith("公开标题"):
            code = "banned_phrase"
        report.add("error", code, message, result.title or title)
    return result, report


def check_shownotes(html: str, target: str, report: Report) -> None:
    for leak in SHOW_NOTES_LEAKS:
        if leak in html:
            report.add("error", "shownotes_leak", f"公开 Show Notes 含禁止内容：{leak}", target)


def _file_belongs(episode_id: str, filename: str) -> bool:
    stem = filename[:-4] if filename.lower().endswith(".mp3") else filename
    return stem == episode_id or stem.startswith(episode_id + "-")


def _public_no(title: str) -> int | None:
    match = re.match(r"EP\s*(\d+)\b", title.strip(), re.I)
    return int(match.group(1)) if match else None


def _page_audio(page: Path) -> str | None:
    if not page.exists():
        return None
    match = re.search(r'src="\./audio/([^"]+)"', page.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _feed_items(feed: Path) -> dict[str, dict]:
    if not feed.exists():
        return {}
    root = ET.parse(feed).getroot()
    channel = root.find("channel")
    items: dict[str, dict] = {}
    if channel is None:
        return items
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        url = enc.get("url") if enc is not None else ""
        name = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
        dur = item.findtext(f"{{{ITUNES}}}duration")
        items[name] = {
            "url": url,
            "length": enc.get("length") if enc is not None else None,
            "title": item.findtext("title") or "",
            "duration": dur or "",
            "guid": item.findtext("guid") or "",
        }
    title = channel.findtext("title") or ""
    items["__channel_title__"] = {"title": title}
    return items


def check_catalog(root: Path, *, only_ids: set[str] | None = None, require_audio: bool = True) -> Report:
    report = Report()
    catalog_path = root / "episodes.json"
    if not catalog_path.exists():
        report.add("error", "missing_catalog", "没有 episodes.json", str(root))
        return report
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    podcast = data.get("podcast") or {}
    if podcast.get("title") != SHOW_TITLE:
        report.add("error", "show_title", f"频道标题不是「{SHOW_TITLE}」", podcast.get("title") or "")
    episodes = [ep for ep in data.get("episodes") or [] if ep.get("listed", True)]
    if only_ids is not None:
        episodes = [ep for ep in episodes if ep.get("id") in only_ids]
    feed = _feed_items(root / "feed.xml")
    channel = feed.get("__channel_title__", {}).get("title", "")
    if (root / "feed.xml").exists() and channel != SHOW_TITLE:
        report.add("error", "show_title", f"feed 频道标题不是「{SHOW_TITLE}」", channel)
    index_html = (root / "index.html").read_text(encoding="utf-8") if (root / "index.html").exists() else ""
    seen_public: dict[int, str] = {}
    for ep in episodes:
        eid = ep.get("id") or ""
        target = eid
        filename = ep.get("file") or ""
        if not filename or filename.endswith("/"):
            report.add("error", "bare_enclosure", "file 为空，enclosure 会变成目录", eid)
            continue
        if not _file_belongs(eid, filename):
            report.add("error", "file_id_mismatch", f"file {filename} 不属于 {eid}", eid)
        audio = root / "audio" / filename
        if require_audio:
            if not audio.exists():
                report.add("error", "missing_audio", f"缺少音频 audio/{filename}", eid)
            else:
                actual = audio.stat().st_size
                expected = int(ep.get("size_bytes") or 0)
                if actual != expected:
                    report.add(
                        "error",
                        "size_mismatch",
                        f"size_bytes={expected}，文件实际 {actual}",
                        eid,
                    )
                probed = duration_seconds(audio)
                listed = float(ep.get("duration_sec") or 0)
                if abs(probed - listed) > DURATION_TOLERANCE:
                    report.add(
                        "error",
                        "duration_mismatch",
                        f"duration_sec={int(listed)}，ffprobe {probed:.2f}s",
                        eid,
                    )
        item = feed.get(filename)
        if (root / "feed.xml").exists() and item is None:
            report.add("error", "feed_missing", f"feed.xml 没有 {filename}", eid)
        elif item:
            if item.get("url", "").rstrip("/").endswith("/audio"):
                report.add("error", "bare_enclosure", "enclosure 指向 audio 目录而不是文件", eid)
            length = item.get("length")
            if audio.exists() and length is not None and int(length) != audio.stat().st_size:
                report.add(
                    "error",
                    "feed_length_mismatch",
                    f"feed length={length}，文件 {audio.stat().st_size}",
                    eid,
                )
            enc_name = (item.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            if enc_name and enc_name != filename:
                report.add("error", "feed_file_mismatch", f"feed 文件是 {enc_name}", eid)
        page = root / f"{eid}.html"
        notes = root / "shownotes" / f"{eid}.html"
        if notes.exists():
            check_shownotes(notes.read_text(encoding="utf-8"), eid, report)
            if not page.exists():
                report.add("error", "page_missing", f"有 Show Notes 但没有 {eid}.html", eid)
        if page.exists():
            page_file = _page_audio(page)
            if page_file and page_file != filename:
                report.add(
                    "error",
                    "page_file_mismatch",
                    f"节目页播放 {page_file}，episodes.json 是 {filename}",
                    eid,
                )
        if index_html and filename and f'src="./audio/{filename}"' not in index_html:
            report.add("error", "index_file_mismatch", f"index.html 没有 audio/{filename}", eid)
        public = _public_no(ep.get("title") or "")
        if public is not None:
            if public in seen_public:
                report.add(
                    "error",
                    "duplicate_public_no",
                    f"公开编号 EP {public} 同时被 {seen_public[public]} 和 {eid} 使用",
                    eid,
                )
            else:
                seen_public[public] = eid
            internal = _internal_no(eid)
            if internal is not None and internal != public:
                report.add(
                    "info",
                    "public_vs_file_id",
                    f"公开编号 EP {public}，文件编号是 {eid}（既有编号策略，不是同一套数字）",
                    eid,
                )
    return report


def _internal_no(episode_id: str) -> int | None:
    match = re.fullmatch(r"ep-(\d+)", episode_id)
    return int(match.group(1)) if match else None


def render_markdown(report: Report, *, title: str) -> str:
    lines = [f"# {title}", ""]
    if report.ok():
        lines.append("没有阻断项。")
    else:
        lines.append(f"阻断 {len(report.errors)} 项。本报告只记录，不修改线上 `episodes.json`、`feed.xml` 或节目页。")
    lines.append("")
    for level, heading in (("error", "阻断"), ("warn", "需修正"), ("info", "提示")):
        rows = [i for i in report.issues if i.level == level]
        if not rows:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for issue in rows:
            where = f"`{issue.target}` " if issue.target else ""
            lines.append(f"- {where}**{issue.code}**：{issue.message}")
        lines.append("")
    lines.append("## 怎么读")
    lines.append("")
    lines.append("- 字节数、时长、节目页文件名和 feed enclosure 对不上，会挡住新一期上线。")
    lines.append("- 公开 EP 号和 `ep-0xx` 文件号不是同一套数字（例如 EP 24 对应 `ep-034`）。这是既有编号，记为提示，不因此改历史文件。")
    lines.append("- 同一公开编号被两期占用，或页面播放的 mp3 和 `episodes.json` 的 `file` 不是同一个，算失败。")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="播客发布前质检")
    parser.add_argument("--root", default=".", help="站点根目录")
    parser.add_argument("--script", default="", help="同时检查这篇口播稿")
    parser.add_argument("--title", default="")
    parser.add_argument("--report", default="", help="把 Markdown 报告写到这个路径")
    parser.add_argument("--report-only", action="store_true", help="即使有阻断也退出 0，只出报告")
    parser.add_argument("--only", default="", help="只核对这些 episode id，逗号分隔")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    only = {x for x in args.only.split(",") if x} or None
    report = check_catalog(root, only_ids=only)
    if args.script:
        _, script_report = check_script(Path(args.script).read_text(encoding="utf-8"), title=args.title)
        report.issues.extend(script_report.issues)
    text = render_markdown(report, title="发布前质检")
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text)
    if args.report_only:
        return 0
    return 0 if report.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
