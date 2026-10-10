"""TTS 预处理：跳过不出声的节、小标题挂到中文段末、清英文口头禅、中文数字。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import OPENING_LINES, SUBSCRIBE_LINE
from .numbers import convert_numbers

SKIP_KEYS = (
    "审核附件",
    "生词好句",
    "生词表",
    "命中表",
    "命中盘点",
    "编辑部备注",
    "尾注",
    "发音辅导",
)
# 抒情腔。固定订阅句不算。来源：小Yo 审稿口径。
BANNED_PHRASES = (
    "镜头拉远",
    "值得玩味",
    "层层递进",
    "鸡汤收尾",
    "内心独白",
    "不禁让人",
    "心头一暖",
    "友邻的同学大家好",
    "原名瑜伽课后",
)
BANNED_TITLE_BITS = ("十八问重构", "十二问重构", "18问", "12问")
SHOW_NOTES_LEAKS = (
    "feishu.cn",
    "飞书",
    "导读钩子",
    "讲解稿直出",
    "公开编号",
    "mode=direct",
    "voice-clone",
    "音色 ID",
    "hard concat",
    "40ms",
)

_FILLER_SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:um+|uh+|uhh|umm|er|ah)\b[,.]?\s*", re.I), ""),
    (re.compile(r"\byou know\b[,.]?\s*", re.I), ""),
    (re.compile(r"\bI mean\b[,.]?\s*", re.I), ""),
    (re.compile(r"^(?:Yeah|Yep|Yes),\s+I think\s+", re.I), ""),
    (re.compile(r"\b([Yy]ou|[Tt]hey|[Ww]e|[Hh]e|[Ss]he|[Ii])\s+(?:was|were)\s+like\b", re.I), r"\1 said"),
    (re.compile(r",\s*like\b,?\s*", re.I), ", "),
    (re.compile(r"\blike,\s+", re.I), ""),
    (re.compile(r"\bkind of need\b", re.I), "KIND_OF_NEED"),
    (re.compile(r"\b(?:kind of|sort of)\b[,.]?\s*", re.I), ""),
    (re.compile(r"KIND_OF_NEED"), "kind of need"),
)
_PRONUN = re.compile(r"别读成|不要读成|词尾不送气|国际音标|\bIPA\b|[/／][^/／\s]{1,12}[/／]")


@dataclass
class Segment:
    text: str
    lang: str  # zh | en
    role: str = "body"  # opening | body
    heading: str = ""


@dataclass
class PreprocessResult:
    title: str
    segments: list[Segment] = field(default_factory=list)
    unattached_headings: list[str] = field(default_factory=list)
    spoken_text: str = ""

    @property
    def body_segments(self) -> list[Segment]:
        return [s for s in self.segments if s.role != "opening"]


def _strip_front_matter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + 4 :]
    return md


def _strip_inline(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"`+", "", text)
    text = re.sub(r"^>\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
    text = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
    return text.strip()


def _is_english(text: str) -> bool:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if latin >= 8 and cjk == 0:
        return True
    return latin > 24 and cjk <= 2


def _drop_pronunciation(text: str) -> str:
    parts = re.split(r"(?<=[。！？!?])", text)
    kept = [p for p in parts if p.strip() and not _PRONUN.search(p)]
    return "".join(kept).strip()


def _clean_english(text: str) -> str:
    for pattern, repl in _FILLER_SUBS:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r"\(\s*\)", "", text)
    return text.strip(" \t,")


def _heading_spoken(level: int, text: str) -> bool:
    if any(key in text for key in SKIP_KEYS):
        return False
    if level >= 3:
        return True
    return level == 2 and "英文原文与讲解" in text


def _is_skip_heading(text: str) -> bool:
    return any(key in text for key in SKIP_KEYS)


def _is_editorial(text: str) -> bool:
    """开场前的制作备注，不出声。"""
    if "确认稿" in text and ("模板" in text or "改口吻" in text or "不出声" in text):
        return True
    return False


@dataclass
class _Raw:
    kind: str  # heading | para
    level: int
    text: str


def _raw_blocks(md: str) -> tuple[str, list[_Raw]]:
    md = _strip_front_matter(md).replace("\r\n", "\n")
    title = ""
    blocks: list[_Raw] = []
    buf: list[str] = []
    in_code = False
    skip_level = 0

    def flush() -> None:
        nonlocal buf
        text = _strip_inline("\n".join(buf))
        buf = []
        if text and skip_level == 0:
            blocks.append(_Raw("para", 0, text))

    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped or stripped == "---":
            if not stripped:
                flush()
            continue
        if stripped.startswith("#"):
            flush()
            marks, rest = stripped.split(" ", 1) if " " in stripped else (stripped, "")
            if not set(marks) <= {"#"}:
                buf.append(stripped)
                continue
            level = len(marks)
            text = _strip_inline(rest)
            if level == 1 and not title:
                title = text
                continue
            if skip_level and level <= skip_level and not _is_skip_heading(text):
                skip_level = 0
            if _is_skip_heading(text):
                skip_level = level
                continue
            if skip_level:
                continue
            blocks.append(_Raw("heading", level, text))
            continue
        if skip_level:
            continue
        buf.append(stripped)
    flush()
    return title, blocks


def _attach(blocks: list[_Raw]) -> tuple[list[Segment], list[str]]:
    pending: list[str] = []
    segments: list[Segment] = []
    unattached: list[str] = []
    last_zh: int | None = None
    # 小标题必须挂在它后面、英文段前面的那句中文上。前面更早的中文不算。
    zh_after_heading = False

    def flush_headings(*, final: bool) -> None:
        nonlocal pending, zh_after_heading
        if not pending:
            return
        joined = "。".join(pending)
        if zh_after_heading and last_zh is not None:
            prev = segments[last_zh]
            prev.text = prev.text.rstrip("。") + "。" + joined
            prev.heading = joined
        else:
            unattached.extend(pending)
            if not final:
                segments.append(Segment(joined, "zh", heading=joined))
        pending = []
        zh_after_heading = False

    for block in blocks:
        if block.kind == "heading":
            if _heading_spoken(block.level, block.text):
                pending.append(block.text)
                zh_after_heading = False
            continue
        text = _drop_pronunciation(block.text)
        if not text or _is_editorial(text):
            continue
        if _is_english(text):
            flush_headings(final=False)
            segments.append(Segment(_clean_english(text), "en"))
            last_zh = None
            continue
        converted = convert_numbers(text)
        segments.append(Segment(converted, "zh"))
        last_zh = len(segments) - 1
        if pending:
            zh_after_heading = True
    flush_headings(final=True)
    return segments, unattached


def _mark_opening(segments: list[Segment]) -> None:
    """开场两句复用成片，不跟正文捆在一起重录。"""
    if not segments:
        return
    first = segments[0]
    if first.lang != "zh":
        return
    text = first.text
    if OPENING_LINES[0] not in text or OPENING_LINES[1] not in text:
        return
    rest = text
    for line in OPENING_LINES:
        rest = rest.replace(line, "", 1)
    rest = rest.strip()
    first.text = OPENING_LINES[0] + OPENING_LINES[1]
    first.role = "opening"
    if rest:
        segments.insert(1, Segment(rest, "zh"))


def preprocess(md: str, *, title: str = "") -> PreprocessResult:
    parsed_title, blocks = _raw_blocks(md)
    segments, unattached = _attach(blocks)
    _mark_opening(segments)
    spoken = "\n\n".join(s.text for s in segments if s.text)
    return PreprocessResult(
        title=title or parsed_title,
        segments=segments,
        unattached_headings=unattached,
        spoken_text=spoken,
    )


def filler_hits(text: str) -> list[str]:
    hits: list[str] = []
    checks = (
        (r"\b(?:um+|uh+|er|ah)\b", "um/uh"),
        (r"\byou know\b", "you know"),
        (r"\bI mean\b", "I mean"),
        (r",\s*like\b|\blike,", "like"),
        (r"\b(?:was|were)\s+like\b", "was/were like"),
        (r"\b(?:kind of|sort of)\b", "kind of/sort of"),
    )
    for pattern, label in checks:
        if label == "kind of/sort of" and re.search(r"\bkind of need\b", text, re.I):
            continue
        if re.search(pattern, text, re.I):
            hits.append(label)
    return hits


def banned_phrase_hits(text: str) -> list[str]:
    return [p for p in BANNED_PHRASES if p in text]


def number_violations(text: str) -> list[str]:
    """中文段里不该留下的数字读法。"""
    hits: list[str] = []
    if re.search(r"\$\s*\d", text):
        hits.append("美元符号叠在数字前")
    if "美元美元" in text:
        hits.append("美元叠读")
    if re.search(r"两千零二[一二三四五六七八九]", text):
        hits.append("年份读成了两千零")
    if re.search(r"(?<![A-Za-z\d.])\d", text):
        hits.append("中文段仍有阿拉伯数字")
    return hits


def script_structure_issues(result: PreprocessResult) -> list[str]:
    text = result.spoken_text
    issues: list[str] = []
    for line in OPENING_LINES:
        if line not in text:
            issues.append(f"缺少固定开场：{line}")
    if SUBSCRIBE_LINE not in text:
        issues.append("缺少固定订阅句")
    for heading in result.unattached_headings:
        issues.append(f"小标题没有挂进英文段前的中文段：{heading}")
    for seg in result.segments:
        if seg.lang != "en":
            continue
        for hit in filler_hits(seg.text):
            issues.append(f"英文口头禅还在：{hit}")
    for seg in result.segments:
        if seg.lang != "zh":
            continue
        for hit in number_violations(seg.text):
            issues.append(f"数字格式：{hit}")
    for hit in banned_phrase_hits(text):
        issues.append(f"禁用说法：{hit}")
    for bit in BANNED_TITLE_BITS:
        if bit in result.title:
            issues.append(f"公开标题含禁用字样：{bit}")
    return issues
