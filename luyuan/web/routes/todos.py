"""待办路由。路径与字段照抄旧 `/api/todos*`（手机端与前端零改动）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from luyuan.core.todos import repo

router = APIRouter()


class TodoFields(BaseModel):
    topic: str | None = None
    due_at: str | None = None
    when_text: str | None = None


@router.get("/api/todos")
def overview():
    return repo().overview()


@router.post("/api/todos/{tid}/done")
def mark_done(tid: str):
    t = repo().mark_done(tid)
    if not t:
        raise HTTPException(404, "待办不存在")
    return t


@router.post("/api/todos/{tid}/undone")
def unmark(tid: str):
    t = repo().unmark(tid)
    if not t:
        raise HTTPException(404, "待办不存在")
    return t


@router.post("/api/todos/{tid}/update")
def update_fields(tid: str, body: TodoFields):
    """只接受 topic / due_at / when_text（智能体专用白名单，done/deleted 永远拿不到）。"""
    t = repo().update_fields(tid, body.model_dump(exclude_none=True))
    if not t:
        raise HTTPException(404, "待办不存在或字段不可改")
    return t


@router.post("/api/todos/{tid}/discard")
def discard(tid: str):
    if not repo().discard(tid):
        raise HTTPException(404, "待办不存在")
    return {"ok": True}
