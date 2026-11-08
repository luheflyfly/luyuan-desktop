"""天气（open-meteo，免 key、免注册）。

为什么自己写而不复用 3927 那个：那是路远远（Node）的工具，挂在它自己的
工具箱里且**没有配城市**；路远大脑要能独立回答"今天带不带伞"，不能依赖
第二个进程活着。

三件事：
  1. 城市 → 坐标（中文名有歧义："长沙"会先命中重庆的长沙镇，所以按人口取最大）
  2. 坐标 → 当前 + 今天 + 明天（10 分钟缓存，别把免 key 的公共服务打爆）
  3. 数据 → **一句人话**（这才是路远要说的，不是把 JSON 甩给用户）
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from luyuan.logs import get

log = get("weather")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FC_URL = "https://api.open-meteo.com/v1/forecast"
TZ = "Asia/Shanghai"
TTL = 600  # 秒

# WMO 天气码 → 中文（只保留会说人话需要的那几档）
WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}
RAINY = set(range(51, 68)) | {80, 81, 82, 95, 96, 99}
SNOWY = {71, 73, 75, 77, 85, 86}
RAIN_TIP = "有雨，伞提前放包里"


def _get(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "luyuan/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


@dataclass
class Place:
    name: str
    admin: str
    lat: float
    lon: float


@dataclass
class Weather:
    place: Place
    temp: float
    code: int
    precip: float
    today_max: float
    today_min: float
    today_code: int
    pop: int
    tomorrow_max: float = 0.0
    tomorrow_min: float = 0.0
    tomorrow_code: int = 0
    tomorrow_pop: int = 0
    fetched_at: float = field(default_factory=time.time)

    # ── 人话 ───────────────────────────────────────────────
    @property
    def label(self) -> str:
        return WMO.get(self.code, WMO.get(self.today_code, "未知"))

    def brief(self) -> str:
        """一句话。规则：先说结论（带不带伞/穿多少），再给数字，最后给"明天"。"""
        parts: list[str] = []
        rainy = self.today_code in RAINY or self.pop >= 60
        snowy = self.today_code in SNOWY
        if snowy:
            parts.append("今天有雪，路滑，穿厚点")
        elif rainy:
            parts.append("今天有雨，出门带伞")
        elif self.pop >= 40:
            parts.append("今天可能下雨，伞放包里稳妥")
        else:
            parts.append(f"今天{self.label}")

        parts.append(f"{self.today_min:.0f}–{self.today_max:.0f}°")
        if self.today_max - self.today_min >= 8:
            parts.append("早晚温差大，加件外套")
        if self.today_max >= 33:
            parts.append("热，多喝水")
        if self.today_max <= 5:
            parts.append("冷，注意保暖")

        # 今天没雨但明天有 → 值得提前一句（洗衣服、带伞放包里）
        if not rainy and (self.tomorrow_code in RAINY or self.tomorrow_pop >= 60):
            parts.append(f"明天{RAIN_TIP}")
        return "，".join(parts) + "。"

    def as_dict(self) -> dict:
        return {
            "city": self.place.name, "admin": self.place.admin,
            "lat": self.place.lat, "lon": self.place.lon,
            "now": {"temp": self.temp, "code": self.code, "label": self.label,
                    "precip": self.precip},
            "today": {"max": self.today_max, "min": self.today_min,
                      "code": self.today_code, "pop": self.pop,
                      "label": WMO.get(self.today_code, "未知")},
            "tomorrow": {"max": self.tomorrow_max, "min": self.tomorrow_min,
                         "code": self.tomorrow_code, "pop": self.tomorrow_pop,
                         "label": WMO.get(self.tomorrow_code, "未知")},
            "brief": self.brief(),
            "at": self.fetched_at,
        }


_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, builder, ttl: float = TTL):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = builder()
    if val is not None:
        _cache[key] = (time.time(), val)
    return val


def resolve_city(name: str) -> Place | None:
    """城市名 → 坐标。

    中文名有歧义，实测过的坑：查 "长沙" 会先命中**重庆的长沙镇**（人口 4.7 万），
    湖南长沙（人口 309 万）根本不在结果里；必须查 "长沙市" 或 "Changsha" 才对。
    所以这里做尝试链：原名 → 加"市" → 英文名（同一份缓存里取人口最大的）。
    """

    def _query(q: str):
        params = urllib.parse.urlencode({"name": q, "count": 5, "language": "zh",
                                         "format": "json", "countryCode": "CN"})
        try:
            data = _get(f"{GEO_URL}?{params}")
        except Exception as e:  # noqa: BLE001
            log.warning("地理编码失败 %s: %s", q, e)
            return []
        return data.get("results") or []

    def build():
        candidates: list[dict] = []
        tries = [name]
        if not name.endswith(("市", "县", "区")):
            tries.append(name + "市")
        for q in tries:
            rows = _query(q)
            if rows:
                candidates.extend(rows)
                # 命中的第一个名字对得上且人口够大，就不再往下试
                best = max(rows, key=lambda r: r.get("population") or 0)
                if (best.get("population") or 0) >= 500_000:
                    break
        if not candidates:
            return None
        best = max(candidates, key=lambda r: r.get("population") or 0)
        return Place(best.get("name") or name, best.get("admin1") or "",
                     float(best["latitude"]), float(best["longitude"]))

    return _cached(f"geo:{name}", build, ttl=86400)


def fetch(city: str = "长沙", lat: float | None = None, lon: float | None = None) -> Weather | None:
    place = Place(city, "", lat, lon) if (lat and lon) else resolve_city(city)
    if not place:
        return None

    def build():
        q = urllib.parse.urlencode({
            "latitude": place.lat, "longitude": place.lon,
            "current": "temperature_2m,precipitation,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": TZ, "forecast_days": 2,
        })
        try:
            d = _get(f"{FC_URL}?{q}")
        except Exception as e:  # noqa: BLE001
            log.warning("天气接口失败: %s", e)
            return None
        cur, day = d.get("current") or {}, d.get("daily") or {}
        try:
            return Weather(
                place=place,
                temp=float(cur.get("temperature_2m") or 0),
                code=int(cur.get("weather_code") or 0),
                precip=float(cur.get("precipitation") or 0),
                today_max=float(day["temperature_2m_max"][0]),
                today_min=float(day["temperature_2m_min"][0]),
                today_code=int(day["weather_code"][0]),
                pop=int(day.get("precipitation_probability_max", [0])[0] or 0),
                tomorrow_max=float(day["temperature_2m_max"][1]),
                tomorrow_min=float(day["temperature_2m_min"][1]),
                tomorrow_code=int(day["weather_code"][1]),
                tomorrow_pop=int(day.get("precipitation_probability_max", [0, 0])[1] or 0),
            )
        except (KeyError, IndexError, TypeError) as e:
            log.warning("天气数据形状异常: %s", e)
            return None

    return _cached(f"wx:{place.name}:{place.lat:.3f}", build)
