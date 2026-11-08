"""自托管语音唤醒词检测器（路远）。

不依赖 openWakeWord 的训练器 / TTS 流水线。
方案：对 16k 单声道音频取 MFCC，按时序聚合为固定长度特征，
用逻辑回归分类器区分"路远"(正样本) 与其余声音(负样本)。
训练见 train_wakeword.py，模型存为 models/luyuan_wakeword/luyuan_model.json。

接口（供 main.py 调用）：
    ww = WakeWordDetector(on_detect=callback)
    ww.stop_event = threading.Event()
    threading.Thread(target=ww.run, daemon=True).start()
"""
import os
import sys
import time
import threading
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import config  # noqa: E402

try:
    import librosa
except Exception:
    librosa = None

SR = 16000          # 统一采样率
N_MFCC = 13         # MFCC 维数 -> 特征 = 2*13 = 26 维 (均值+标准差)
FEAT_DIM = 2 * N_MFCC
MODEL_DIR = os.path.join(BASE, "models", "luyuan_wakeword")
MODEL_PATH = os.path.join(MODEL_DIR, "luyuan_model.json")

try:
    import logging
    log = logging.getLogger("luyuan")
except Exception:
    log = None


# ---------------- 特征提取（训练/检测共用） ----------------
def extract_features(samples, sr=SR):
    """samples: 1-d float32 numpy 数组；返回 26 维特征向量。"""
    if librosa is None:
        raise RuntimeError("librosa 未安装，无法提取特征")
    y = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    if len(y) < SR // 4:
        y = np.pad(y, (0, max(0, SR // 4 - len(y))))
    # 去掉可能的直流偏置
    y = y - y.mean()
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=N_MFCC,
                                n_fft=512, hop_length=160)
    mean = mfcc.mean(axis=1)
    std = mfcc.std(axis=1)
    return np.concatenate([mean, std]).astype(np.float32)


# ---------------- 逻辑回归训练（纯 numpy，可控可测） ----------------
def train_lr(X, y, lr=0.1, iters=3000):
    """X: (n, d) 已标准化, y: (n,) 0/1。返回 (w, b)。"""
    n, d = X.shape
    X = X.astype(np.float64)
    y = y.astype(np.float64)
    w = np.zeros(d, dtype=np.float64)
    b = 0.0
    for _ in range(iters):
        z = X @ w + b
        z = np.clip(z, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        gw = X.T @ (p - y) / n
        gb = (p - y).mean()
        w -= lr * gw
        b -= lr * gb
    return w.astype(np.float32), float(b)


def _sigmoid(z):
    z = np.clip(z, -30, 30)
    return 1.0 / (1.0 + np.exp(-z))


# ---------------- 检测器 ----------------
class WakeWordDetector:
    def __init__(self, on_detect=None):
        self.on_detect = on_detect
        self.stop_event = threading.Event()
        self.threshold = 0.85
        self._fire_cooldown = 12.0     # 两次触发最小间隔（秒），防"连炸"
        self.available = False
        self._probs = []
        self._rms_hist = []
        self._last_fire = 0
        self.w = None
        self.b = 0.0
        self.mean = None
        self.std = None

        cfg = config.load()
        ww = cfg.get("wakeword", {})
        if not ww.get("enabled", False):
            if log:
                log.info("wakeword disabled in config")
            return
        if not os.path.exists(MODEL_PATH):
            if log:
                log.warning("wakeword model missing: %s", MODEL_PATH)
            return
        self._load()
        # 阈值可被 config 覆盖（2026-09-13 修「唤醒词一直自己启动语音输入」）：
        # 旧阈值 0.85 太低 —— 环境噪声实测在 0.93 就被判命中，且随后 STT 识别为
        # "empty speech"（无语音），坐实是无语音的误报；而历史上真正的"路远"
        # 命中分数都是 1.00 / 0.95。故抬到 0.94：挡掉 0.93 档噪声，又给 0.95
        # 档真唤醒留出余量。仍可由 config.wakeword.threshold 调整。
        try:
            thr = ww.get("threshold")
            if thr is not None:
                self.threshold = min(0.99, max(0.5, float(thr)))
        except Exception:
            pass
        if log:
            log.info("wakeword ready, threshold=%.2f", self.threshold)
        self.available = True

    def _load(self):
        with open(MODEL_PATH, "r", encoding="utf-8") as f:
            m = __import__("json").load(f)
        self.w = np.asarray(m["w"], dtype=np.float32)
        self.b = float(m["b"])
        self.mean = np.asarray(m["mean"], dtype=np.float32)
        self.std = np.asarray(m["std"], dtype=np.float32)
        self.threshold = min(0.95, max(0.5, float(m.get("threshold", 0.85))))
        self.n_mfcc = int(m.get("n_mfcc", N_MFCC))
        if log:
            log.info("wakeword model loaded, threshold=%.2f", self.threshold)

    def _predict(self, feat):
        x = (feat - self.mean) / (self.std + 1e-6)
        z = float(x @ self.w + self.b)
        return float(_sigmoid(z))

    def run(self):
        if not self.available:
            return
        import sounddevice as sd
        import bridge

        if log:
            log.info("wakeword listener started")
        while not self.stop_event.is_set():
            # 捕获流水线正在用麦克风时，主动让出，避免双开冲突
            if bridge.is_busy():
                time.sleep(0.4)
                continue
            # 录制结束后的静默冷却期：不自动触发，避免"录完又来"
            if bridge.ww_in_cooldown():
                time.sleep(0.3)
                continue
            try:
                buf = []

                def cb(indata, frames, t, s):
                    buf.append(indata.copy())

                with sd.InputStream(samplerate=SR, channels=1,
                                    dtype="float32", callback=cb):
                    deadline = time.time() + 1.0
                    while time.time() < deadline and not self.stop_event.is_set() \
                            and not bridge.is_busy():
                        time.sleep(0.05)
                if not buf:
                    time.sleep(0.2)
                    continue
                chunk = np.concatenate(buf, axis=0).reshape(-1)
                # ---- 能量门禁：只在明显比环境基线响的"人声"上才判定 ----
                # 避免房间底噪 / 风扇 / 麦克风回授等恒定背景被误判成 1.00。
                rms = float(np.sqrt(np.mean(np.square(
                    chunk.astype(np.float32)))))
                self._rms_hist.append(rms)
                if len(self._rms_hist) > 25:
                    self._rms_hist.pop(0)
                med = float(np.median(self._rms_hist)) if self._rms_hist else 0.0
                # 说话声通常明显比环境响；若当前能量没超过基线 2.2 倍，
                # 视为非语音（或恒定背景），直接跳过，不送模型。
                if med > 1e-4 and rms < max(2.2 * med, 1.0e-3):
                    time.sleep(0.1)
                    continue
            except Exception as e:
                if log:
                    log.warning("wakeword mic error: %s", e)
                time.sleep(1.0)
                continue

            try:
                feat = extract_features(chunk, SR)
                p = self._predict(feat)
            except Exception as e:
                if log:
                    log.warning("wakeword feature error: %s", e)
                time.sleep(0.3)
                continue

            self._probs.append(p)
            if len(self._probs) > 4:
                self._probs.pop(0)

            now = time.time()
            recent_max = max(self._probs)
            if recent_max > self.threshold and \
                    (now - self._last_fire) > self._fire_cooldown:
                self._last_fire = now
                if log:
                    log.info("wakeword DETECTED (score=%.2f)", recent_max)
                if self.on_detect:
                    try:
                        self.on_detect()
                    except Exception as e:
                        if log:
                            log.warning("wakeword on_detect error: %s", e)
        if log:
            log.info("wakeword listener stopped")
