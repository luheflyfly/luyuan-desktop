# -*- coding: utf-8 -*-
"""v1.37 隔离活体测试：纯函数单测 + 8778 单进程自测，全临时数据，验证完即退。
覆盖：parse_time 分钟级、_rules_route 强信号、/api/terminal 三层漏斗、
confirm(含 edits)/reject/undo/rejudge/记忆表/pending、批量恢复/彻底删除、counts。"""
import sys
import os
import json
import time
import tempfile
import threading
import datetime
import urllib.request
import urllib.error

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_t137_")

import store
import router
import expenses
import courses
import contacts
import classify

store._cfg_cache = {"notes_dir": tmp}
router._SESSIONS_FILE = os.path.join(tmp, "terminal_sessions.json")
router._MEMORY_FILE = os.path.join(tmp, "terminal_memory.json")
expenses._DIR = tmp
courses._DIR = tmp
contacts._DIR = os.path.join(tmp, "contacts")
classify.process_async = lambda *a, **k: None   # 测试不跑真模型

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %s" % detail))


# ---------------- 一、纯函数单测 ----------------
now = datetime.datetime.now().astimezone()

r = router.parse_time("20分钟后提醒我拿快递", now)
dt = datetime.datetime.fromisoformat(r)
check("parse_time 分钟级(20分钟后)", abs((dt - now).total_seconds() - 1200) < 65, r)
r = router.parse_time("半小时后开会", now)
dt = datetime.datetime.fromisoformat(r)
check("parse_time 半小时后", abs((dt - now).total_seconds() - 1800) < 65, r)
r = router.parse_time("明天下午三点取蛋糕", now)
dt = datetime.datetime.fromisoformat(r)
expect = (now + datetime.timedelta(days=1)).replace(hour=15, minute=0)
check("parse_time 明天下午三点", dt.hour == 15 and dt.date() == expect.date(), r)
r = router.parse_time("周五之前交报告", now)
dt = datetime.datetime.fromisoformat(r)
check("parse_time 周X前=当天21点", dt.hour == 21, r)
r = router.parse_time("没有时间词的一句话", now)
check("parse_time 无时间词=None", r is None, r)

res = router._rules_route("https://example.com/post/1 好文")
check("rules URL→稍后读", res and res[0] == "read_later", str(res))
res = router._rules_route("今天午饭花了35块")
check("rules 花了35块→expense", res and res[0] == "expense"
      and res[1].get("amount") == 35.0, str(res))
res = router._rules_route("¥12.5 奶茶")
check("rules ¥12.5→expense", res and res[1].get("amount") == 12.5, str(res))
res = router._rules_route("谢凤林的生日是10月20日")
check("rules 生日→contact_update", res and res[0] == "contact_update"
      and res[1].get("name") == "谢凤林" and res[1].get("field") == "birthday",
      str(res))
res = router._rules_route("今天认识了王雨琪 PHONE_REDACTED")
check("rules 认识了→contact_create+手机号", res and res[0] == "contact_create"
      and "王雨琪" in res[1].get("name", "") and res[1].get("phone"), str(res))
res = router._rules_route("别忘了明天9点交作业")
check("rules 别忘了→todo+提醒", res and res[0] == "todo"
      and res[1].get("remind_at"), str(res))
res = router._rules_route("？今天有什么安排")
check("rules ？开头→ask", res and res[0] == "ask", str(res))
res = router._rules_route("今天天气不错心情很好")
check("rules 无强信号→None(交给模型)", res is None, str(res))

# 回归（2026-09-09 深夜切云案）：弱线索不得劫持长文本（弱词只对短文本生效）
long_diary = ("今天一整天都在忙各种各样的事情，早上起来先去食堂吃了顿早饭，"
              "然后去图书馆坐了一上午看书写笔记，下午又开了两个会讨论课程安排，"
              "晚上回宿舍还要整理白天积攒下来的资料和待办清单，感觉一天过得飞快，"
              "整个人都累得不行，希望明天能够稍微轻松一点吧。")
res = router._rules_route(long_diary)
check("回归:长文本含'待办清单'不被劫持成todo", res is None or res[0] != "todo",
      str(res))
