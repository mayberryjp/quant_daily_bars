"""Container-local timezone helpers.

Every database timestamp is stored and returned in the container's local
timezone (New York). These helpers resolve that timezone, provide local-time
values for application code, and build SQLAlchemy engines whose sessions use it,
so the application and the database always agree on a single zone rather than
falling back to UTC or a fixed offset.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
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


def make_engine(url: str, **kwargs: Any) -> Any:
    """Create a SQLAlchemy engine whose sessions use the container-local timezone.

    Server-side time (``now()``, ``current_timestamp``) and every ``timestamptz``
    value read back are rendered in the container's local timezone rather than the
    server default (usually UTC).
    """
    from sqlalchemy import create_engine

    connect_args = dict(kwargs.pop("connect_args", {}))
    tz_option = f"-c timezone={local_timezone_name()}"
    existing_options = connect_args.get("options", "")
    connect_args["options"] = f"{existing_options} {tz_option}".strip()
    return create_engine(url, connect_args=connect_args, **kwargs)
