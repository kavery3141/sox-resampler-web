from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


main = Path("app/main.py")
replace_once(
    main,
    '''    zfs = zfs_pool_health()
    read_only_mode = bool(db.get_setting(DB_PATH, "read_only_mode", False))
    try:
        db.init(DB_PATH)
        db_ok = True
    except Exception:
        db_ok = False
''',
    '''    zfs = zfs_pool_health()
    try:
        db.init(DB_PATH)
        db_ok = True
        read_only_mode = bool(db.get_setting(DB_PATH, "read_only_mode", False))
    except Exception:
        db_ok = False
        read_only_mode = False
''',
    "health DB failure handling",
)

admin = Path("app/admin.py")
replace_once(
    admin,
    "from .converter import recover_pending_transactions\n",
    "from .converter import SOX_ULTRA_BIN, recover_pending_transactions\n",
    "admin Ultra backend import",
)
replace_once(
    admin,
    '''            "tools": {
                "sox": _tool_version(["sox", "--version"]),
                "flac": _tool_version(["flac", "--version"]),
''',
    '''            "tools": {
                "sox": _tool_version(["sox", "--version"]),
                "sox_ultra_37": _tool_version([SOX_ULTRA_BIN, "--version"]),
                "flac": _tool_version(["flac", "--version"]),
''',
    "maintenance Ultra backend version",
)
