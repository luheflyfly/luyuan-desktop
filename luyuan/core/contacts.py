"""人脉域：`data/notes/contacts/*.json`（**子目录**，不是笔记目录顶层）。

⚠️ 关键约束（2026-10-30 审计确认）：手机 App 找实体只扫同步根目录顶层，不递归；
人脉是唯一的子目录域，App 有专门的 contacts 扫描。重构时**不得把人脉搬出
notes/contacts/**，也不得把其它实体挪进子目录 —— 否则手机上会出现"笔记正常、
待办/汇报全空"的半瞎故障。
"""
from __future__ import annotations

from luyuan import paths
from luyuan.core.store import JsonRepo, iso_now


class ContactsRepo(JsonRepo):
    kind = "contact"       # 新文件写入 kind="contact"
    strict_kind = False    # ⚠️ 老数据里 30 个文件有 2 个缺 kind 字段；目录即边界，不按 kind 过滤
    filename_is_name = True  # 旧文件名是 C_陈佳豪.json，按姓名而非 id 命名

    def __init__(self, directory=None):
        super().__init__(directory or (paths.NOTES / "contacts"))

    def _filename(self, rec: dict) -> str:
        """沿用旧命名 `C_姓名.json`（字母_姓名）——改名会让手机端解不出人。"""
        letter = str(rec.get("letter") or "?").upper()[:1]
        name = str(rec.get("name") or rec.get("id") or "未知")
        safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip() or "未知"
        return f"{letter}_{safe}.json"

    def by_group(self, group: str | None = None) -> list[dict]:
        rows = self.visible()
        if group:
            rows = [r for r in rows if str(r.get("group") or "") == group]
        return rows

    def groups(self) -> list[str]:
        seen: list[str] = []
        for r in self.visible():
            g = str(r.get("group") or "")
            if g and g not in seen:
                seen.append(g)
        return seen

    def add(self, name: str, **fields) -> dict:
        rec = {"name": name.strip(), "letter": (name.strip()[:1] or "?"),
               "phone": "", "wechat": "", "qq": "", "birthday": "", "relation": "",
               "note": "", "info": [], "todos": [], "created_at": iso_now()}
        rec.update(fields)
        return self.save(rec)


_repo: ContactsRepo | None = None


def repo() -> ContactsRepo:
    global _repo
    if _repo is None:
        _repo = ContactsRepo()
    return _repo
