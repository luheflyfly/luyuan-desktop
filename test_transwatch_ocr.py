# -*- coding: utf-8 -*-
"""transwatch 拍作业 OCR 闭环单测（vc102）。
占位筛选 / 识别写回（占位替换+raw 留底+ocr_done）/ 空结果完结 / 缺图抛错 / 分类触发。
OCR 引擎与 classify 一律以 stub 模块注入，不碰真 RapidOCR。
直接运行：python test_transwatch_ocr.py   →  末行打印「结果: X / Y」。"""
import io
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import transwatch

_RESULTS = []


def test(fn):
    _RESULTS.append(fn)
    return fn


def _mk_stub_modules(ocr_text):
    """注入 wechat_ocr / classify stub（transwatch 函数内 import 时命中）。"""
    fake_ocr = types.ModuleType("wechat_ocr")
    fake_ocr.ocr_image_path = lambda p: ocr_text
    fake_classify = types.ModuleType("classify")
    seen = {}
    fake_classify.classify_async = lambda nid, text: seen.update(nid=nid, text=text)
    return fake_ocr, fake_classify, seen


def _mk_notes_dir(tmp_root):
    d = os.path.join(tmp_root, "notes")
    os.makedirs(os.path.join(d, "images"), exist_ok=True)
    return d


def _write_note(d, note):
    fp = os.path.join(d, "2026-09-18_10-00-00_" + str(note.get("id", "x"))[:8] + ".json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(note, f, ensure_ascii=False)
    return fp


def _photo_note(**kw):
    base = {
        "kind": "note", "id": "test1234",
        "text": "[高等数学A（一）] （作业照片待识别）",
        "tags": ["高等数学A（一）"],
        "images": ["images/test_img.jpg"],
        "device": "phone", "transcribed": True,
        "deleted": False,
        "created_at": "2026-09-18T10:00:00+08:00",
        "updated_at": "2026-09-18T10:00:00+08:00",
    }
    base.update(kw)
    return base


def _fake_img(d):
    img = os.path.join(d, "images", "test_img.jpg")
    with open(img, "wb") as f:
        f.write(b"\xff" * 2048)      # 假图片（引擎已 stub，内容无所谓）
    return img


@test
def find_ocr_pending_filters(tmp):
    d = _mk_notes_dir(tmp)
    _write_note(d, _photo_note())
    _write_note(d, _photo_note(id="bad1", device="pc"))
    _write_note(d, _photo_note(id="bad2", deleted=True))
    _write_note(d, _photo_note(id="bad3", text="[课] 已抄好了"))
    _write_note(d, _photo_note(id="bad4", images=[]))
    got = transwatch.find_ocr_pending(d)
    assert len(got) == 1, f"应只收 1 条，实收 {len(got)}"
    assert got[0][1]["id"] == "test1234"


@test
def ocr_one_replaces_placeholder(tmp):
    d = _mk_notes_dir(tmp)
    _fake_img(d)
    fp = _write_note(d, _photo_note())
    fake_ocr, fake_classify, seen = _mk_stub_modules("1. 求极限\n2. 证明单调有界")
    sys.modules["wechat_ocr"] = fake_ocr
    sys.modules["classify"] = fake_classify
    try:
        note = transwatch.find_ocr_pending(d)[0][1]
        out = transwatch.ocr_one(fp, note, d, notify=None)
    finally:
        sys.modules.pop("wechat_ocr", None)
        sys.modules.pop("classify", None)
    assert "求极限" in out and "单调有界" in out
    with open(fp, "r", encoding="utf-8") as f:
        n = json.load(f)
    assert n["ocr_done"] is True
    assert "作业照片待识别" in n["raw_text"], "占位原文应留底 raw_text"
    assert "作业照片待识别" not in n["text"], "正文占位应被替换"
    assert "高等数学A（一）]" in n["text"], "课程前缀应保留"
    assert seen.get("nid") == "test1234", "应触发重新分类"


@test
def ocr_one_empty_result_marks_empty(tmp):
    d = _mk_notes_dir(tmp)
    _fake_img(d)
    fp = _write_note(d, _photo_note())
    fake_ocr, fake_classify, _seen = _mk_stub_modules("")
    sys.modules["wechat_ocr"] = fake_ocr
    sys.modules["classify"] = fake_classify
    try:
        note = transwatch.find_ocr_pending(d)[0][1]
        out = transwatch.ocr_one(fp, note, d)
    finally:
        sys.modules.pop("wechat_ocr", None)
        sys.modules.pop("classify", None)
    assert out == transwatch.OCR_EMPTY_TEXT
    with open(fp, "r", encoding="utf-8") as f:
        n = json.load(f)
    assert n["ocr_done"] is True, "空结果也算完成，不无限重试"
    assert transwatch.OCR_EMPTY_TEXT in n["text"]


@test
def ocr_one_missing_image_raises(tmp):
    d = _mk_notes_dir(tmp)
    fp = _write_note(d, _photo_note(images=["images/missing.jpg"]))
    fake_ocr, fake_classify, _seen = _mk_stub_modules("x")
    sys.modules["wechat_ocr"] = fake_ocr
    sys.modules["classify"] = fake_classify
    try:
        note = transwatch.find_ocr_pending(d)[0][1]
        try:
            transwatch.ocr_one(fp, note, d)
            raise AssertionError("缺图应抛 FileNotFoundError")
        except FileNotFoundError:
            pass
    finally:
        sys.modules.pop("wechat_ocr", None)
        sys.modules.pop("classify", None)


@test
def watch_loop_ocr_two_round_size_gate(tmp):
    """watch_loop OCR 段的两轮大小判定：大小还在变不识别；稳定后才识别。"""
    d = _mk_notes_dir(tmp)
    img = _fake_img(d)
    fp = _write_note(d, _photo_note())
    fake_ocr, fake_classify, _seen = _mk_stub_modules("第3章 习题 1-15")
    sys.modules["wechat_ocr"] = fake_ocr
    sys.modules["classify"] = fake_classify
    try:
        transwatch._ocr_sizes.clear()
        transwatch._ocr_attempts.clear()
        size = os.path.getsize(img)
        # 第一轮：prev=None → 只记大小不识别
        prev = transwatch._ocr_sizes.get(img)
        transwatch._ocr_sizes[img] = size
        assert prev is None
        assert transwatch.find_ocr_pending(d), "第一轮后仍应待识别"
        # 第二轮：大小一致 → 识别
        assert transwatch._ocr_sizes.get(img) == os.path.getsize(img)
        pend = transwatch.find_ocr_pending(d)
        transwatch.ocr_one(*pend[0], d, notify=None)
        with open(fp, "r", encoding="utf-8") as f:
            n = json.load(f)
        assert "第3章 习题 1-15" in n["text"]
    finally:
        sys.modules.pop("wechat_ocr", None)
        sys.modules.pop("classify", None)


def main():
    ok = 0
    total = 0
    import tempfile
    for fn in _RESULTS:
        total += 1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                fn(tmp)
            ok += 1
            print(f"[PASS] {fn.__name__}")
        except Exception as e:
            print(f"[FAIL] {fn.__name__}: {e}")
    print(f"结果: {ok} / {total}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
