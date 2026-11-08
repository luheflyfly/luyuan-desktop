"""配置：config.json → 一个对象，缺项永不 KeyError。

旧代码的做法是满世界 `_load_cfg().get("stt", {}).get("vad_dir", ...)`，
路径一深就写成 `cfg.get("a", {}).get("b", {})` 然后把 KeyError 埋进去。
这里收口：一个 `Config` 对象，点号取值，缺了就回默认值，并且**只读一次**。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from luyuan import paths

_DEFAULTS: dict[str, Any] = {
    "samplerate": 16000,
    "channels": 1,
    "notes_dir": "data/notes",
    "server": {"host": "127.0.0.1", "port": 8777},
    "hotkey": {"enabled": True, "combo": "<f10>"},
    "capture": {"max_seconds": 12, "silence_seconds": 1.2, "min_seconds": 0.6},
    "stt": {"sensevoice_dir": "models/SenseVoiceSmall", "vad_dir": "models/VAD",
            "device": "cpu", "semsearch": {"enabled": True}},
    "ai": {"endpoint": "http://localhost:11434", "small": "qwen3.5:2b", "big": "qwen3.5:4b",
           "timeout": 60, "think": False},
    "backup": {"enabled": True, "keep": 3},
    "trash_autopurge": {"enabled": True, "days": 30},
    "diary": {"enabled": True, "remind_time": "21:30"},
    "privacy": {"allow_private_outbound": False, "allowed_sources": []},
    # 天气：只填 city 就够；给了经纬度就不会去查城市名（更准、更快）
    "weather": {"city": "长沙", "latitude": None, "longitude": None},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """只读配置视图。`cfg.get("stt.device")` / `cfg.server_port` 两种取法都行。"""

    def __init__(self, raw: dict | None = None, source: Path | None = None):
        self.raw: dict = _deep_merge(_DEFAULTS, raw or {})
        self.source = source

    # ── 构造 ───────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        p = path or paths.CONFIG_FILE
        raw: dict = {}
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001 — 坏配置不能拖死启动
                import logging
                logging.getLogger("luyuan").warning("config.json 解析失败，用默认值：%s", e)
        return cls(raw, source=p)

    # ── 取值 ───────────────────────────────────────────────
    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # ── 常用快捷属性 ───────────────────────────────────────
    @property
    def host(self) -> str:
        return str(self.get("server.host", "127.0.0.1"))

    @property
    def port(self) -> int:
        return int(self.get("server.port", 8777))

    @property
    def notes_dir(self) -> Path:
        return paths.ROOT / str(self.get("notes_dir", "data/notes"))

    @property
    def ai_endpoint(self) -> str:
        return str(self.get("ai.endpoint") or "http://localhost:11434").rstrip("/")

    @property
    def ai_small(self) -> str:
        return str(self.get("ai.small") or "qwen3.5:2b")

    @property
    def ai_big(self) -> str:
        return str(self.get("ai.big") or "qwen3.5:4b")

    @property
    def ai_timeout(self) -> int:
        return int(self.get("ai.timeout") or 60)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Config {self.source} host={self.host} port={self.port}>"
