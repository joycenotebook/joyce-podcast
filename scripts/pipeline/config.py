"""环境变量与确认闸门。密钥只从环境读取，仓库里不放值。"""
from __future__ import annotations

import os

SHOW_TITLE = "发声 Taste, Out loud"
OPENING_LINES = (
    "大家好，欢迎回来，发声。",
    "这里和希望低阻力输入、高质感表达的朋友，一起打磨输入输出系统。",
)
SUBSCRIBE_LINE = (
    "如果你希望继续收听到我筛选的全球AI商业访谈和课程，把表达练成肌肉记忆，可以订阅节目。"
)
DEFAULT_SPEAKER = "voice-clone-6a89685731af54c9011c09c7"
CONFIRMED_VALUES = {"yes", "true", "1", "confirmed", "确认上线"}
API_BASE = "https://api.marswave.ai/openapi/v1"


def env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def confirmed(value: str | None = None) -> bool:
    raw = env("CONFIRMED") if value is None else (value or "").strip()
    return raw.lower() in CONFIRMED_VALUES or raw == "确认上线"


def listenhub_api_key() -> str:
    return env("LISTENHUB_API_KEY")


def listenhub_client_id() -> str:
    return env("LISTENHUB_CLIENT_ID")


def allow_listenhub() -> bool:
    return env("ALLOW_LISTENHUB").lower() in {"yes", "true", "1"}
