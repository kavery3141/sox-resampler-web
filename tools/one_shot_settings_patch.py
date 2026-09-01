from __future__ import annotations

from pathlib import Path

path = Path("app/main.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "from .storage_health import zfs_pool_health\nfrom .temp_cleanup import cleanup_orphan_temps\n",
        "from .storage_health import zfs_pool_health\nfrom .settings_extras import (\n"
        "    build_settings_extras_router,\n"
        "    configure_daily_scan_job,\n"
        "    schedule_deferred_daily_scan,\n"
        ")\n"
        "from .temp_cleanup import cleanup_orphan_temps\n",
    ),
    (
        "app.include_router(build_profiles_router(DB_PATH))\n\n\ndef _refresh_recovery_status",
        "app.include_router(build_profiles_router(DB_PATH))\n"
        "app.include_router(\n"
        "    build_settings_extras_router(\n"
        "        db_path=DB_PATH,\n"
        "        timezone=TIMEZONE,\n"
        "        scheduler=scheduler,\n"
        "        daily_scan=lambda: _daily_scan(),\n"
        "        scanner=scanner,\n"
        "        job_manager=job_manager,\n"
        "    )\n"
        ")\n\n\ndef _refresh_recovery_status",
    ),
    (
        "def _daily_scan() -> None:\n"
        "    # Discovery/maintenance only. Conversion is intentionally never launched by a schedule.\n"
        "    if scanner.snapshot()[\"running\"] or job_manager.is_running():\n"
        "        return\n",
        "def _daily_scan() -> None:\n"
        "    # Discovery/maintenance only. Conversion is intentionally never launched by a schedule.\n"
        "    if scanner.snapshot()[\"running\"] or job_manager.is_running():\n"
        "        next_attempt = schedule_deferred_daily_scan(scheduler, lambda: _daily_scan(), minutes=30)\n"
        "        record_event(\n"
        "            DB_PATH,\n"
        "            job_manager._now(),\n"
        "            \"daily_scan_deferred\",\n"
        "            {\"reason\": \"conversion_or_scan_active\", \"next_attempt\": next_attempt},\n"
        "        )\n"
        "        return\n",
    ),
    (
        "    if not scheduler.running:\n"
        "        scheduler.add_job(\n"
        "            _daily_scan,\n"
        "            \"cron\",\n"
        "            hour=10,\n"
        "            minute=0,\n"
        "            id=\"daily-library-scan\",\n"
        "            replace_existing=True,\n"
        "            coalesce=True,\n"
        "            max_instances=1,\n"
        "        )\n"
        "        scheduler.start()\n",
        "    configure_daily_scan_job(scheduler, lambda: _daily_scan(), DB_PATH)\n"
        "    if not scheduler.running:\n"
        "        scheduler.start()\n",
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one main.py match, found {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
