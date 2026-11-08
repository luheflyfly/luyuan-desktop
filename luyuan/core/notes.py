"""笔记域（kind 为空的记录，历史数据都在这）。

语义沿用 SYNC_FORMAT：`kind` 字段为空才算笔记；todo/expense/course/contact/report
即使带 text 也不进笔记列表（旧 store 靠 `not n.get("kind")` 挡，这里由基类统一挡）。
"""
from __future__ import annotations

from luyuan.core.store import JsonRepo, iso_now


class NotesRepo(JsonRepo):
    kind = None  # 无 kind 字段 = 笔记

    def all(self) -> list[dict]:
        """无 text 的记录不算笔记 —— 旧 store.py:83 就是这条规则（32 个文件因此不进列表）。"""
        return [r for r in super().all() if str(r.get("text") or "").strip()]

    def all_with_text_any(self) -> list[dict]:
        """含无 text 的原始全集（迁移/体检用，不对外）。"""
        return super().all()

    def add(self, text: str, source: str = "manual", tags: list[str] | None = None,
            extra: dict | None = None) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None
        rec = {
            "created_at": iso_now(),
            "text": text,
            "source": source,
            "tags": list(tags or []),
            "device": "pc",
            "schema": 1,
        }
        if extra:
            rec.update(extra)
        return self.save(rec)

    def list_page(self, limit: int | None = None, reverse: bool = True,
                  tag: str | None = None, trash: bool = False,
                  ondate: str | None = None) -> list[dict]:
        rows = self.all()
        if reverse:
            pass  # all() 已按 created_at 倒序
        out = []
        for n in rows:
            if bool(n.get("deleted")) != trash:
                continue
            if tag and tag not in (n.get("tags") or []):
                continue
            if ondate and not str(n.get("created_at") or "").startswith(ondate):
                continue
            out.append(n)
        return out[:limit] if limit else out

    def append_block(self, rid: str, block: str, sep: str = "\n\n---- ✨ 整理 ----\n\n") -> dict | None:
        """把「✨整理」块追加到正文后；已有则替换（原文始终保留）。"""
        n = self.get(rid)
        if not n:
            return None
        text = str(n.get("text") or "")
        if sep in text:
            text = text.split(sep)[0].rstrip()
        return self.update(rid, text=text + block)


_repo: NotesRepo | None = None


def repo() -> NotesRepo:
    """进程内单例（目录可在测试里注入）。"""
    global _repo
    if _repo is None:
        _repo = NotesRepo()
    return _repo
