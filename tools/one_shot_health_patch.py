from __future__ import annotations

from pathlib import Path


path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "from .converter import recover_pending_transactions\n",
        "from .converter import SOX_ULTRA_BIN, recover_pending_transactions\n"
        "from .health_status import summarize_health\n",
    ),
    (
        '''    sox = _tool_version(["sox", "--version"])
    flac = _tool_version(["flac", "--version"])
    zfs = zfs_pool_health()
    try:
        db.init(DB_PATH)
        db_ok = True
    except Exception:
        db_ok = False
    healthy = bool(music_exists and music_readable and data_writable and sox and flac and db_ok)
    return {
        "status": "ok" if healthy else "degraded",
''',
        '''    sox = _tool_version(["sox", "--version"])
    ultra_sox = _tool_version([SOX_ULTRA_BIN, "--version"])
    flac = _tool_version(["flac", "--version"])
    zfs = zfs_pool_health()
    read_only_mode = bool(db.get_setting(DB_PATH, "read_only_mode", False))
    try:
        db.init(DB_PATH)
        db_ok = True
    except Exception:
        db_ok = False
    summary = summarize_health(
        music_exists=music_exists,
        music_readable=music_readable,
        music_writable=music_writable,
        data_exists=data_exists,
        data_writable=data_writable,
        db_ok=db_ok,
        stock_sox=sox,
        ultra_sox=ultra_sox,
        flac=flac,
        zfs=zfs,
        read_only_mode=read_only_mode,
    )
    return {
        **summary,
''',
    ),
    (
        '        "tools": {"sox": sox, "flac": flac},\n',
        '        "tools": {"sox": sox, "sox_ultra_37": ultra_sox, "flac": flac},\n',
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one main.py match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
