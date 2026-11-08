"""生活域路由：天气（以及后续的日历/位置/邮件）。

原则：**给结论，不给原始 JSON**。`brief` 字段就是准备直接念给用户听的那句话。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from luyuan import config as config_mod
from luyuan.io import weather as wx

router = APIRouter()


@router.get("/api/weather")
def weather(city: str = "", lat: float | None = None, lon: float | None = None):
    cfg = config_mod.Config.load()
    city = city or str(cfg.get("weather.city") or "长沙")
    lat = lat if lat is not None else cfg.get("weather.latitude")
    lon = lon if lon is not None else cfg.get("weather.longitude")
    w = wx.fetch(city, lat=lat, lon=lon)
    if not w:
        return JSONResponse({"error": "weather_unavailable", "city": city,
                             "msg": "天气拿不到（没网或城市名不认识）"}, status_code=503)
    return w.as_dict()
