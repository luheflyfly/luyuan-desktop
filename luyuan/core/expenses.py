"""记账域（`kind:"expense"`，SYNC_FORMAT §10.2）。

两个容易踩的历史语义：
  * **"本月"按 `spent_at` 算，不是 `created_at`** —— 导入的旧账单 spent_at 是过去某天，
    用 created_at 会把三个月前的账算进这个月。
  * 手机端记账产出的 `id` 是完整 UUID，文件名只取前 8 位；`add()` 也照这个来，
    否则手机写回的定位键对不上，会生成重复文件。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from luyuan.core.store import JsonRepo, iso_now


class ExpensesRepo(JsonRepo):
    kind = "expense"

    # ── 读 ─────────────────────────────────────────────────
    def list_month(self, month: str | None = None) -> list[dict]:
        """某月消费（'YYYY-MM'，缺省当月），按 spent_at 倒序。"""
        month = month or datetime.now().strftime("%Y-%m")
        rows = [e for e in self.visible()
                if str(e.get("spent_at") or "").startswith(month)]
        rows.sort(key=lambda e: str(e.get("spent_at") or ""), reverse=True)
        return rows

    def month_stats(self, month: str | None = None) -> dict:
        month = month or datetime.now().strftime("%Y-%m")
        items = self.list_month(month)
        by_cat: dict[str, float] = {}
        for e in items:
            c = str(e.get("category") or "其他")
            by_cat[c] = round(by_cat.get(c, 0) + float(e.get("amount") or 0), 2)
        total = round(sum(float(e.get("amount") or 0) for e in items), 2)
        cats = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)
        return {"month": month, "total": total, "count": len(items),
                "categories": [{"category": c, "amount": a} for c, a in cats]}

    # ── 写 ─────────────────────────────────────────────────
    def add(self, amount, item: str, spent_at: str | None = None,
            category: str | None = None, source: str = "manual",
            image: str | None = None) -> dict | None:
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError):
            return None
        now = iso_now()
        rec = {
            "kind": "expense",
            "id": str(uuid.uuid4()),
            "schema": 2,
            "device": "pc",
            "deleted": False,
            "amount": amount,
            "item": (item or "").strip() or "（未命名）",
            "category": (category or "其他").strip() or "其他",
            "spent_at": spent_at or now,
            "source": source,
            "tags": ["记账"],
            "created_at": now,
            "updated_at": now,
        }
        if image:
            rec["image"] = image
        return self.save(rec)

    def edit(self, eid: str, fields: dict) -> dict | None:
        allow = {k: fields[k] for k in ("amount", "item", "category", "spent_at")
                 if k in (fields or {})}
        if not allow:
            return None
        return self.update(eid, **allow)

    def remove(self, eid: str) -> bool:
        """物理删（与旧 expenses.delete / 手机端一致，删前要有确认卡）。"""
        return self.purge(eid)


_repo: ExpensesRepo | None = None


def repo() -> ExpensesRepo:
    global _repo
    if _repo is None:
        _repo = ExpensesRepo()
    return _repo
