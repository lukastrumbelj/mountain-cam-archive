from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def nearest_slot(now_utc: datetime, slots: list[str], tz: str, tolerance_min: int = 90):
    """Najbližji načrtovani termin v lokalnem času (upošteva zimski/poletni čas).

    Vrne (lokalni datum termina, "HH-MM") ali None, če noben termin ni znotraj tolerance.
    """
    zi = ZoneInfo(tz)
    local = now_utc.astimezone(zi)
    best = None
    for dd in (-1, 0, 1):
        d = local.date() + timedelta(days=dd)
        for s in slots:
            h, m = map(int, s.split(":"))
            planned = datetime(d.year, d.month, d.day, h, m, tzinfo=zi)
            diff = abs((local - planned).total_seconds()) / 60
            if best is None or diff < best[0]:
                best = (diff, d, s)
    if best and best[0] <= tolerance_min:
        return best[1], best[2].replace(":", "-")
    return None


def local_parts(dt_utc: datetime, tz: str) -> tuple[date, str, datetime]:
    local = dt_utc.astimezone(ZoneInfo(tz))
    return local.date(), local.strftime("%H-%M"), local
