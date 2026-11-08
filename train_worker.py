"""【venv python 运行】训练「路远」唤醒词的无界面工作进程。

由 train_gui.py 通过子进程启动（CREATE_NO_WINDOW，不弹黑窗）。
协议：从 stdin 读命令，向 stdout 输出 JSON 进度行。

命令（每行一条）：
  START <n_pos> <n_neg>   开始（创建样本目录）
  REC                      录制一条当前阶段的样本
  AMBIENT <seconds>        录 seconds 秒环境声，自动切成 1 秒段存为负样本
  STOP                     中止训练

事件（stdout JSON）：
  {"event":"started","n_pos":..,"n_neg":..}
  {"event":"need_sample","phase":"pos|neg","index":..,"total":..}
  {"event":"sample","phase":..,"index":..,"total":..}
  {"event":"ambient_start","seconds":..}
  {"event":"ambient_progress","second":..,"total":..}
  {"event":"ambient_done","slices":..}
  {"event":"training"}
  {"event":"done","model":..,"pos_score":..,"neg_score":..,"threshold":..}
  {"event":"error","msg":..}
  {"event":"stopped"}
"""
import os
import sys
import json
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

LOG = os.path.join(BASE, "train_wakeword.log")


def log(*a):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[worker %s] %s\n" % (time.strftime("%H:%M:%S"),
                                          " ".join(map(str, a))))
    except Exception:
        pass


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


try:
    import numpy as np
    import soundfile as sf
    import config
    import recorder
    import wakeword
except Exception as e:
    emit({"event": "error", "msg": "依赖加载失败: %s" % e})
    log("import error", repr(e))
    sys.exit(1)

POS_DIR = os.path.join(wakeword.MODEL_DIR, "positives")
NEG_DIR = os.path.join(wakeword.MODEL_DIR, "negatives")
MODEL_PATH = wakeword.MODEL_PATH

state = {"n_pos": 40, "n_neg": 30, "pos": 0, "neg": 0,
         "phase": "pos", "running": False}


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


def _choose_threshold(p_pos, p_neg):
    """在训练集上选阈值：负样本误报率控制 ≤2%，正样本召回尽量高。
    并 clamp 到 [0.6, 0.95]，避免极端值（如坏样本把阈值顶到 1.0）。"""
    best_t = 0.85
    best_recall = -1.0
    for t in np.linspace(0.5, 0.97, 100):
        neg_rate = float((p_neg >= t).mean()) if len(p_neg) else 0.0
        if neg_rate > 0.02:
            continue
        recall = float((p_pos >= t).mean()) if len(p_pos) else 0.0
        if recall > best_recall:
            best_recall = recall
            best_t = t
    return float(min(0.95, max(0.6, best_t)))


def do_train():
    Xp = _feats_from_dir(POS_DIR)
    Xn = _feats_from_dir(NEG_DIR)
    emit({"event": "log", "msg": "正样本 %d 条，负样本 %d 条" %
          (Xp.shape[0], Xn.shape[0])})
    X = np.vstack([Xp, Xn]).astype(np.float32)
    y = np.concatenate([np.ones(Xp.shape[0]),
                        np.zeros(Xn.shape[0])]).astype(np.float32)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    Xs = (X - mean) / (std + 1e-6)
    w, b = wakeword.train_lr(Xs, y, lr=0.1, iters=3000)
    p_pos = wakeword._sigmoid((Xp - mean) @ w + b)
    p_neg = wakeword._sigmoid((Xn - mean) @ w + b)
    thr = _choose_threshold(p_pos, p_neg)
    model = {
        "w": w.tolist(), "b": float(b),
        "mean": mean.tolist(), "std": std.tolist(),
        "threshold": thr, "n_mfcc": wakeword.N_MFCC, "sr": wakeword.SR,
        "trained_at": time.strftime("%Y-%m-%d %H:%M"),
        "n_pos": int(Xp.shape[0]), "n_neg": int(Xn.shape[0]),
    }
    os.makedirs(wakeword.MODEL_DIR, exist_ok=True)
    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)
    cfg = config.load()
    cfg.setdefault("wakeword", {})["enabled"] = True
    cfg["wakeword"]["model"] = MODEL_PATH
    config.save(cfg)
    emit({"event": "done", "model": MODEL_PATH,
          "pos_score": float(p_pos.mean()), "neg_score": float(p_neg.mean()),
          "threshold": thr})


def record_one():
    folder = POS_DIR if state["phase"] == "pos" else NEG_DIR
    idx = state["pos"] if state["phase"] == "pos" else state["neg"]
    path = os.path.join(folder, "%03d.wav" % idx)
    recorder.record_until_silence(path, max_seconds=4,
                                  silence_seconds=0.8, min_seconds=0.5)
    return path


