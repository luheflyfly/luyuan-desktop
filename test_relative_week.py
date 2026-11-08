# -*- coding: utf-8 -*-
"""A1 相对星期确定性覆盖验收（2026-09-14）。
覆盖：周X / 下周X / 今天恰是周X / 跨月 / 跨年 + 上周跳过 + 时间抽取 + 真实入口（process_note 正则压过模型）。"""
import sys
import datetime

sys.path.insert(0, r"D:\Luyuan")
import smart

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


def d(y, mo, dd, h=10, mi=0):
    return datetime.datetime(y, mo, dd, h, mi)


def day_of(text, now):
    dt, hit = smart._resolve_relative_weekday(text, now)
    return (dt.date() if dt else None), hit, dt


NOW = d(2026, 9, 14)          # 2026-09-14 是周一
assert NOW.weekday() == 0

# 1) 周X = 下一个该星期几（原 bug 案：「周五前交」模型给 09-14，应为 09-18）
day, hit, dt = day_of("周五前交材料", NOW)
check("周X 周五前交=09-18", day == datetime.date(2026, 9, 18), "%s hit=%s" % (day, hit))
check("周X 默认上午9点", dt and dt.hour == 9 and dt.minute == 0, str(dt))

day, _, _ = day_of("周六去取快递", NOW)
check("周X 周六=09-19", day == datetime.date(2026, 9, 19), str(day))
day, _, _ = day_of("周日给家里打电话", NOW)
check("周X 周日=本周日09-20", day == datetime.date(2026, 9, 20), str(day))

# 2) 下周X
day, _, _ = day_of("下周一交作业", NOW)
check("下周X 下周一=09-21", day == datetime.date(2026, 9, 21), str(day))
day, _, _ = day_of("下周五组会汇报", NOW)
check("下周X 下周五=09-25", day == datetime.date(2026, 9, 25), str(day))

# 3) 今天恰是该天 → 7 天后
day, _, dt = day_of("周一下午三点开会", NOW)
check("今天恰是周X 取7天后=09-21", day == datetime.date(2026, 9, 21), str(day))
check("下午三点=15:00", dt and dt.hour == 15, str(dt))

# 4) 跨月
day, _, _ = day_of("下周三交表格", d(2026, 9, 28))   # 09-28 周一 → 下周三 = 10-07
check("跨月 下周三=10-07", day == datetime.date(2026, 10, 7), str(day))

# 5) 跨年
day, _, _ = day_of("下周四交年终总结", d(2026, 12, 28))  # 12-28 周一 → 下周四 = 2027-01-07
check("跨年 下周四=2027-01-07", day == datetime.date(2027, 1, 7), str(day))

# 6) 上周X（过去）不解析
day, hit, _ = day_of("上周五我交了材料", NOW)
check("上周X 跳过不解析", day is None, "%s hit=%s" % (day, hit))

# 7) 时间抽取
day, _, dt = day_of("周三下午三点取票", NOW)
check("周三=09-16", day == datetime.date(2026, 9, 16), str(day))
check("下午三点=15:00", dt and dt.hour == 15 and dt.minute == 0, str(dt))
_, _, dt = day_of("周五晚上八点半开会", NOW)
check("晚上八点半=20:30", dt and (dt.hour, dt.minute) == (20, 30), str(dt))
_, _, dt = day_of("下周二上午十点取件", NOW)
check("上午十点=10:00", dt and dt.hour == 10, str(dt))
_, _, dt = day_of("周四15:30答辩", NOW)
check("15:30 直接认", dt and (dt.hour, dt.minute) == (15, 30), str(dt))
_, _, dt = day_of("周五中午12点聚餐", NOW)
check("中午12点=12:00", dt and dt.hour == 12, str(dt))

# 8) 多个星期词取第一个（主要期限通常在前）
day, hit, _ = day_of("周五前交表，下周三讨论", NOW)
check("多个星期词取第一个", day == datetime.date(2026, 9, 18) and hit and "周五" in hit,
      "%s %s" % (day, hit))

# 9) 非星期词不误伤
day, _, _ = day_of("把周报整理一下发出去", NOW)
check("周报 不误伤", day is None, str(day))
day, _, _ = day_of("这周末大扫除", NOW)
check("周末 不误伤", day is None, str(day))

# 10) 真实入口：process_note 里正则必须压过模型输出（Ollama 开着才跑；这就是生产路径本身）
#     ⚠️ 期望日期按"今天"动态推算，别把当天日历写死进断言
#    （09-15 夜把 周三=09-16 写死，过午夜立即误报——时间炸弹拆除 ZCode 09-16）
def _next_weekday(anchor, weekday):        # 0=周一 … 6=周日
    days = (weekday - anchor.weekday()) % 7
    if days == 0:
        days = 7                            # 当天说"周X"= 下周（解析器口径）
    return anchor + datetime.timedelta(days=days)

CATS = ["待办", "购物", "想法", "写作素材", "日常"]
if smart.ollama_running():
    FRI = _next_weekday(datetime.date.today(), 4)
    WED = _next_weekday(datetime.date.today(), 2)
    r = smart.process_note("周五前交奖学金申请表", CATS)
    ra = r.get("remind_at")
    ok = ra and ra[:10] == FRI.isoformat()
    check("process_note 真实入口=本周五（正则压过模型）", ok, str(r))
    r2 = smart.process_note("记得周三下午去取快递", CATS)
    ra2 = r2.get("remind_at")
    ok2 = ra2 and ra2[:10] == WED.isoformat()
    check("process_note 真实入口=本周三 15:00", ok2 and ra2[11:16] == "15:00", str(r2))
else:
    print("⏭️ Ollama 未运行，跳过真实入口两条（纯函数部分已全覆盖）")

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)


# ---- 09-15 追加：中文数字时刻（router.parse_time 直测，_clock 借 _extract_hm）----
if __name__ == "__main__" or True:
    _cn_cases = [
        ("明天上午十点提醒我开会", "10"),
        ("明晚八点聚会", "20"),
        ("今晚十点叫我", "22"),
        ("明天下午三点提醒我交材料", "15"),
        ("明天上午10点开会", "10"),
    ]
    import router as _rt
    _bad = 0
    print("-- 中文数字时刻（parse_time）--")
    for _t, _h in _cn_cases:
        _r = _rt.parse_time(_t)
        _got = _r[11:13] if _r else None
        _ok = _got == _h
        _bad += 0 if _ok else 1
        print(("OK " if _ok else "FAIL"), repr(_t), "->", _r)
    if _bad:
        print(f"中文时刻 {_bad} 错")
        sys.exit(1)
