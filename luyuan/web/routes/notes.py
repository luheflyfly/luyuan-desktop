"""笔记域路由。**字段与语义逐条照抄旧 `/api/notes`**（前端与手机零改动）。

影子阶段（REFACTOR.md §4 P2）的目标是"行为等价"，所以这里刻意保留旧接口的
历史语义 —— 包括那些不优雅的地方（`trash: int` 而不是 bool、日记靠 tag 不靠 kind、
返回体没有 count）。要改语义，等新前端上线（P5）时一起改，别在迁移期偷改。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from luyuan.core.notes import repo

router = APIRouter()

DIARY_TAG = "日记"


class NoteIn(BaseModel):
    text: str = ""
    source: str = "manual"
    tags: list[str] | None = None


class NotePatch(BaseModel):
    text: str


def _public(n: dict) -> dict:
    """对外只给契约字段（去掉内部下划线键）。"""
    return {k: v for k, v in n.items() if not k.startswith("_")}


def _filter_diary(rows: list[dict], diary: int, tag: str = "") -> list[dict]:
    if tag:
        return [n for n in rows if tag in (n.get("tags") or [])]
    return [n for n in rows
            if (DIARY_TAG in (n.get("tags") or [])) == bool(diary)]


@router.get("/api/notes")
def list_notes(limit: int = 200, tag: str = "", trash: int = 0,
               ondate: str = "", diary: int = 0):
    # 旧实现先多取 50 条再过滤，这里保持同样的"够用就够"的取法
    rows = repo().list_page(limit=limit + 50, trash=bool(trash),
                            tag=tag or None, ondate=ondate or None)
    rows = _filter_diary(rows, diary, tag)
    return {"notes": [_public(n) for n in rows[:limit]]}


@router.get("/api/notes/{nid}")
def get_note(nid: str):
    n = repo().get(nid)
    if not n:
        raise HTTPException(404, "笔记不存在")
    return _public(n)


@router.get("/api/search")
def search(q: str = "", tag: str = "", diary: int = 0, limit: int = 200):
    rows = repo().search(q) if q else repo().visible()
    rows = _filter_diary(rows, diary, tag)
    # 语义兜底（semsearch）留到 P4 接入 ai 层时再挂，先在报告里标 TODO
    return {"notes": [_public(n) for n in rows[:limit]]}


@router.get("/api/note_dates")
def note_dates():
    return {"dates": repo().dates()}


# ── 写：只读实例由 create_app 的中间件统一拦掉，这里按正常语义实现 ──────
@router.post("/api/notes")
def create_note(body: NoteIn):
    n = repo().add(body.text, source=body.source, tags=body.tags)
    if not n:
        raise HTTPException(400, "内容为空")
    return _public(n)


@router.put("/api/notes/{nid}")
def update_note(nid: str, body: NotePatch):
    n = repo().update(nid, text=body.text.strip())
    if not n:
        raise HTTPException(404, "笔记不存在")
    return _public(n)


@router.delete("/api/notes/{nid}")
def delete_note(nid: str):
    if not repo().soft_delete(nid):
        raise HTTPException(404, "笔记不存在")
    return {"ok": True}