def do_ambient(secs=30):
    """连续录 secs 秒房间环境声，切成 1 秒段存入负样本目录。
    用途：把风扇/底噪等环境音当负样本，根治"恒触发"类误判。"""
    try:
        import sounddevice as sd
    except Exception as e:
        emit({"event": "error", "msg": "录音组件不可用: %s" % e})
        return
    os.makedirs(NEG_DIR, exist_ok=True)
    start_idx = len([f for f in os.listdir(NEG_DIR)
                     if f.startswith("amb_") and f.lower().endswith(".wav")])
    sr = wakeword.SR
    secs = max(5, min(int(secs), 120))
    emit({"event": "ambient_start", "seconds": secs})
    log("AMBIENT start", secs, "s")
    chunks = []
    try:
        with sd.InputStream(samplerate=sr, channels=1, dtype="float32") as stream:
            for i in range(secs):
                data, _ = stream.read(sr)
                chunks.append(data[:, 0].copy())
                emit({"event": "ambient_progress", "second": i + 1, "total": secs})
    except Exception as e:
        emit({"event": "error", "msg": "环境声录制失败: %s" % e})
        return
    all_data = np.concatenate(chunks)
    n_slices = 0
    for j in range(secs):
        seg = all_data[j * sr:(j + 1) * sr].astype(np.float32)
        if seg.shape[0] < sr // 2:
            continue
        rms = float(np.sqrt((seg ** 2).mean()))
        if rms < 1e-4:  # 纯数字静音段，没有训练价值
            continue
        path = os.path.join(NEG_DIR, "amb_%03d.wav" % (start_idx + n_slices))
        sf.write(path, seg, sr)
        n_slices += 1
    log("AMBIENT done, slices", n_slices)
    emit({"event": "ambient_done", "slices": n_slices})


def handle_rec():
    try:
        record_one()
    except Exception as e:
        emit({"event": "error", "msg": "录音失败: %s" % e})
        return
    if state["phase"] == "pos":
        state["pos"] += 1
        if state["pos"] >= state["n_pos"]:
            state["phase"] = "neg"
            emit({"event": "sample", "phase": "pos",
                  "index": state["pos"], "total": state["n_pos"]})
            emit({"event": "need_sample", "phase": "neg",
                  "index": 1, "total": state["n_neg"]})
        else:
            emit({"event": "sample", "phase": "pos",
                  "index": state["pos"], "total": state["n_pos"]})
            emit({"event": "need_sample", "phase": "pos",
                  "index": state["pos"] + 1, "total": state["n_pos"]})
    else:
        state["neg"] += 1
        if state["neg"] >= state["n_neg"]:
            emit({"event": "sample", "phase": "neg",
                  "index": state["neg"], "total": state["n_neg"]})
            do_train()
            state["running"] = False
        else:
            emit({"event": "sample", "phase": "neg",
                  "index": state["neg"], "total": state["n_neg"]})
            emit({"event": "need_sample", "phase": "neg",
                  "index": state["neg"] + 1, "total": state["n_neg"]})


def main():
    os.makedirs(wakeword.MODEL_DIR, exist_ok=True)
    log("worker started, pid", os.getpid())
    emit({"event": "ready"})
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0]
        if cmd == "START":
            try:
                state["n_pos"] = int(parts[1]) if len(parts) > 1 else 40
                state["n_neg"] = int(parts[2]) if len(parts) > 2 else 30
            except ValueError:
                state["n_pos"], state["n_neg"] = 40, 30
            state["pos"] = state["neg"] = 0
            state["phase"] = "pos"
            state["running"] = True
            os.makedirs(POS_DIR, exist_ok=True)
            os.makedirs(NEG_DIR, exist_ok=True)
            emit({"event": "started", "n_pos": state["n_pos"],
                  "n_neg": state["n_neg"]})
            emit({"event": "need_sample", "phase": "pos",
                  "index": 1, "total": state["n_pos"]})
            log("START", state["n_pos"], state["n_neg"])
        elif cmd == "REC":
            if state["running"]:
                handle_rec()
        elif cmd == "AMBIENT":
            try:
                secs = int(parts[1]) if len(parts) > 1 else 30
            except ValueError:
                secs = 30
            do_ambient(secs)
        elif cmd == "STOP":
            state["running"] = False
            emit({"event": "stopped"})
            log("STOP")
            break
    log("worker exit")


if __name__ == "__main__":
    main()
