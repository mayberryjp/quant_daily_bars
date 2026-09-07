"""Container-local timezone helpers.

These helpers resolve the container's local timezone and provide local-time
values for application code.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Used when the container exposes no timezone; the deployment sets its local
# timezone to New York.
DEFAULT_TIMEZONE = "America/New_York"


def local_timezone_name() -> str:
    """Return the container's local IANA timezone name."""
    tz = os.environ.get("TZ")
    if tz:
        return tz
    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        target = os.readlink(localtime)
        marker = "zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    return DEFAULT_TIMEZONE


def local_timezone() -> ZoneInfo:
    """Return the container's local timezone."""
    return ZoneInfo(local_timezone_name())


def local_now() -> datetime:
    """Return the current time in the container's local timezone."""
    return datetime.now(local_timezone())
