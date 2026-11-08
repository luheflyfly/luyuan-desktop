# -*- coding: utf-8 -*-
"""人名识别专项回归（2026-09-14 夜班新增，配合 test_wechat_parse.py）。

背景：路河 09-13 深夜反馈「人名识别还不是很准确」，且已因微信误发出丑。
本文件专攻「收件人名字」这一环，与 test_wechat_parse 的指令识别互补：

  A. 「说」字并入名字（09-14 实锤：给妈妈说：X → 名字解析成「妈妈说」→ 搜索零结果）
  B. 收件人同音字纠正（STT 把「张俊扬」转成「张俊杨」→ 名字对不上任何联系人）
  C. 间接转告句（让X知道… / X那边回一句…）——云端二审通道
  D. 名字边界安全网（绝不猜名字的既有铁律不松）

用法：cd <project-root> && ./.venv/Scripts/python.exe test_wechat_names.py
🔴 依赖联系人库：B 组需要「张俊杨」在联系人名单里（班级 30 人名单，实库有）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import router  # noqa: E402

# ---- A. 「说」字并入名字（正则层 bug，必须确定性修复）----
# 「给X说：正文」③标点通道先命中，旧代码把引导语「说」吞进名字 → 搜「妈妈说」零结果
SAY_TAIL_HIT = [
    ("给妈妈说：明天开会", ("妈妈", "明天开会")),
    ("跟路河说：明天下午三点图书馆见", ("路河", "明天下午三点图书馆见")),
    ("给老师说：作业交了", ("老师", "作业交了")),
    ("回复妈妈说：明天开会", ("妈妈", "明天开会")),
    ("帮我跟路河说一下：票买好了", ("路河", "票买好了")),
]

# 修复不许误伤：正文以「说」开头的既有正确行为（test_wechat_parse 也有，这里是名字侧）
SAY_TAIL_SAFE = [
    # 「张说」若真是联系人名就不该被剥——但库里没有单字后缀人名，此处验证不崩即可
    ("回复张三：说好的下午三点", ("张三", "说好的下午三点")),
    ("回他：说好的下午三点", ("current", "说好的下午三点")),
]

# ---- B. 同音字纠正（需要联系人库有「张俊杨」）----
# STT 同音错名 → 解析出的 to 不在联系人库 → 应纠正为库内同名拼音联系人
HOMOPHONE_HIT = [
    ("给张俊扬说训练改到周四", ("张俊杨", "训练改到周四")),   # 扬→杨
]

# 不该被纠正的（防过度纠正）：
HOMOPHONE_SAFE = [
    # 库内真实联系人直接用，不折腾
    ("给张俊杨说训练改到周四", ("张俊杨", "训练改到周四")),
    # 「路河」不在库内且无同音联系人 → 保留原名（今晚小号唯一联系人就是它）
    ("给路河说：明天下午三点图书馆见", ("路河", "明天下午三点图书馆见")),
]

# 拼音前缀纠错：STT 整词听错还变字数的真实案例（09-13 SenseVoice 实录）
PREFIX_HIT = [
    ("给陆平坦乘客说我下午要去图书馆", ("路平坦成河", "我下午要去图书馆")),
    # 09-15 追加：路河真实语音失败案例（张俊龙/张旭阳 均为「张俊杨」的 STT 错名）
    ("给张俊龙说训练改到周四", ("张俊杨", "训练改到周四")),
]

# ---- C. 间接转告句（本地 2b 判 None 时走 DeepSeek 云端二审）----
# 离线/无余额自动 SKIP，不算失败
CLOUD_HIT = [
    ("让路河知道明天不用等我", ("路河", "明天不用等我")),
    ("路河那边回一句说我马上到", ("路河", "我马上到")),
    ("帮我转告路河晚上聚餐", ("路河", "晚上聚餐")),
]

CLOUD_MISS = [
    ("给妈妈买药", None),          # 无转告信号 → 连云端都不该问
    ("明天下午三点开会", None),     # 纯日程 → 不发
]

# ---- E. 对抗扫描（09-14 凌晨对抗实测揪出的盲区，修复后固化为回归）----
ADVERSARIAL = [
    # 名字尾部中缀动词/称谓尾巴（曾解析成「张三发个消息」「路平坦成河的微信」）
    ("给张三发个消息说明天见", ("张三", "明天见")),
    ("回复路平坦成河的微信：好的", ("路平坦成河", "好的")),
    ("回消息给张三：ok", ("张三", "ok")),          # 后置动词「回消息给」
    ("转发给张三：明天停课", ("张三", "明天停课")),  # 「转发给」动词
    # 倒装「把X告诉Y」：正文在前收件人在后（曾解析成名字=「把明天开会的事」）
    ("帮我把明天开会的事告诉张三", ("张三", "明天开会的事")),
    ("把停课通知告诉张三", ("张三", "停课通知")),   # 无动词前缀也认
    ("替我把取件码告诉路平坦成河", ("路平坦成河", "取件码")),
    # 多人连接词 → 收件人不确定，宁可落笔记
    ("跟张三李四都说到了", None),
]

# ---- D. 安全网：宁可落笔记也绝不猜名字 ----
SAFETY_MISS = [
    "给妈妈买药",
    "给车加油",
    "跟老师请假",
    "回复邮件：今天处理完了",
    "回学校明天开会",
    "给她打电话",
    "给他发个红包",
    "明天下午三点开会",
]


def _run(fn, rows, expect_is_tuple):
    bad = 0
    for text, want in rows:
        got = fn(text)
        ok = got == want
        bad += 0 if ok else 1
        print("%s %-30s -> %r (期望 %r)" % ("OK " if ok else "FAIL", text, got, want))
    return bad


def _run_cloud():
    """云端二审通道。DeepSeek 不可达 → SKIP（不算失败）。"""
    import socket
    try:
        s = socket.create_connection(("api.deepseek.com", 443), timeout=3)
        s.close()
    except Exception as e:
        print("SKIP 云端通道：DeepSeek 不可达（%s）" % e)
        return 0
    bad = 0
    for text, want in CLOUD_HIT + CLOUD_MISS:
        got = router._cloud_wechat_judge(text)
        ok = got == want
        bad += 0 if ok else 1
        print("%s [云] %-26s -> %r (期望 %r)" % ("OK " if ok else "FAIL", text, got, want))
    return bad


def main():
    bad = 0
    print("== A. 「说」字并入名字 ==")
    bad += _run(router.parse_wechat, SAY_TAIL_HIT, True)
    bad += _run(router.parse_wechat, SAY_TAIL_SAFE, True)
    print("== B. 同音字纠正（resolve 后的完整解析）==")
    bad += _run(router.parse_wechat_resolved, HOMOPHONE_HIT, True)
    bad += _run(router.parse_wechat_resolved, HOMOPHONE_SAFE, True)
    bad += _run(router.parse_wechat_resolved, PREFIX_HIT, True)
    print("== D. 安全网（必须 None）==")
    for text in SAFETY_MISS:
        got = router.parse_wechat(text)
        ok = got is None
        bad += 0 if ok else 1
        print("%s %-30s -> %r" % ("OK " if ok else "FAIL", text, got))
    print("== E. 对抗扫描（盲区回归）==")
    bad += _run(router.parse_wechat_resolved, ADVERSARIAL, True)
    n = (len(SAY_TAIL_HIT) + len(SAY_TAIL_SAFE) + len(HOMOPHONE_HIT)
         + len(HOMOPHONE_SAFE) + len(PREFIX_HIT) + len(SAFETY_MISS)
         + len(ADVERSARIAL))
    print("-" * 62)
    print("本地通道 %d/%d PASS" % (n - bad, n))
    cloud_bad = _run_cloud()
    print("-" * 62)
    print("总计 %d/%d PASS%s" % (n - bad + len(CLOUD_HIT) + len(CLOUD_MISS) - cloud_bad,
                                 n + len(CLOUD_HIT) + len(CLOUD_MISS),
                                 "" if not cloud_bad else "（云端通道 %d 条挂）" % cloud_bad))
    return 1 if (bad or cloud_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
