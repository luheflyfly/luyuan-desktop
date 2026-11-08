"""【需要用户本人运行】训练「路远」语音唤醒词模型。

流程：
  1) 录 N 条你本人说"路远"的音频（正样本）
  2) 录 M 条其他声音/安静（负样本）
  3) 提取 MFCC 特征，训练逻辑回归分类器
  4) 模型写出到 models/luyuan_wakeword/luyuan_model.json
  5) 把 config.json 里 wakeword.enabled 设为 true，重启路远即可语音唤醒

注意：唤醒词必须录你本人的声音，换人录模型不认。
运行方式：双击「<project-root>\\训练路远唤醒词.bat」（不要直接双击本文件）。
"""
import os
import sys
import json
import time

# ---- 启动器自检：必须用路远 venv 的 Python 运行，否则依赖全找不到 ----
def _in_venv():
    return getattr(sys, "base_prefix", sys.prefix) != sys.prefix

if not _in_venv():
    print("=" * 50)
    print("⚠️  这个脚本不能直接双击打开！")
    print("请改用「<project-root>\\训练路远唤醒词.bat」来运行。")
    print("=" * 50)
    try:
        input("按回车关闭此窗口...")
    except EOFError:
        pass
    sys.exit(2)

import numpy as np
import soundfile as sf

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import config
import recorder
import wakeword

POS_DIR = os.path.join(wakeword.MODEL_DIR, "positives")
NEG_DIR = os.path.join(wakeword.MODEL_DIR, "negatives")
MODEL_PATH = wakeword.MODEL_PATH


def _record_set(folder, count, prompt_word):
    os.makedirs(folder, exist_ok=True)
    print(f"\n===== {prompt_word}（共 {count} 条）=====")
    for i in range(count):
        while True:
            input(f"  [{i + 1}/{count}] 按回车后清晰说「路远」，说完自动停…")
            try:
                path = os.path.join(folder, f"{i:03d}.wav")
                recorder.record_until_silence(path, max_seconds=4,
                                              silence_seconds=0.8, min_seconds=0.5)
                print("    已保存:", os.path.basename(path))
                break
            except Exception as e:
                print("    ⚠️ 没录到，重试：", e)


def _feats_from_dir(folder):
    feats = []
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(".wav"):
            continue
        data, sr = sf.read(os.path.join(folder, fn), always_2d=False)
        if data.ndim > 1:
            data = data[:, 0]
        feats.append(wakeword.extract_features(data.astype(np.float32), sr))
    return np.array(feats, dtype=np.float32)


def main():
    os.makedirs(wakeword.MODEL_DIR, exist_ok=True)
    n_pos = int(input("要录几条'路远'正样本？(建议 40): ").strip() or "40")
    n_neg = int(input("要录几条负样本(随便说别的/安静)？(建议 30): ").strip() or "30")

    _record_set(POS_DIR, n_pos, "正样本：说「路远」")
    _record_set(NEG_DIR, n_neg, "负样本：说别的词或安静坐着")

    print("\n===== 提取特征 + 训练 =====")
    Xp = _feats_from_dir(POS_DIR)
    Xn = _feats_from_dir(NEG_DIR)
    print(f"  正样本 {Xp.shape[0]} 条，负样本 {Xn.shape[0]} 条")

    X = np.vstack([Xp, Xn]).astype(np.float32)
    y = np.concatenate([np.ones(Xp.shape[0]), np.zeros(Xn.shape[0])]).astype(np.float32)

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    Xs = (X - mean) / (std + 1e-6)

    w, b = wakeword.train_lr(Xs, y, lr=0.1, iters=3000)

    # 在训练集上估阈值：让 95% 负样本判为负，同时尽量不漏正样本
    p_pos = wakeword._sigmoid((Xp - mean) @ w + b)
    p_neg = wakeword._sigmoid((Xn - mean) @ w + b)
    thr = float(max(0.7, np.quantile(p_neg, 0.95)))
    print(f"  正样本得分 均值={p_pos.mean():.2f}  负样本得分 均值={p_neg.mean():.2f}")
    print(f"  设定阈值 = {thr:.2f}")

    model = {
        "w": w.tolist(),
        "b": b,
        "mean": mean.tolist(),
        "std": std.tolist(),
        "threshold": thr,
        "n_mfcc": wakeword.N_MFCC,
        "sr": wakeword.SR,
        "trained_at": time.strftime("%Y-%m-%d %H:%M"),
        "n_pos": int(Xp.shape[0]),
        "n_neg": int(Xn.shape[0]),
    }
    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    print("✅ 模型已保存:", MODEL_PATH)

    # 自动开启唤醒词
    cfg = config.load()
    cfg.setdefault("wakeword", {})["enabled"] = True
    cfg["wakeword"]["model"] = MODEL_PATH
    config.save(cfg)
    print("已把 config.json 的 wakeword.enabled 设为 true。")
    print("重启「路远」（退出托盘图标再双击启动路远.bat）即可用语音「路远」唤醒。")


if __name__ == "__main__":
    main()
