from __future__ import annotations

from datetime import date, datetime, timezone
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


def local_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_timezone()).replace(tzinfo=None)


def format_local_datetime(value: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    localized = local_datetime(value)
    return localized.strftime(fmt) if localized else ""
