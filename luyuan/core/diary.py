"""日记（负一屏）——**不是独立 kind，是带「日记」标签的笔记**。

历史语义（照抄，别"优化"）：
  * 存的是普通笔记 + `tags:["日记"]`
  * 判断"哪天写没写"看 `created_at[:10]`
  * 连续天数：今天还没写就从昨天起算（不算断）
  * 一天只有一篇：再写就覆盖当天那篇（`update`，不是新增）
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from luyuan.core.notes import NotesRepo, repo as notes_repo

TAG = "日记"


class DiaryBook:
    """基于笔记仓储的日记视图。不持有数据，只做筛选与聚合。"""

    def __init__(self, notes: NotesRepo | None = None):
        self._notes = notes or notes_repo()

    # ── 读 ─────────────────────────────────────────────────
    def entries(self, limit: int = 500) -> list[dict]:
        return [n for n in self._notes.all() if TAG in (n.get("tags") or [])][:limit]

    def days(self) -> set[str]:
        return {str(n.get("created_at") or "")[:10] for n in self.entries()}

    def streak(self) -> int:
        days = self.days()
        d = date.today()
        if d.strftime("%Y-%m-%d") not in days:
            d -= timedelta(days=1)  # 今天还没写：从昨天起算，不算断
        n = 0
        while d.strftime("%Y-%m-%d") in days:
            n += 1
            d -= timedelta(days=1)
        return n

    def today(self) -> dict:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        rows = [n for n in self.entries(limit=50)
                if str(n.get("created_at") or "").startswith(today)]
        return {"note": rows[0] if rows else None, "streak": self.streak()}

    def recent(self, limit: int = 30) -> list[dict]:
        return self.entries(limit=limit)

    # ── 写 ─────────────────────────────────────────────────
    def save(self, text: str, images: list[str] | None = None) -> dict | None:
        """写今天的日记：已有则覆盖正文，没有则新建（一天一篇）。"""
        text = (text or "").strip()
        if not text:
            return None
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        rows = [n for n in self.entries(limit=50)
                if str(n.get("created_at") or "").startswith(today)]
        if rows:
            note = self._notes.update(rows[0]["id"], text=text)
        else:
            note = self._notes.add(text, source="diary", tags=[TAG])
        if note and isinstance(images, list):
            keep = [str(i) for i in images if str(i).startswith("images/")]
            note = self._notes.update(note["id"],
                                      images=keep or None)
        return note


_book: DiaryBook | None = None


def book() -> DiaryBook:
    global _book
    if _book is None:
        _book = DiaryBook()
    return _book
