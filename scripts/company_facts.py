"""企业追踪：读 workbench/companies.json，挂上节目，标出过期和未公开。

不访问网络，不读密钥，不改 episodes.json / feed.xml / 节目页。
"""
from __future__ import annotations

import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path

STALE_DAYS = 90
TYPES = ("官方披露", "财报", "媒体报道", "分析师预测", "播客中嘉宾原话")
JUDGMENTS = ("看多", "中性", "看空", "观察中")
SCALE_KEYS = ("活跃用户数", "交易/付费用户数", "订阅/交易金额", "企业收入", "企业利润")

# 这些叶子对应上一版要求的证据字段。status=未公开 的记入覆盖缺口。
LEAF_PATHS = (
    "business",
    "scale.活跃用户数",
    "scale.交易/付费用户数",
    "scale.订阅/交易金额",
    "scale.企业收入",
    "scale.企业利润",
    "growth",
    "model",
    "products",
    "iterations",
    "customers",
    "market",
    "moat",
    "valuation",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def companies_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / "workbench" / "companies.json"


def parse_as_of(value: str | None) -> date | None:
    """YYYY-MM-DD，或 YYYY-MM（按该月最后一天）。解析不了就返回 None。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            return None
        return date(y, mo, monthrange(y, mo)[1])
    return None


def age_days(as_of: str | None, today: date) -> int | None:
    parsed = parse_as_of(as_of)
    if parsed is None:
        return None
    return (today - parsed).days


def is_stale(as_of: str | None, today: date, days: int = STALE_DAYS) -> bool:
    age = age_days(as_of, today)
    return age is not None and age > days


def _hit(text: str, needles: list[str]) -> bool:
    if not text or not needles:
        return False
    for needle in needles:
        if not needle:
            continue
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])", text):
            return True
    return False


def _strip(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", text).strip()


def _guest_block(html: str) -> str:
    m = re.search(r"<h2>\s*2\.\s*访谈嘉宾\s*</h2>(.*?)(<h2>|$)", html, re.S)
    return _strip(m.group(1)) if m else ""


def _public_no(title: str, eid: str) -> int | None:
    m = re.match(r"EP\s*(\d+)", title or "")
    if m:
        return int(m.group(1))
    if eid == "ep-001":
        return 1
    return None


def load_episode_index(root: Path) -> list[dict]:
    cat = json.loads((root / "episodes.json").read_text(encoding="utf-8"))
    rows = []
    for ep in cat["episodes"]:
        eid = ep["id"]
        path = root / "shownotes" / f"{eid}.html"
        html = path.read_text(encoding="utf-8") if path.exists() else ""
        plain = _strip(html)
        rows.append(
            {
                "id": eid,
                "title": ep.get("title") or "",
                "desc": ep.get("desc") or "",
                "pubDate": ep.get("pub_date") or "",
                "publicNo": _public_no(ep.get("title") or "", eid),
                "guest": _guest_block(html),
                "lead": plain[:2500],
                "plain": plain,
            }
        )
    return rows


def attach_episodes(company: dict, episodes: list[dict]) -> list[dict]:
    rule = company.get("derive") or {}
    linked = []
    for ep in episodes:
        title_hit = _hit(ep["title"], rule.get("title") or [])
        guest_hit = _hit(ep["guest"], rule.get("guest") or [])
        lead_hit = _hit(ep["lead"], rule.get("lead") or [])
        spot_hit = _hit(ep["plain"], rule.get("spotlight") or [])
        mention_hit = _hit(
            "\n".join((ep["title"], ep["desc"], ep["plain"])),
            rule.get("mention") or [],
        )
        if title_hit or guest_hit or lead_hit or spot_hit:
            role = "主线"
        elif mention_hit:
            role = "提及"
        else:
            continue
        linked.append(
            {
                "id": ep["id"],
                "role": role,
                "publicNo": ep["publicNo"],
                "title": ep["title"],
                "pubDate": ep["pubDate"],
                "why": rule.get("how") or "",
            }
        )
    prim = [e for e in linked if e["role"] == "主线"]
    ment = [e for e in linked if e["role"] != "主线"]
    prim.sort(key=lambda e: e["pubDate"], reverse=True)
    ment.sort(key=lambda e: e["pubDate"], reverse=True)
    return prim + ment


def _is_undisclosed(node) -> bool:
    return isinstance(node, dict) and node.get("status") == "未公开"


def iter_facts(company: dict):
    """产出 (路径, 事实或未公开节点)。"""

    def walk(node, path: str):
        if isinstance(node, dict):
            if node.get("status") == "未公开" or (
                "value" in node and "sourceUrl" in node and "type" in node
            ):
                yield path, node
                return
            if node.get("source") and (node.get("text") or node.get("name") or node.get("date")):
                yield path, node
                return
            if "facts" in node and isinstance(node["facts"], list):
                for i, fact in enumerate(node["facts"]):
                    yield from walk(fact, f"{path}[{i}]")
                return
            if "items" in node and isinstance(node["items"], list):
                for i, item in enumerate(node["items"]):
                    yield from walk(item, f"{path}[{i}]")
                return
            for key, child in node.items():
                if key in ("derive", "thesis", "episodes", "coverage"):
                    continue
                yield from walk(child, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, child in enumerate(node):
                yield from walk(child, f"{path}[{i}]")

    yield from walk(company, "")


def leaf_node(company: dict, path: str):
    cur = company
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def leaf_undisclosed(node) -> bool:
    if node is None:
        return True
    if _is_undisclosed(node):
        return True
    if isinstance(node, dict) and "facts" in node:
        facts = node.get("facts") or []
        return len(facts) == 0
    if isinstance(node, dict) and "items" in node:
        return len(node.get("items") or []) == 0 and _is_undisclosed(node.get("tam") or {})
    if isinstance(node, dict) and "tam" in node and _is_undisclosed(node["tam"]):
        # 市场空间文字可以是草稿，TAM 未公开单独计，不把整段算成未公开
        return False
    if isinstance(node, dict) and (node.get("text") or node.get("unitEconomics")):
        return False
    return False


def coverage(company: dict, today: date) -> dict:
    undisclosed = []
    for path in LEAF_PATHS:
        node = leaf_node(company, path)
        if path == "market":
            tam = (node or {}).get("tam") if isinstance(node, dict) else None
            if _is_undisclosed(tam):
                undisclosed.append(path + ".tam")
            continue
        if path == "valuation":
            if _is_undisclosed(node) or not (isinstance(node, dict) and node.get("facts")):
                undisclosed.append(path)
            elif _is_undisclosed((node or {}).get("multiples")):
                undisclosed.append(path + ".multiples")
            continue
        if leaf_undisclosed(node):
            undisclosed.append(path)
    stale = []
    missing_date = []
    for path, fact in iter_facts(company):
        if fact.get("status") == "未公开":
            continue
        if "value" not in fact and "name" not in fact and "text" not in fact:
            continue
        as_of = fact.get("asOf") or (fact.get("source") or {}).get("asOf")
        if fact.get("value") is not None and re.search(r"\d", str(fact.get("value"))):
            if not as_of:
                missing_date.append(path)
            elif is_stale(as_of, today):
                stale.append({"path": path, "asOf": as_of, "value": fact.get("value")})
        elif as_of and is_stale(as_of, today):
            stale.append({"path": path, "asOf": as_of, "value": fact.get("value") or fact.get("text") or fact.get("name")})
    return {
        "leaves": len(LEAF_PATHS),
        "undisclosed": undisclosed,
        "undisclosedCount": len(undisclosed),
        "stale": stale,
        "staleCount": len(stale),
        "missingDate": missing_date,
    }


def annotate(company: dict, episodes: list[dict], today: date) -> dict:
    out = json.loads(json.dumps(company, ensure_ascii=False))
    out["episodes"] = attach_episodes(company, episodes)
    out["coverage"] = coverage(out, today)
    out.setdefault("thesis", {})
    out["thesis"].setdefault("judgment", "观察中")
    out["thesis"].setdefault("draft", True)
    return out


def load_raw(root: Path | None = None) -> dict:
    root = root or repo_root()
    return json.loads(companies_path(root).read_text(encoding="utf-8"))


def load_companies(root: Path | None = None, today: date | None = None) -> dict:
    root = root or repo_root()
    today = today or date.today()
    raw = load_raw(root)
    episodes = load_episode_index(root)
    companies = [annotate(c, episodes, today) for c in raw.get("companies") or []]
    return {
        "schema": raw.get("schema", 1),
        "disclaimer": raw.get("disclaimer") or "",
        "staleDays": raw.get("staleDays", STALE_DAYS),
        "asOf": today.isoformat(),
        "types": list(raw.get("types") or TYPES),
        "judgments": list(raw.get("judgments") or JUDGMENTS),
        "omitted": raw.get("omitted") or [],
        "pendingTopics": raw.get("pendingTopics") or [],
        "rivalries": raw.get("rivalries") or [],
        "list": companies,
    }


def fact_problems(company: dict) -> list[str]:
    """数字事实缺字段时返回说明。未公开不算问题。"""
    problems = []
    for path, fact in iter_facts(company):
        if fact.get("status") == "未公开":
            if fact.get("value") not in (None, "", "未公开"):
                problems.append(f"{company.get('id')} {path} 标了未公开又写了 value")
            continue
        if "value" not in fact:
            continue
        value = fact.get("value")
        if not re.search(r"\d", str(value)):
            continue
        for key in ("unit", "asOf", "sourceTitle", "sourceUrl", "type"):
            if not fact.get(key):
                problems.append(f"{company.get('id')} {path} 缺 {key}")
        if fact.get("type") and fact["type"] not in TYPES:
            problems.append(f"{company.get('id')} {path} 类型不在清单里")
        if fact.get("forecast") and fact.get("type") == "分析师预测" and not fact.get("sourceTitle"):
            problems.append(f"{company.get('id')} {path} 预测没有具名来源")
        if parse_as_of(fact.get("asOf")) is None:
            problems.append(f"{company.get('id')} {path} asOf 无法解析")
    return problems
