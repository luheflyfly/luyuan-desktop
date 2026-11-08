"""记账路由。字段照抄旧 `/api/expenses`：`{month, items, stats}`。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from luyuan.core.expenses import repo

router = APIRouter()


class ExpenseIn(BaseModel):
    amount: float
    item: str = ""
    category: str | None = None
    spent_at: str | None = None
    source: str = "manual"
    image: str | None = None


class ExpensePatch(BaseModel):
    amount: float | None = None
    item: str | None = None
    category: str | None = None
    spent_at: str | None = None


@router.get("/api/expenses")
def list_expenses(month: str = ""):
    m = month or None
    r = repo()
    return {"month": m or r.month_stats()["month"],
            "items": r.list_month(m),
            "stats": r.month_stats(m)}


@router.post("/api/expenses")
def add_expense(body: ExpenseIn):
    e = repo().add(body.amount, body.item, spent_at=body.spent_at,
                   category=body.category, source=body.source, image=body.image)
    if not e:
        raise HTTPException(400, "金额不合法")
    return e


@router.put("/api/expenses/{eid}")
def update_expense(eid: str, body: ExpensePatch):
    e = repo().edit(eid, body.model_dump(exclude_none=True))
    if not e:
        raise HTTPException(404, "记录不存在")
    return e


@router.delete("/api/expenses/{eid}")
def delete_expense(eid: str):
    if not repo().remove(eid):
        raise HTTPException(404, "记录不存在")
    return {"ok": True}
