# -*- coding: utf-8 -*-
"""账单导入验收（2026-09-14）：微信/支付宝 CSV 解析 + 去重 + 只导支出。全临时目录。"""
import sys
import os
import tempfile

sys.path.insert(0, r"D:\Luyuan")
tmp = tempfile.mkdtemp(prefix="luyuan_bill_")

import expenses  # noqa: E402
# 🔴 expenses._DIR 是模块常量（不走 config/_cfg_cache），必须直接指到临时目录。
#   第一版测试漏了这条 → 5 条测试账单写进生产库（已物理清理，教训入册）。
expenses._DIR = tmp

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌"), name, ("" if cond else "-> %r" % (detail,)))


# 微信支付账单格式（导出 CSV 解压后的样子，去掉前置说明行）
WECHAT = """微信支付账单明细,,,,,,,,,,
微信支付账单明细,,,,,,,,,,
---------------,微信支付账单明细,,,,,,,,,,
交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注
2026-09-10 12:30:45,商户消费,瑞幸咖啡,瑞幸咖啡拿铁,支出,¥15.90,零钱,支付成功,10001,20001,"/"
2026-09-11 08:12:00,商户消费,中国铁路12306,火车票,支出,¥55.00,招商银行(1234),支付成功,10002,20002,"/"
2026-09-11 18:00:00,红包,张三,微信红包,收入,¥200.00,零钱,已存入零钱,10003,20003,"/"
2026-09-12 09:00:00,商户消费,京东商城,买书,支出,¥89.50,零钱通,支付成功,10004,20004,"/"
"""

# 支付宝账单格式（旧版 tab 分隔 + 新版逗号两种测一个）
ALIPAY = """------------------------支付宝交易记录明细查询------------------------
账号:[xxx***yy]
起始日期:[2026-09-01 00:00:00]  终止日期:[2026-09-14 23:59:59]
---------------------------------交易记录明细列表----------------------------------
交易号,商家订单号,交易创建时间,付款时间,最近修改时间,交易来源地,类型,交易对方,商品名称,金额（元）,收/支,交易状态
20260912xxx,20260912yyy,2026-09-12 21:05:00,2026-09-12 21:05:10,2026-09-12 21:05:10,手机,交易,美团外卖,黄焖鸡米饭,25.80,支出,交易成功
20260913xxx,20260913yyy,2026-09-13 10:00:00,2026-09-13 10:00:05,2026-09-13 10:00:05,电脑,交易,淘宝网,数据结构教材,68.00,支出,交易成功
20260913zzz,,2026-09-13 15:00:00,,,手机,转账,李四,转账,100.00,收入,交易成功
"""

imp1, skip1, err1 = expenses.import_bill_text(WECHAT, source="wechat_bill")
check("微信账单导入 3 条支出", imp1 == 3, (imp1, err1))
check("微信账单收入被跳过", skip1 == 1, skip1)

imp2, skip2, err2 = expenses.import_bill_text(ALIPAY, source="alipay_bill")
check("支付宝账单导入 2 条支出", imp2 == 2, (imp2, err2))
check("支付宝收入被跳过", skip2 == 1, skip2)

# 金额/商品映射抽查
all_e = expenses.list_all()
lx = [e for e in all_e if "拿铁" in (e.get("item") or "")]
check("金额解析正确(¥15.90→15.9)", lx and abs(lx[0]["amount"] - 15.9) < 0.01,
      lx[0]["amount"] if lx else "无")
check("交易对方并入名目", lx and "瑞幸" in (lx[0]["item"] or ""), lx[0]["item"] if lx else "")
check("spent_at 归一 ISO", lx and lx[0]["spent_at"] == "2026-09-10T12:30:45",
      lx[0]["spent_at"] if lx else "")
mt = [e for e in all_e if "黄焖鸡" in (e.get("item") or "")]
check("支付宝条目入库", bool(mt))
# 自动分类：微信「商户消费+拿铁」→ 餐饮；铁路12306 → 交通；京东买书 → 学习
check("账单自动分类·餐饮", lx and lx[0].get("category") == "餐饮", lx[0].get("category") if lx else None)
tl = [e for e in all_e if "火车票" in (e.get("item") or "")]
check("账单自动分类·交通", tl and tl[0].get("category") == "交通", tl[0].get("category") if tl else None)
jd = [e for e in all_e if "买书" in (e.get("item") or "")]
check("账单自动分类·学习", jd and jd[0].get("category") == "学习", jd[0].get("category") if jd else None)

# 幂等：重复粘贴同一份
imp3, skip3, _ = expenses.import_bill_text(WECHAT, source="wechat_bill")
check("重复导入幂等（0 新增，3 去重+1 收入跳过）", imp3 == 0 and skip3 == 4, (imp3, skip3))

# 坏输入
imp4, skip4, err4 = expenses.import_bill_text("随便一段文字", source="bill")
check("无表头文本安全拒绝", imp4 == 0 and len(err4) == 1, err4)

print("-" * 50)
print("结果：%d 过 / %d 挂" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
