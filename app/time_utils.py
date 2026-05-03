from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import get_settings


@lru_cache
def app_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def local_now() -> datetime:
    return datetime.now(app_timezone()).replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()
