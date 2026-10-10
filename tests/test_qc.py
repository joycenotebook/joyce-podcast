from pathlib import Path

from scripts.pipeline.preprocess import PreprocessResult, Segment, filler_hits, number_violations, preprocess, script_structure_issues
from scripts.pipeline.qc import check_catalog, check_script

ROOT = Path(__file__).resolve().parents[1]


def test_gate_fails_each_script_rule():
    opening = "大家好，欢迎回来，发声。\n这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。\n\n"
    subscribe = "\n\n如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。\n"
    cases = {
        "missing_opening": "今天没有开场。" + subscribe,
        "missing_subscribe": opening + "今天没有订阅句。",
        "number_format": opening + "那是两千零二六年的事。" + subscribe,
        "banned_phrase": opening + "这里值得玩味。" + subscribe,
        "unattached_heading": opening + "### 孤标题\n\nThis is only English.\n" + subscribe,
    }
    for code, md in cases.items():
        _, report = check_script(md, title="普通标题")
        assert not report.ok(), code
        assert any(issue.code == code for issue in report.errors), (code, [i.code for i in report.errors])


def test_leftover_filler_fails_even_if_preprocess_would_have_cleaned_it():
    result = PreprocessResult(
        title="标题",
        segments=[
            Segment("大家好，欢迎回来，发声。这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。", "zh", "opening"),
            Segment("You know, the constraint is still here.", "en"),
            Segment("如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。", "zh"),
        ],
        spoken_text="x",
    )
    result.spoken_text = "\n".join(seg.text for seg in result.segments)
    issues = script_structure_issues(result)
    assert any(item.startswith("英文口头禅") for item in issues)
    assert filler_hits("You know, the constraint is still here.")
    assert number_violations("预算 $1美元")
    cleaned = preprocess(
        "大家好，欢迎回来，发声。\n这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。\n\n"
        "You know, we feel like the constraint is real.\n\n"
        "预算是 $1美元。\n\n"
        "如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。\n"
    )
    assert filler_hits(next(seg.text for seg in cleaned.segments if seg.lang == "en")) == []
    assert all("数字格式" not in item for item in script_structure_issues(cleaned))


def test_banned_public_title():
    md = (
        "大家好，欢迎回来，发声。\n"
        "这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。\n\n"
        "正文。\n\n"
        "如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。\n"
    )
    _, report = check_script(md, title="十八问重构这一期")
    assert any(issue.code == "banned_phrase" for issue in report.errors)


def test_clean_script_passes():
    md = (ROOT / "pipeline/samples/rehearsal-doordash/script.md").read_text(encoding="utf-8")
    result, report = check_script(md, title="[彩排] 十年后骑手会变多还是变少")
    assert report.ok(), [issue.message for issue in report.errors]
    assert result.segments[0].role == "opening"
    assert "审核" not in result.spoken_text


def test_live_catalog_reports_known_mismatches_without_editing():
    before = (ROOT / "episodes.json").read_bytes()
    report = check_catalog(ROOT)
    after = (ROOT / "episodes.json").read_bytes()
    assert before == after
    codes = {(issue.target, issue.code) for issue in report.errors}
    assert ("ep-010", "size_mismatch") in codes
    assert ("ep-010", "duration_mismatch") in codes
    assert ("ep-014", "size_mismatch") in codes
    assert ("ep-014", "duration_mismatch") in codes
    assert ("ep-014", "page_file_mismatch") in codes
    assert any("ep-014-v3.mp3" in issue.message for issue in report.errors)
    # 公开编号和文件号不是同一套数字，只提示，不挡历史期。
    assert any(issue.code == "public_vs_file_id" for issue in report.issues)
    assert not any(issue.code == "public_vs_file_id" and issue.level == "error" for issue in report.issues)


def test_no_hardcoded_listenhub_client_id():
    text = (ROOT / "scripts/publish_episode.py").read_text(encoding="utf-8")
    assert "PJBkELS1o" not in text
    assert "LISTENHUB_CLIENT_ID" in text
    for path in (ROOT / "scripts/pipeline").rglob("*.py"):
        assert "PJBkELS1o" not in path.read_text(encoding="utf-8")


def test_preprocess_does_not_invent_subscribe_line():
    result = preprocess("大家好，欢迎回来，发声。\n这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。\n\n正文。\n")
    assert "可以订阅节目" not in result.spoken_text
