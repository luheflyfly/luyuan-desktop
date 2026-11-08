"""日记路由。字段照抄旧 `/api/diary*`：`{note, streak}` / `{notes}`。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from luyuan.core.diary import book

router = APIRouter()


class DiaryIn(BaseModel):
    text: str = ""
    images: list[str] | None = None


@router.get("/api/diary/today")
def today():
    return book().today()


@router.get("/api/diary/recent")
def recent(limit: int = 30):
    return {"notes": book().recent(limit)}


@router.post("/api/diary")
def save(body: DiaryIn):
    n = book().save(body.text, images=body.images)
    if not n:
        raise HTTPException(400, "内容为空")
    return {"note": n, "streak": book().streak()}
