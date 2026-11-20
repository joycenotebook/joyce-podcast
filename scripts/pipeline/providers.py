"""TTS 提供者。彩排只用 MockProvider。ListenHub 必须同时满足确认闸门和显式开关。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .audio import synthesize_mock
from .config import API_BASE, allow_listenhub, confirmed, listenhub_api_key, listenhub_client_id
from .preprocess import Segment


class TTSProvider:
    name = "base"

    def synthesize(self, segments: list[Segment], work: Path) -> list[Path]:
        raise NotImplementedError


class MockProvider(TTSProvider):
    """短提示音。不联网。"""

    name = "mock"

    def synthesize(self, segments: list[Segment], work: Path) -> list[Path]:
        body = [s for s in segments if s.role != "opening" and s.text.strip()]
        if not body:
            raise RuntimeError("预处理后没有可朗读的正文")
        return synthesize_mock(body, work)


class ListenHubProvider(TTSProvider):
    """mode=direct，不走 deep 重写。本仓库的彩排路径不会实例化它。"""

    name = "listenhub"

    def __init__(self, speaker_id: str) -> None:
        self.speaker_id = speaker_id

    def synthesize(self, segments: list[Segment], work: Path) -> list[Path]:
        if not confirmed():
            raise RuntimeError("未确认脚本，拒绝调用 ListenHub。需要 CONFIRMED=yes 或「确认上线」。")
        if not allow_listenhub():
            raise RuntimeError("ALLOW_LISTENHUB 未打开。默认拒绝任何付费 TTS。")
        key = listenhub_api_key()
        client = listenhub_client_id()
        if not key or not client:
            raise RuntimeError("缺少 LISTENHUB_API_KEY 或 LISTENHUB_CLIENT_ID")
        self._check_speaker(key, client)
        work.mkdir(parents=True, exist_ok=True)
        body = [s for s in segments if s.role != "opening" and s.text.strip()]
        paths: list[Path] = []
        meta = []
        for i, seg in enumerate(body):
            if len(seg.text) > 10000:
                raise RuntimeError(f"第 {i+1} 段超过 10000 字，ListenHub 不收")
            url = self._render(key, client, seg.text)
            path = work / f"part-{i:02d}.mp3"
            urllib.request.urlretrieve(url, path)
            paths.append(path)
            meta.append({"file": path.name, "lang": seg.lang, "role": seg.role, "chars": len(seg.text)})
        (work / "segments.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return paths

    def _request(self, key: str, client: str, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{API_BASE}/{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "x-marswave-client-id": client,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ListenHub HTTP {exc.code}: {detail}") from exc

    def _check_speaker(self, key: str, client: str) -> None:
        payload = self._request(key, client, "GET", "speakers/list?language=zh")
        items = (payload.get("data") or {}).get("items") or payload.get("items") or []
        if not any(item.get("speakerId") == self.speaker_id for item in items):
            raise RuntimeError(f"音色对不上：{self.speaker_id}")

    def _render(self, key: str, client: str, text: str) -> str:
        created = self._request(
            key,
            client,
            "POST",
            "flow-speech/episodes",
            {
                "sources": [{"type": "text", "content": text}],
                "speakers": [{"speakerId": self.speaker_id}],
                "language": "zh",
                "mode": "direct",
            },
        )
        episode_id = (created.get("data") or {}).get("episodeId") or created.get("episodeId")
        if not episode_id:
            raise RuntimeError("ListenHub 未返回 episodeId")
        for _ in range(90):
            status = self._request(key, client, "GET", f"flow-speech/episodes/{episode_id}")
            data = status.get("data") or status
            state = data.get("processStatus") or "unknown"
            if state in {"success", "completed"}:
                audio_url = data.get("audioUrl") or ""
                if not audio_url:
                    raise RuntimeError("ListenHub 完成但没有 audioUrl")
                return audio_url
            if state in {"failed", "error"}:
                raise RuntimeError("ListenHub 生成失败")
            time.sleep(10)
        raise RuntimeError("ListenHub 超时")


def provider_for(mode: str, speaker_id: str) -> TTSProvider:
    if mode != "live":
        return MockProvider()
    return ListenHubProvider(speaker_id)
