"""企业追踪：节目挂接、未公开、过期，以及不改线上节目文件。"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from scripts.companies_refresh import main
from scripts.company_facts import fact_problems, load_companies

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 10)


def _bundle():
    return load_companies(ROOT, today=TODAY)


def _by_id():
    return {c["id"]: c for c in _bundle()["list"]}


def test_companies_come_from_published_episodes():
    rows = _by_id()
    assert "notion" not in rows and "higgsfield" not in rows
    door = [e["id"] for e in rows["doordash"]["episodes"] if e["role"] == "主线"]
    assert door == ["ep-029"]
    anth = [e["id"] for e in rows["anthropic"]["episodes"] if e["role"] == "主线"]
    for eid in ("ep-034", "ep-020", "ep-006", "ep-003", "ep-002"):
        assert eid in anth
    openai_main = [e["id"] for e in rows["openai"]["episodes"] if e["role"] == "主线"]
    assert "ep-010" in openai_main and "ep-007" in openai_main and "ep-016" in openai_main
    assert "ep-009" not in openai_main
    assert "ep-009" in [e["id"] for e in rows["openai"]["episodes"] if e["role"] == "提及"]
    assert "ep-016" in [e["id"] for e in rows["nvidia"]["episodes"] if e["role"] == "主线"]
    assert rows["nvidia"]["derive"]["role"] == "正文点名"
    assert "ep-017" in [e["id"] for e in rows["applied-compute"]["episodes"] if e["role"] == "主线"]
    assert rows["doordash"]["thesis"]["judgment"] == "观察中"
    assert rows["doordash"]["thesis"]["draft"] is True


def test_numeric_facts_are_sourced_and_private_profit_stays_blank():
    rows = _by_id()
    for co in rows.values():
        assert fact_problems(co) == []
    assert rows["anthropic"]["scale"]["企业利润"]["status"] == "未公开"
    assert rows["openai"]["scale"]["企业利润"]["status"] == "未公开"
    assert rows["cursor"]["scale"]["企业收入"]["status"] == "未公开"
    assert rows["nvidia"]["scale"]["企业利润"]["facts"]
    assert rows["doordash"]["scale"]["活跃用户数"]["status"] == "未公开"


def test_stale_and_podcast_scale_are_not_rewritten():
    rows = _by_id()
    stale = [row["asOf"] for row in rows["anthropic"]["coverage"]["stale"]]
    assert any(item.startswith("2026-05") for item in stale)
    raw = json.loads((ROOT / "workbench" / "companies.json").read_text(encoding="utf-8"))
    anth = next(c for c in raw["companies"] if c["id"] == "anthropic")
    growth = anth["growth"]["facts"][0]
    assert growth["value"] == "10 → 190"
    assert "1900" not in growth["value"]
    assert "非投资建议" in raw["disclaimer"]


def test_refresh_reports_without_failing():
    assert main(["--root", str(ROOT), "--as-of", "2026-10-10"]) == 0


def test_tracking_does_not_touch_live_catalog():
    files = ["episodes.json", "feed.xml", "index.html", "ep-014.html", "ep-010.html"]
    before = {name: hashlib.md5((ROOT / name).read_bytes()).hexdigest() for name in files}
    load_companies(ROOT, today=TODAY)
    main(["--root", str(ROOT), "--as-of", "2026-10-10"])
    after = {name: hashlib.md5((ROOT / name).read_bytes()).hexdigest() for name in files}
    assert before == after
