from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Timezones always included in the context block
_DEFAULT_ZONES = [
    ("UTC",             "UTC"),
    ("Los Angeles",     "America/Los_Angeles"),
    ("New York",        "America/New_York"),
    ("London",          "Europe/London"),
    ("Germany",         "Europe/Berlin"),
    ("Dubai",           "Asia/Dubai"),
    ("Singapore",       "Asia/Singapore"),
    ("Tokyo",           "Asia/Tokyo"),
    ("Sydney",          "Australia/Sydney"),
]


def get_time_context(extra_zones: list[tuple[str, str]] | None = None) -> str:
    """
    Return a one-block time context string for injection into LLM prompts.
    extra_zones: optional list of (label, IANA tz name) pairs to append.
    """
    now_utc = datetime.now(ZoneInfo("UTC"))
    zones = _DEFAULT_ZONES + (extra_zones or [])
    parts = []
    for label, tz_name in zones:
        try:
            t = now_utc.astimezone(ZoneInfo(tz_name))
            parts.append(f"{label}: {t.strftime('%b %d %Y %H:%M')} {t.strftime('%Z')}")
        except ZoneInfoNotFoundError:
            parts.append(f"{label}: unknown tz '{tz_name}'")
    return "[CURRENT TIME]\n" + " | ".join(parts)


def convert_tz(label: str, tz_name: str) -> str:
    """Convert current UTC time to a named timezone, returning a short string."""
    now_utc = datetime.now(ZoneInfo("UTC"))
    try:
        t = now_utc.astimezone(ZoneInfo(tz_name))
        return f"{label}: {t.strftime('%b %d %Y %H:%M %Z')}"
    except ZoneInfoNotFoundError:
        return f"Unknown timezone: {tz_name}"
