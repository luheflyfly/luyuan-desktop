"""提醒与调度观测端点 —— "它到底说了什么、为什么说、什么时候说的"。

这三个问题的答案在这里，不在日志里。没有这几个端点，路远主动开口这件事
就是黑盒，用户只能凭感觉判断"它是不是又在瞎提醒"。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def _bus(request: Request):
    return getattr(request.app.state, "reminders", None)


def _scheduler(request: Request):
    return getattr(request.app.state, "scheduler", None)


@router.get("/api/reminders")
def reminders(request: Request, limit: int = 50):
    bus = _bus(request)
    if bus is None:
        return {"pending": [], "recent": [], "note": "提醒服务未启动（用 --jobs 开启）"}
    return {"pending": bus.pending(), "recent": bus.recent(limit)}


@router.post("/api/reminders/{rid}/ack")
def ack(request: Request, rid: str):
    bus = _bus(request)
    return {"ok": bool(bus and bus.ack(rid))}


@router.post("/api/reminders/ack_all")
def ack_all(request: Request):
    bus = _bus(request)
    return {"ok": True, "n": bus.ack_all() if bus else 0}


@router.get("/api/jobs")
def jobs(request: Request):
    sch = _scheduler(request)
    if sch is None:
        return {"running": False, "jobs": []}
    return {"running": True, **sch.status()}
