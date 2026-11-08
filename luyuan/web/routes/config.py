"""配置路由（设置页用）。

⚠️ 与旧 `/api/config` 的**有意差异**：旧实现把 config.json 原文整份吐给前端，
包括 `askaway.api_key` 明文 —— 任何能访问 8777 的人都能拿走 key。
新实现只回**掩码**（`sk-****6e13`），并且写回时遇到掩码值就保留原值不动，
所以设置页照常能看、能改其它项，而 key 永远不出本机。
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from luyuan import paths
from luyuan.config import Config
from luyuan.logs import get

router = APIRouter()
log = get("config")

SECRET_HINTS = ("api_key", "apikey", "token", "secret", "password")
MASK = "****"


def _mask(value: str) -> str:
    """sk-REDACTED -> sk-****6e13"""
    v = str(value or "")
    if len(v) <= 8:
        return MASK
    head = v[:3] if v.startswith("sk-") else ""
    return f"{head}{MASK}{v[-4:]}"


def _scrub(node, path: str = ""):
    if isinstance(node, dict):
        return {k: (_mask(v) if (isinstance(v, str) and any(h in k.lower() for h in SECRET_HINTS))
                    else _scrub(v, f"{path}.{k}"))
                for k, v in node.items()}
    if isinstance(node, list):
        return [_scrub(v, path) for v in node]
    return node


def _restore_masked(old: dict, new: dict) -> dict:
    """写回时：新值看起来是掩码（含 ****）→ 沿用旧值，避免把 key 写成星号。"""
    out = dict(new or {})
    for k, v in list(out.items()):
        if isinstance(v, dict) and isinstance(old.get(k), dict):
            out[k] = _restore_masked(old[k], v)
        elif isinstance(v, str) and MASK in v and isinstance(old.get(k), str):
            out[k] = old[k]
    return out


class ConfigIn(BaseModel):
    config: dict


@router.get("/api/config")
def read_config():
    cfg = Config.load()
    return {"ok": True, "config": _scrub(cfg.raw), "masked": True}


@router.put("/api/config")
def write_config(body: ConfigIn):
    p: Path = paths.CONFIG_FILE
    try:
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        old = {}
    merged = _restore_masked(old, body.config)
    cfg = Config(merged)
    try:
        p.write_text(json.dumps(cfg.raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"写配置失败：{e}") from e
    log.info("config 已更新（密钥项保持原值）")
    return {"ok": True, "config": _scrub(cfg.raw), "masked": True}
