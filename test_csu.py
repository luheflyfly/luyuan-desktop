# -*- coding: utf-8 -*-
"""CSU 学业助手验收（2026-09-14 自提案一）：周锚点 + 校历导入幂等 + 速查。
全部走临时 notes_dir（真实笔记只读红线）。"""
import sys
import os
import datetime
import tempfile

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_csu_")

import store   # noqa: E402
import csu     # noqa: E402

store._cfg_cache = {"notes_dir": tmp}

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


# 1. 周锚点（拍板：2026-09-14 = 第一周周一）
w = csu.week_info(datetime.date(2026, 9, 14))
check("锚点日=第1周周一", w["week"] == 1 and w["week_day"] == "周一", w)
w = csu.week_info(datetime.date(2026, 9, 21))
check("7天后=第2周周一", w["week"] == 2, w)
w = csu.week_info(datetime.date(2026, 9, 13))
check("开学前一天显示倒计时", w["week"] == 0 and w.get("days_until") == 1, w)

# 2. upcoming：进行中/未来事件
ev = csu.upcoming(30, today=__import__("datetime").date(2026, 9, 14))
check("未来30天有事件", len(ev) > 0, len(ev))
check("区间事件（进行中）含困难认定", any("困难认定学生申请" in e["name"] for e in ev))

# 3. 导入提醒库（幂等）
imp1, skip1 = csu.import_calendar(120, store_mod=store)
check("首次导入 >0 条", imp1 > 0, imp1)
check("首次导入零跳过", skip1 == 0, skip1)
notes = store.list_notes()
csu_notes = [n for n in notes if n.get("source") == "csu"
             and (n.get("text") or "").startswith("[校历]")]
check("导入的笔记都在库里", len(csu_notes) == imp1, (len(csu_notes), imp1))
check("提醒都带 remind_at", all(n.get("remind_at") for n in csu_notes))
imp2, skip2 = csu.import_calendar(120, store_mod=store)
check("重复导入幂等（0 新增）", imp2 == 0 and skip2 == imp1, (imp2, skip2, imp1))

# 4. 速查
q = csu.quick("国家奖学金")
check("速查命中国奖", any("国家奖学金" in s for s in q["scholarships"]))
q = csu.quick("数学建模")
check("速查命中竞赛", any("数学建模" in s for s in q["competitions"]))
q = csu.quick("竞赛加分")
check("速查命中综测加分", len(q["bonuses"]) > 0)

# 5. 速查笔记种子（幂等 + 标题行查重）
si1, ss1 = csu.seed_notes(store)
check("种子首次导入 3 条", si1 == 3, si1)
si2, ss2 = csu.seed_notes(store)
check("种子重复导入幂等", si2 == 0 and ss2 == 3, (si2, ss2))
big = [n for n in store.list_notes()
       if (n.get("text") or "").startswith("[速查·竞赛]")]
check("竞赛速查正文真的落库（多行）", big and len(big[0]["text"].splitlines()) > 10,
      len(big[0]["text"].splitlines()) if big else 0)

# 6. 待核实清单
check("待核实清单 53 条", len(csu.pending()) == 53, len(csu.pending()))

print("-" * 50)
print("结果：%d 过 / %d 挂" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
