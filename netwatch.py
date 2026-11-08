# -*- coding: utf-8 -*-
"""断网出门感应（netwatch）：识别「在家/离家」，给 main.py 的监视循环供状态。

原理：宿舍网指纹 = 路由器网关 MAC + WiFi SSID（双指纹，有线无线通用）。
- 在家：SSID 在 home_ssids 里，或 默认网关 MAC 在 home_gateway_macs 里
- 离家：连了别的网（热点/外网），或干脆没网
- netsh/ipconfig/arp 输出编码随启动环境变（Git Bash 下 UTF-8、服务下 GBK），统一双解码
状态机在 AwayMonitor：连续 N 次检测到「非家」才算真出门（防路由器重启的假断网误报）。
"""
import re
import subprocess

log_name = "netwatch"


def _run(cmd, timeout=8):
    """跑命令，返回解码后的 stdout（utf-8 优先，GBK 兜底）；失败返回空串。"""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = p.stdout or b""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("gbk", "ignore")
    except Exception:
        return ""


def wifi_ssid():
    """当前连接的 WiFi SSID；WiFi 没连返回 None。SSID 标签本身不分语言。"""
    txt = _run(["netsh", "wlan", "show", "interfaces"])
    if not txt:
        return None
    m = re.search(r"^\s*SSID\s*:\s*(\S.*)$", txt, re.M)
    return m.group(1).strip() if m else None


def default_route():
    """IPv4 默认路由 → (网关IP, 本机接口IP)；没有外网路由返回 (None, None)。
    用 route print 的数字列，天然不受系统语言影响。"""
    txt = _run(["route", "print", "-4"])
    best = None
    for line in txt.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            try:
                metric = int(parts[4])
                gw, iface = parts[2], parts[3]
            except ValueError:
                continue
            if gw in ("0.0.0.0", "On-link"):
                gw = None
            if best is None or metric < best[2]:
                best = (gw, iface, metric)
    if not best:
        return None, None
    return best[0], best[1]


def gateway_mac(ip, probe=True):
    """网关 IP → MAC（路由器唯一指纹）。先 ping 一下确保 ARP 表有记录。"""
    if not ip:
        return None
    if probe:
        _run(["ping", "-n", "1", "-w", "600", ip], timeout=3)
    txt = _run(["arp", "-a", ip], timeout=6)
    for line in txt.splitlines():
        if ip in line:
            parts = line.split()
            for p in parts[1:3]:
                if p.count("-") == 5 or p.count(":") == 5:
                    return p.lower()
    return None


def get_network_state():
    """当前网络状态。connected=有没有默认路由；ssid=WLAN（可能与有线并存）。"""
    st = {"connected": False, "ssid": None, "gw_ip": None, "gw_mac": None,
          "via": None}
    ssid = wifi_ssid()
    if ssid:
        st["ssid"] = ssid
        st["via"] = "wifi"
    gw_ip, iface_ip = default_route()
    if gw_ip or iface_ip:
        st["connected"] = True
        st["gw_ip"] = gw_ip
        if not st["via"]:
            st["via"] = "ethernet"
        st["gw_mac"] = gateway_mac(gw_ip)
    return st


def classify_state(st, cfg):
    """home = 命中家里任一指纹；其余（别的网/没网）都算 away。"""
    ssids = set(cfg.get("home_ssids") or [])
    macs = set(str(m).lower() for m in (cfg.get("home_gateway_macs") or []))
    if st.get("ssid") and st["ssid"] in ssids:
        return "home"
    if st.get("gw_mac") and st["gw_mac"].lower() in macs:
        return "home"
    return "away"


class AwayMonitor:
    """防抖状态机：连续 confirm 次 away 才确认「出门」。
    update() 返回 "depart" / "arrive" / None。
    启动后第一次读数作为基线，不产生边沿（防重启误报）。"""

    def __init__(self, confirm=4):
        self.confirm = max(1, int(confirm))
        self.streak = {"home": 0, "away": 0}
        self.confirmed = None

    def update(self, raw):
        raw = "home" if raw == "home" else "away"
        self.streak[raw] += 1
        self.streak["away" if raw == "home" else "home"] = 0
        if self.confirmed is None:
            self.confirmed = raw
            return None
        if raw == self.confirmed:
            return None
        if self.streak[raw] >= self.confirm:
            old = self.confirmed
            self.confirmed = raw
            return "depart" if old == "home" else "arrive"
        return None
