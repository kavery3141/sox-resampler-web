from __future__ import annotations

from pathlib import Path


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


main = Path("app/main.py")
patch(
    main,
    "from .temp_cleanup import cleanup_orphan_temps\n",
    "from .temp_cleanup import cleanup_orphan_temps\nfrom .update_check import build_update_router\n",
    "main update router import",
)
patch(
    main,
    "app.include_router(build_profiles_router(DB_PATH))\n",
    "app.include_router(build_profiles_router(DB_PATH))\napp.include_router(build_update_router(APP_VERSION))\n",
    "main update router include",
)

ui = Path("app/static/ui.js")
patch(
    ui,
    "loadUiAddon('/static/maintenance-history.js');\n",
    "loadUiAddon('/static/maintenance-history.js');\nloadUiAddon('/static/update-status.js');\n",
    "UI update addon loader",
)
