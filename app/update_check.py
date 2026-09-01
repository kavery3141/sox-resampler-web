from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query


LATEST_RELEASE_URL = "https://api.github.com/repos/kavery3141/sox-resampler-web/releases/latest"
CACHE_SECONDS = 6 * 60 * 60
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?$")
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def _version_parts(value: str) -> tuple[tuple[int, int, int], bool] | None:
    match = _VERSION_RE.fullmatch(str(value).strip())
    if not match:
        return None
    return (
        (int(match.group(1)), int(match.group(2)), int(match.group(3))),
        bool(match.group(4)),
    )


def newer_release_available(current: str, latest: str) -> bool | None:
    current_parts = _version_parts(current)
    latest_parts = _version_parts(latest)
    if current_parts is None or latest_parts is None:
        return None
    current_base, current_prerelease = current_parts
    latest_base, latest_prerelease = latest_parts
    if latest_base != current_base:
        return latest_base > current_base
    if current_prerelease and not latest_prerelease:
        return True
    return False


def _fetch_latest_release(timeout: float = 4.0) -> dict[str, Any]:
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "sox-resampler-web-update-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "check_status": "unavailable",
                "reason": "No published GitHub release is available yet",
            }
        return {
            "check_status": "unavailable",
            "reason": f"GitHub release check returned HTTP {exc.code}",
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "check_status": "unavailable",
            "reason": f"Unable to check GitHub releases: {exc}",
        }

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return {
            "check_status": "unavailable",
            "reason": "Latest GitHub release did not contain a version tag",
        }
    return {
        "check_status": "ok",
        "latest_version": tag.removeprefix("v"),
        "release_url": payload.get("html_url"),
        "published_at": payload.get("published_at"),
        "release_name": payload.get("name") or tag,
        "prerelease": bool(payload.get("prerelease")),
        "draft": bool(payload.get("draft")),
    }


def check_for_updates(current_version: str, *, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get("payload")
        if not force and cached is not None and float(_CACHE.get("expires_at") or 0.0) > now:
            return dict(cached)

    latest = _fetch_latest_release()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result: dict[str, Any] = {
        "current_version": current_version,
        "checked_at": checked_at,
        "automatic_install": False,
        **latest,
    }
    if latest.get("check_status") == "ok":
        comparison = newer_release_available(current_version, str(latest["latest_version"]))
        result["update_available"] = comparison
        if comparison is None:
            result["comparison_status"] = "unknown"
            result["reason"] = "Current or latest version is not a comparable semantic version"
        else:
            result["comparison_status"] = "update-available" if comparison else "up-to-date"
    else:
        result["update_available"] = None
        result["comparison_status"] = "unavailable"

    with _CACHE_LOCK:
        _CACHE["payload"] = dict(result)
        _CACHE["expires_at"] = now + CACHE_SECONDS
    return result


def reset_update_cache_for_tests() -> None:
    with _CACHE_LOCK:
        _CACHE["payload"] = None
        _CACHE["expires_at"] = 0.0


def build_update_router(app_version: str) -> APIRouter:
    router = APIRouter()

    @router.get("/api/maintenance/update")
    def update_status(force: bool = Query(default=False)) -> dict[str, Any]:
        return check_for_updates(app_version, force=force)

    return router