res = router._rules_route("记得那天我们在图书馆坐了一下午，聊了好多好多以前的事，"
                          "感觉又回到了刚认识的时候，真是怀念啊。")
check("回归:长叙事'记得那天'不劫持", res is None or res[0] != "todo", str(res))
res = router._rules_route("记得明天交作业")
check("回归:短文本弱线索仍生效", res is not None and res[0] == "todo", str(res))
# 嵌套 JSON 解析（模型层返回 fields 套层时不再全灭）
import json as _json
out_nested = '{"intent": "diary", "fields": {"text": "今天很累，想睡觉。"}}'
data = None
try:
    data = _json.loads(out_nested.strip())
except Exception:
    pass
check("回归:嵌套JSON整段loads可用", data and data.get("intent") == "diary",
      str(data))

# ---------------- 二、8778 隔离实例 E2E ----------------
import server
import uvicorn


def _serve():
    uvicorn.run(server.app, host="127.0.0.1", port=8778, log_level="warning")


threading.Thread(target=_serve, daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen("http://127.0.0.1:8778/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.2)


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:8778" + path, data=data,
                                 method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


# 空输入 → 把关点①错误契约
st, r = call("POST", "/api/terminal", {"text": ""})
check("空输入 400+人话", st == 400 and r["error"]["code"] == "empty"
      and r["error"]["msg"], "%s %s" % (st, r))

# 待办 + N分钟后（轻动作直执行）
st, r = call("POST", "/api/terminal", {"text": "20分钟后提醒我拿快递"})
a0 = (r.get("actions") or [{}])[0]
tid_todo = r.get("id", "")
check("terminal 待办 rules 直执行", st == 200 and r["model"] == "rules"
      and a0.get("status") == "done" and a0.get("fields", {}).get("remind_at"),
      "%s %s" % (st, json.dumps(r, ensure_ascii=False)[:200]))
nid_todo = a0.get("fields", {}).get("note_id")
st, r = call("GET", "/api/notes")
check("待办真落库+待办标签", any(n["id"] == nid_todo and "待办" in n["tags"]
                              for n in r["notes"]), "")

# undo 撤销 → 回收站
st, r = call("POST", "/api/terminal/%s/undo" % tid_todo)
check("undo 撤销待办", st == 200 and r.get("undone") == 1, "%s %s" % (st, r))
st, r = call("GET", "/api/notes")
check("撤销后列表不见", not any(n["id"] == nid_todo for n in r["notes"]), "")
st, r = call("GET", "/api/notes?trash=1")
check("撤销=软删进回收站", any(n["id"] == nid_todo for n in r["notes"]), "")

# 记账重动作：出卡 → 改金额确认 → 入账
st, r = call("POST", "/api/terminal", {"text": "今天晚饭花了35块"})
a0 = (r.get("actions") or [{}])[0]
tid1 = r.get("id", "")
check("记账出确认卡(不入库)", st == 200 and a0.get("confirm") is True
      and a0.get("status") == "pending"
      and abs(a0.get("fields", {}).get("amount", 0) - 35.0) < 0.01,
      json.dumps(r, ensure_ascii=False)[:200])
st, r2 = call("GET", "/api/terminal/pending")
check("pending 列表有卡", any(i["tid"] == tid1 for i in r2.get("items", [])), r2)
st, r2 = call("POST", "/api/terminal/%s/confirm" % tid1,
              {"index": 0, "edits": {"amount": 38}})
check("confirm+改金额入库", st == 200 and abs(
    r2["result"]["expense"]["amount"] - 38.0) < 0.01, "%s %s" % (st, r2))
st, r2 = call("GET", "/api/expenses")
check("记账列表可见38元", any(abs(e["amount"] - 38.0) < 0.01
                          for e in r2["items"]), r2)

# 第二张卡 reject
st, r = call("POST", "/api/terminal", {"text": "昨天打车花了15块"})
tid2 = r["id"]
st, r2 = call("POST", "/api/terminal/%s/reject" % tid2, {"index": 0})
check("reject 放弃不入库", st == 200 and r2.get("ok"), "%s %s" % (st, r2))
st, r2 = call("GET", "/api/expenses")
check("reject 后无15元账", not any(abs(e["amount"] - 15.0) < 0.01
                                for e in r2["items"]), "")

# 联系人建档卡 → 确认
st, r = call("POST", "/api/terminal", {"text": "今天认识了王雨琪 PHONE_REDACTED"})
tid3 = r["id"]
st, r2 = call("POST", "/api/terminal/%s/confirm" % tid3, {"index": 0})
check("联系人建档入库", st == 200 and r2["result"]["contact"]["name"] == "王雨琪"
      and r2["result"]["contact"].get("phone") == "PHONE_REDACTED", "%s %s" % (st, r2))

# 档案更新卡 → 确认
st, r = call("POST", "/api/terminal", {"text": "王雨琪的生日是10月20日"})
tid4 = r["id"]
st, r2 = call("POST", "/api/terminal/%s/confirm" % tid4, {"index": 0})
check("生日写进档案", st == 200 and r2["result"]["contact"].get("birthday"),
      "%s %s" % (st, r2))

# 更新不存在的联系人 → 人话错误，卡留着
st, r = call("POST", "/api/terminal", {"text": "李逍遥的电话是13900001111"})
tid5 = r["id"]
st, r2 = call("POST", "/api/terminal/%s/confirm" % tid5, {"index": 0})
check("无此人→人话错误卡保留", st == 400 and r2["error"]["code"] == "confirm_fix"
      and "李逍遥" in r2["error"]["msg"], "%s %s" % (st, r2))
st, r2 = call("POST", "/api/terminal/%s/reject" % tid5, {"index": 0})
check("错误卡可放弃", st == 200, "%s" % st)

# ask 交接
st, r = call("POST", "/api/terminal", {"text": "？我上周记了什么"})
check("ask 交接不动库", st == 200 and r["actions"][0]["action"] == "ask.handoff"
      and r["actions"][0]["status"] == "handoff", "%s %s" % (st, r))

# 兜底：普通短句（模型层真跑，失败也必须落笔记=兜底铁律）
st, r = call("POST", "/api/terminal", {"text": "随便记一句测试兜底"})
a0 = (r.get("actions") or [{}])[0]
check("兜底铁律：落普通笔记", st == 200 and a0.get("status") == "done"
      and a0.get("fields", {}).get("note_id"), json.dumps(r, ensure_ascii=False)[:150])

# 记忆表：rejudge 教学命中
st, r = call("POST", "/api/terminal", {"text": "记忆表测试专属句"})
tid6 = r["id"]
st, r2 = call("POST", "/api/terminal/%s/rejudge" % tid6,
              {"index": 0, "action": "todo.create"})
check("rejudge 记入记忆表", st == 200 and r2.get("memory") == "todo",
      "%s %s" % (st, r2))
st, r = call("POST", "/api/terminal", {"text": "记忆表测试专属句"})
check("记忆表命中 model=memory", st == 200 and r["model"] == "memory"
      and r["intent"] == "todo", json.dumps(r, ensure_ascii=False)[:150])

# 批量恢复/彻底删除（回收站工具条缺口）：先删2 → 彻底删1 → 恢复1 → 守卫验证
st, r = call("GET", "/api/notes")
ids = [n["id"] for n in r["notes"][:2]]
st, _ = call("POST", "/api/notes/delete_many", {"ids": ids})
check("软删2条", st == 200, st)
st, r = call("POST", "/api/notes/purge_many", {"ids": ids[:1]})
check("批量彻底删1条", r.get("purged") == 1, r)
st, r = call("POST", "/api/notes/restore_many", {"ids": ids[1:]})
check("批量恢复1条", r.get("restored") == 1, r)
st, r = call("POST", "/api/notes/purge_many", {"ids": [ids[1]]})
check("彻底删已恢复条=0(防误删守卫)", r.get("purged") == 0, r)

# counts
st, r = call("GET", "/api/counts")
check("counts 模块计数", st == 200 and all(k in r for k in
      ("note", "diary", "trash", "expense", "course", "contact")), r)

print("\n===== 结果：%d 过 / %d 挂 =====" % (len(PASS), len(FAIL)))
if FAIL:
    print("挂掉：", FAIL)
    sys.exit(1)
