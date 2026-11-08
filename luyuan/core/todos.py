"""待办域（`kind:"todo"`，SYNC_FORMAT §10.4）。**手机端产出，PC 端读取 + 回写**。

契约要点（改之前先看）：
  * 手机端 `MessageNotificationListener` 从微信通知里抽出来，落 `todo_<id8>.json`
  * PC 只能改 `done / done_at / topic / due_at / when_text / updated_at`
    —— `done/deleted` 以外的东西一律不许动，尤其不许整文件重写
    （手机写回是整文件覆盖，PC 也跟着整写就会互相抹字段）
  * `discard` 是**物理删**（与手机端「✗ 不要」行为一致），所以调用前必须有确认
"""
from __future__ import annotations

from datetime import datetime

from luyuan.core.store import JsonRepo, iso_now

# 路远远整理智能体唯一能碰的字段（vc127 定的白名单，done/deleted 永不入内）
AGENT_EDITABLE = ("topic", "due_at", "when_text")


class TodosRepo(JsonRepo):
    kind = "todo"

    # ── 读 ─────────────────────────────────────────────────
    def list_todos(self, include_done: bool = False) -> list[dict]:
        """未完成（新在前）；include_done=True 连已完成一起给。软删的永远不出现。"""
        out = []
        for t in self.all():
            if t.get("deleted"):
                continue
            if not include_done and t.get("done"):
                continue
            out.append(t)
        return out

    def overview(self) -> dict:
        """今日待办区：未完成全部 + 今天完成的。字段名与旧 `/api/todos` 一致。"""
        today = datetime.now().strftime("%Y-%m-%d")
        undone, done_today = [], []
        for t in self.list_todos(include_done=True):
            if t.get("done"):
                if str(t.get("done_at") or "").startswith(today):
                    done_today.append(t)
            else:
                undone.append(t)
        return {"todos": undone, "done_today": done_today, "count": len(undone)}

    # ── 写 ─────────────────────────────────────────────────
    def mark_done(self, tid: str) -> dict | None:
        return self.update(tid, done=True, done_at=iso_now())

    def unmark(self, tid: str) -> dict | None:
        return self.update(tid, done=False, done_at=None)

    def update_fields(self, tid: str, fields: dict) -> dict | None:
        """只允许改 AGENT_EDITABLE 里的字段；值非字符串一律存空串（旧实现的纪律）。"""
        allow = {k: (v if isinstance(v, str) else "") for k, v in (fields or {}).items()
                 if k in AGENT_EDITABLE}
        if not allow:
            return None
        return self.update(tid, **allow)

    def discard(self, tid: str) -> bool:
        """丢弃 = 物理删（与手机端 ✗ 一致）。"""
        return self.purge(tid)


_repo: TodosRepo | None = None


def repo() -> TodosRepo:
    global _repo
    if _repo is None:
        _repo = TodosRepo()
    return _repo
