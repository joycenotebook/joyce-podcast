import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.pipeline.providers import ListenHubProvider
from scripts.pipeline.publish import run_job

ROOT = Path(__file__).resolve().parents[1]
TRACKED = [
    "episodes.json",
    "feed.xml",
    "index.html",
    "ep-010.html",
    "ep-014.html",
    "scripts/publish_episode.py",
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sample_dry_run_writes_only_the_output_dir(tmp_path: Path):
    before = {name: _digest(ROOT / name) for name in TRACKED}
    out = tmp_path / "dry-run"
    summary = run_job(ROOT / "pipeline/samples/rehearsal-doordash", out, "dry-run")
    after = {name: _digest(ROOT / name) for name in TRACKED}
    assert before == after
    assert summary["result"] == "dry-run"
    assert summary["provider"] == "mock"
    assert summary["listenhub_called"] is False
    assert summary["committed"] is False
    assert summary["id"] == "ep-900"
    audio = out / "audio" / "ep-900.mp3"
    assert audio.exists()
    assert audio.stat().st_size > 1000
    site = out / "site"
    feed = (site / "feed.xml").read_text(encoding="utf-8")
    assert "ep-900.mp3" in feed
    assert "[彩排] 十年后骑手会变多还是变少" in feed
    assert "发声 Taste, Out loud" in feed
    page = (site / "ep-900.html").read_text(encoding="utf-8")
    assert 'src="./audio/ep-900.mp3"' in page
    catalog = json.loads((site / "episodes.json").read_text(encoding="utf-8"))
    row = next(ep for ep in catalog["episodes"] if ep["id"] == "ep-900")
    assert row["size_bytes"] == audio.stat().st_size
    assert "瑜伽课后" not in catalog["podcast"]["title"]
    # 真 feed 没有被彩排稿污染
    assert "ep-900" not in (ROOT / "feed.xml").read_text(encoding="utf-8")


def test_refuses_script_outside_the_repo(tmp_path: Path):
    outside = tmp_path / "script.md"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_job(outside, tmp_path / "out", "dry-run")


def test_live_mode_refuses_without_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CONFIRMED", raising=False)
    monkeypatch.delenv("ALLOW_LISTENHUB", raising=False)
    with pytest.raises(SystemExit):
        run_job(ROOT / "pipeline/samples/rehearsal-doordash", tmp_path / "live", "live")


def test_listenhub_provider_does_not_open_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def explode(*_args, **_kwargs):
        raise AssertionError("不应该访问网络")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    monkeypatch.setattr("urllib.request.urlretrieve", explode)
    provider = ListenHubProvider("voice-clone-test")
    monkeypatch.delenv("CONFIRMED", raising=False)
    monkeypatch.delenv("ALLOW_LISTENHUB", raising=False)
    with pytest.raises(RuntimeError, match="未确认"):
        provider.synthesize([], tmp_path)
    monkeypatch.setenv("CONFIRMED", "yes")
    with pytest.raises(RuntimeError, match="ALLOW_LISTENHUB"):
        provider.synthesize([], tmp_path)
    monkeypatch.setenv("ALLOW_LISTENHUB", "yes")
    monkeypatch.delenv("LISTENHUB_API_KEY", raising=False)
    monkeypatch.delenv("LISTENHUB_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="LISTENHUB_API_KEY"):
        provider.synthesize([], tmp_path)
    assert os.environ.get("LISTENHUB_API_KEY", "") == ""
