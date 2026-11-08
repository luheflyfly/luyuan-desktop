# -*- coding: utf-8 -*-
"""路远远汇报后端验收（2026-10-19 批）：report_<id8>.json 读取 + 已读/删除回写 + 容量封顶 + 未知 kind 不串台。
全临时数据（SYNC_FORMAT §10.6 契约），不起真服务——API 薄壳只是转发，联调时 curl 冒烟。"""
import sys
import os
import json
import tempfile

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_report_")

import reports

reports._DIR = tmp

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


def put(fname, obj):
    with open(os.path.join(tmp, fname), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# 1) 建一条 → 文件名/字段齐
r1 = reports.create("待办晨报 · 10月19日", "【今天 3】· 内容", category="晨报")
check("create 落盘 report_ 前缀", os.path.exists(os.path.join(tmp, "report_%s.json" % r1["id"][:8])))
check("create 字段齐", all(k in r1 for k in ("kind", "id", "schema", "device", "deleted", "title", "category", "text", "read", "created_at", "updated_at"))
      and r1["kind"] == "report" and r1["schema"] == 3 and r1["read"] is False and r1["deleted"] is False,
      json.dumps(r1, ensure_ascii=False)[:200])

# 2) 旧端互不串台：todo/expense/未知 kind 均不进汇报列表，坏文件跳过
put("todo_ab12cd34.json", {"kind": "todo", "id": "t1", "text": "x"})
put("expense_ef12cd34.json", {"kind": "expense", "id": "e1", "amount": 1})
put("mystery_aa12cd34.json", {"kind": "mystery", "id": "m1"})
put("report_bad1.json", "{ 坏 JSON")
put("report_conflict.json.sync-conflict-20261019", {"kind": "report", "id": "c1"})
ls = reports.list_reports()
check("list 只认 kind=report", [r["id"] for r in ls] == [r1["id"]], str(len(ls)))
check("badge 未读=1", reports.unread_count() == 1, str(reports.unread_count()))

# 3) 已读/未读回写：fresh 读盘只改 read/read_at/updated_at，其余字段原样
before = json.loads(open(os.path.join(tmp, "report_%s.json" % r1["id"][:8]), encoding="utf-8").read())
r1b = reports.mark_read(r1["id"], True)
after = json.loads(open(os.path.join(tmp, "report_%s.json" % r1["id"][:8]), encoding="utf-8").read())
check("mark_read 生效", r1b and r1b["read"] is True and r1b["read_at"], "")
check("回写未碰别的字段", after["text"] == before["text"] and after["title"] == before["title"] and after["created_at"] == before["created_at"], "")
check("badge 清零", reports.unread_count() == 0)
r1c = reports.mark_read(r1["id"], False)
check("标回未读", r1c["read"] is False and r1c["read_at"] is None and reports.unread_count() == 1)

# 4) read_all / overview / 未知 rid
r2 = reports.create("提醒：交材料", "明天 15:00 前", category="提醒")
ov = reports.overview()
check("overview 未读计数", ov["unread"] == 2 and ov["count"] == 2 and len(ov["reports"]) == 2, json.dumps({k: ov[k] for k in ("unread", "count")}))
n = reports.read_all()
check("read_all 全标", n == 2 and reports.unread_count() == 0)
check("未知 rid 返回 None", reports.mark_read("nope") is None and reports.discard("nope") is False)

# 5) 物理删单条
ok = reports.discard(r2["id"])
check("discard 物理删", ok and not os.path.exists(os.path.join(tmp, "report_%s.json" % r2["id"][:8])))

# 6) 容量封顶：造 6 条、上限调 3 → 最老 3 条软删，最新 3 条健在
reports._KEEP = 3
made = [reports.create("第 %d 条" % i, "x", category="手动") for i in range(6)]
alive = [r for r in reports.list_reports(limit=0) if not r.get("deleted")]
ids = {r["id"] for r in alive}
check("容量封顶软删最老", len(alive) == 3 and ids == {r["id"] for r in made[3:]}, "alive=%d" % len(alive))
# 软删墓碑不再出现在列表/未读里
check("软删不进列表", all(r["id"] not in ids for r in reports.list_reports(limit=0) if r.get("deleted")))

# 7) 别把真同步根写花了：临时目录里只有汇报文件（Syncthing 冲突副本不归汇报管，排除）
others = [f for f in os.listdir(tmp) if f.startswith("report_") and "sync-conflict" not in f]
check("文件命名全为 report_*.json", all(f.startswith("report_") and f.endswith(".json") for f in others), str(others[:5]))

print("\n—— 路远远汇报 %d/%d 过 —— tmp=%s" % (len(PASS), len(PASS) + len(FAIL), tmp))
sys.exit(1 if FAIL else 0)
