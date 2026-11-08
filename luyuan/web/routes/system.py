"""系统域路由：健康、状态、计数。

约定：`/api/health` 必须能**不看日志**就回答三个问题 —— 活着没、什么版本、只读还是能写。
"""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter

from luyuan import __version__, paths
from luyuan.core import contacts as contacts_repo
from luyuan.core.notes import repo as notes_repo
from luyuan.core.store import repo_for

router = APIRouter()

_STARTED = time.time()

DIARY_TAG = "日记"


@router.get("/api/health")
def health():
    return {
        "ok": True,
        "time": time.time(),
        "ver": __version__,
        "role": "brain",
        "uptime": round(time.time() - _STARTED, 1),
        "data": str(paths.DATA),
    }


@router.get("/api/status")
def status():
    """录音/转写状态。骨架阶段固定 idle，IO 层接入后由 io.audio 提供。"""
    return {"state": "idle", "text": "", "ts": 0.0, "error": ""}


@router.get("/api/counts")
def counts():
    """各域条数（面板左栏徽章）。字段名与旧 `/api/counts` 完全一致。

    旧语义（server.py:165）照抄，一处不改：
      note    = 笔记总数 - 带「日记」标签的
      diary   = 带「日记」标签的（日记不是独立 kind，是 tag！）
      expense = **当月**笔数（不是全部）
      contact = notes/contacts/ 子目录条数
    """
    month = datetime.now().strftime("%Y-%m")
    notes = notes_repo()
    rows = notes.visible()
    diary = sum(1 for n in rows if DIARY_TAG in (n.get("tags") or []))
    expenses = [e for e in repo_for("expense").visible()
                if str(e.get("spent_at") or e.get("created_at") or "").startswith(month)]
    return {
        "note": len(rows) - diary,
        "diary": diary,
        "trash": len(notes.trash()),
        "expense": len(expenses),
        "course": len(repo_for("course").visible()),
        "contact": len(contacts_repo.repo().visible()),
        "msg_todo": len(repo_for("todo").visible()),
        "readlater_pending": 0,
        "readlater_failed": 0,
    }
