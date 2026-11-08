"""课表路由（`/api/courses`）+ 提醒/调度观测端点。

`/api/courses` 的字段与旧实现一致：`{courses, today, next, week}`，
这样前端和手机端一行都不用改。
"""
from __future__ import annotations

from fastapi import APIRouter

from luyuan.core import courses as courses_repo

router = APIRouter()


@router.get("/api/courses")
def list_courses():
    repo = courses_repo.repo()
    return {
        "courses": repo.all_sorted(),
        "today": repo.today(),
        "next": repo.next_class(),
        "week": repo.week(),
    }


@router.get("/api/courses/next")
def next_class():
    repo = courses_repo.repo()
    return {"next": repo.next_class(), "brief": repo.brief_next()}


@router.get("/api/courses/soon")
def due_soon(window: int = 15):
    repo = courses_repo.repo()
    return {"items": repo.due_soon(window_minutes=window)}
