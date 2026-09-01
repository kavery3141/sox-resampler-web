from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# admin.py: move timing math into the reusable durable-event timing module, keeping the old
# private function name as a compatibility wrapper for existing tests/callers.
admin_path = Path("app/admin.py")
replace_once(
    "app/admin.py",
    "from .job_maintenance import clear_terminal_history, history_summary\n",
    "from .job_maintenance import clear_terminal_history, history_summary\nfrom .job_timing import job_runtime_times\n",
    "admin timing import",
)
admin = admin_path.read_text(encoding="utf-8")
timestamp_start = admin.index("def _timestamp(value: str | None) -> float | None:\n")
recovery_start = admin.index("def _recovery_summary(", timestamp_start)
admin = admin[:timestamp_start] + admin[recovery_start:]
admin_path.write_text(admin, encoding="utf-8")
admin = admin_path.read_text(encoding="utf-8")
runtime_start = admin.index("def _job_runtime_times(db_path: Path, job_id: int)")
build_start = admin.index("def build_admin_router(\n", runtime_start)
wrapper = (
    "def _job_runtime_times(db_path: Path, job_id: int) -> dict[str, float | int | str | None]:\n"
    "    return job_runtime_times(db_path, job_id)\n\n\n"
)
admin_path.write_text(admin[:runtime_start] + wrapper + admin[build_start:], encoding="utf-8")

# reports.py: make the same durable timing breakdown part of the audit report.
replace_once(
    "app/reports.py",
    "from .job_events import load_job_events\n",
    "from .job_events import load_job_events\nfrom .job_timing import job_runtime_times\n",
    "reports timing import",
)
replace_once(
    "app/reports.py",
    '        "events": events,\n        "totals": {\n',
    '        "events": events,\n        "timing": job_runtime_times(db_path, job_id),\n        "totals": {\n',
    "job report timing payload",
)
replace_once(
    "app/reports.py",
    '        f"Finished: {report.get(\'finished_at\') or \'\'}",\n        f"Preset: {profile.get(\'name\') or report.get(\'profile_id\') or \'\'}",\n',
    '        f"Finished: {report.get(\'finished_at\') or \'\'}",\n        f"Wall time seconds: {(report.get(\'timing\') or {}).get(\'wall_seconds\', 0)}",\n        f"File-active seconds: {(report.get(\'timing\') or {}).get(\'active_seconds\', 0)}",\n        f"Paused seconds: {(report.get(\'timing\') or {}).get(\'paused_seconds\', 0)}",\n        f"Interrupted seconds: {(report.get(\'timing\') or {}).get(\'interrupted_seconds\', 0)}",\n        f"Idle/between-file seconds: {(report.get(\'timing\') or {}).get(\'idle_seconds\', 0)}",\n        f"Preset: {profile.get(\'name\') or report.get(\'profile_id\') or \'\'}",\n',
    "job txt timing lines",
)
replace_once(
    "app/reports.py",
    '        "source_pre_hash",\n        "job_event_timeline",\n',
    '        "source_pre_hash",\n        "job_wall_seconds",\n        "job_active_seconds",\n        "job_paused_seconds",\n        "job_interrupted_seconds",\n        "job_idle_seconds",\n        "job_event_timeline",\n',
    "job csv timing fields",
)
replace_once(
    "app/reports.py",
    '                "source_pre_hash": bool((report.get("operational") or {}).get("source_pre_hash")),\n                "job_event_timeline": event_timeline,\n',
    '                "source_pre_hash": bool((report.get("operational") or {}).get("source_pre_hash")),\n                "job_wall_seconds": (report.get("timing") or {}).get("wall_seconds", 0),\n                "job_active_seconds": (report.get("timing") or {}).get("active_seconds", 0),\n                "job_paused_seconds": (report.get("timing") or {}).get("paused_seconds", 0),\n                "job_interrupted_seconds": (report.get("timing") or {}).get("interrupted_seconds", 0),\n                "job_idle_seconds": (report.get("timing") or {}).get("idle_seconds", 0),\n                "job_event_timeline": event_timeline,\n',
    "job csv timing values",
)

# live-stats.js: display truly paused, interrupted, and ordinary between-file idle separately.
replace_once(
    "app/static/live-stats.js",
    '      <div class="telemetryStat"><span>File-active time</span><strong id="jobActiveTime">—</strong></div>\n      <div class="telemetryStat"><span>Paused / idle</span><strong id="jobPausedTime">—</strong></div>\n      <div class="telemetryStat"><span>NAS read</span><strong id="jobNasRead">—</strong></div>\n',
    '      <div class="telemetryStat"><span>File-active time</span><strong id="jobActiveTime">—</strong></div>\n      <div class="telemetryStat"><span>Paused time</span><strong id="jobPausedTime">—</strong></div>\n      <div class="telemetryStat"><span>Interrupted time</span><strong id="jobInterruptedTime">—</strong></div>\n      <div class="telemetryStat"><span>Idle / between files</span><strong id="jobIdleTime">—</strong></div>\n      <div class="telemetryStat"><span>NAS read</span><strong id="jobNasRead">—</strong></div>\n',
    "live timing telemetry cards",
)
replace_once(
    "app/static/live-stats.js",
    "    $('jobActiveTime').textContent=liveSeconds(data.job_time?.active_seconds||0);\n    $('jobPausedTime').textContent=liveSeconds(data.job_time?.paused_or_idle_seconds||0);\n",
    "    $('jobActiveTime').textContent=liveSeconds(data.job_time?.active_seconds||0);\n    $('jobPausedTime').textContent=liveSeconds(data.job_time?.paused_seconds||0);\n    $('jobInterruptedTime').textContent=liveSeconds(data.job_time?.interrupted_seconds||0);\n    $('jobIdleTime').textContent=liveSeconds(data.job_time?.idle_seconds||0);\n",
    "live timing telemetry update",
)
replace_once(
    "app/static/live-stats.js",
    "    $('jobNasRead').textContent='—';$('jobNasWrite').textContent='—';$('jobCpuMemory').textContent='—';\n",
    "    $('jobNasRead').textContent='—';$('jobNasWrite').textContent='—';$('jobCpuMemory').textContent='—';\n    $('jobActiveTime').textContent='—';$('jobPausedTime').textContent='—';$('jobInterruptedTime').textContent='—';$('jobIdleTime').textContent='—';\n",
    "live timing telemetry error state",
)

# test_admin.py: assert idle separately and verify a durable pause/resume interval.
replace_once(
    "tests/test_admin.py",
    "from app.jobs import ensure_tables\n",
    "from app.job_events import record_job_event\nfrom app.jobs import ensure_tables\n",
    "admin test event import",
)
replace_once(
    "tests/test_admin.py",
    '            self.assertEqual(result["active_seconds"], 30.0)\n            self.assertEqual(result["paused_or_idle_seconds"], 10.0)\n            self.assertEqual(result["active_files"], 0)\n\n\nif __name__ == "__main__":\n',
    '            self.assertEqual(result["active_seconds"], 30.0)\n            self.assertEqual(result["paused_seconds"], 0.0)\n            self.assertEqual(result["interrupted_seconds"], 0.0)\n            self.assertEqual(result["idle_seconds"], 10.0)\n            self.assertEqual(result["paused_or_idle_seconds"], 10.0)\n            self.assertEqual(result["active_files"], 0)\n\n    def test_job_runtime_times_separates_real_pause_from_between_file_idle(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            db_path = Path(tmp) / "runtime-paused.db"\n            db.init(db_path)\n            ensure_tables(db_path)\n            with db.session(db_path) as conn:\n                cur = conn.execute(\n                    """\n                    INSERT INTO conversion_jobs(\n                      created_at,started_at,finished_at,status,profile_id,workers,\n                      source_filter_json,album_order_json\n                    ) VALUES(?,?,?,?,?,?,?,?)\n                    """,\n                    (\n                        "2026-09-01T10:00:00-04:00",\n                        "2026-09-01T10:00:00-04:00",\n                        "2026-09-01T10:00:35-04:00",\n                        "completed",\n                        "foobar-ultra-37-48k",\n                        1,\n                        "{}",\n                        "[]",\n                    ),\n                )\n                job_id = int(cur.lastrowid)\n                for index, filename, started, finished in [\n                    (0, "a.flac", "2026-09-01T10:00:00-04:00", "2026-09-01T10:00:10-04:00"),\n                    (1, "b.flac", "2026-09-01T10:00:20-04:00", "2026-09-01T10:00:30-04:00"),\n                ]:\n                    conn.execute(\n                        """\n                        INSERT INTO conversion_files(\n                          job_id,album_index,file_index,albumartist,album,path,source_bytes,status,\n                          started_at,finished_at\n                        ) VALUES(?,?,?,?,?,?,?,?,?,?)\n                        """,\n                        (job_id, 0, index, "Artist", "Album", f"/music/{filename}", 1000, "completed", started, finished),\n                    )\n            record_job_event(\n                db_path, job_id, "2026-09-01T10:00:10-04:00", "job_finished", {"status": "paused"}\n            )\n            record_job_event(\n                db_path, job_id, "2026-09-01T10:00:20-04:00", "job_resumed", {"previous_status": "paused", "workers": 1}\n            )\n            record_job_event(\n                db_path, job_id, "2026-09-01T10:00:35-04:00", "job_finished", {"status": "completed"}\n            )\n            result = _job_runtime_times(db_path, job_id)\n            self.assertEqual(result["wall_seconds"], 35.0)\n            self.assertEqual(result["active_seconds"], 20.0)\n            self.assertEqual(result["paused_seconds"], 10.0)\n            self.assertEqual(result["interrupted_seconds"], 0.0)\n            self.assertEqual(result["idle_seconds"], 5.0)\n            self.assertEqual(result["paused_or_idle_seconds"], 15.0)\n\n\nif __name__ == "__main__":\n',
    "admin separated timing tests",
)

# test_reports.py: prove timing is present in both audit formats.
replace_once(
    "tests/test_reports.py",
    '        self.assertEqual(report["totals"]["savings_bytes"], 400)\n        txt = render_job_txt(report)\n',
    '        self.assertEqual(report["totals"]["savings_bytes"], 400)\n        self.assertEqual(report["timing"]["wall_seconds"], 60.0)\n        self.assertEqual(report["timing"]["active_seconds"], 30.0)\n        self.assertEqual(report["timing"]["idle_seconds"], 30.0)\n        txt = render_job_txt(report)\n',
    "report timing assertions",
)
replace_once(
    "tests/test_reports.py",
    '        self.assertIn("SHA-256: abc", txt)\n        self.assertIn("400", csv_text)\n        self.assertIn("America/Indiana/Indianapolis", csv_text)\n',
    '        self.assertIn("SHA-256: abc", txt)\n        self.assertIn("File-active seconds: 30.0", txt)\n        self.assertIn("Idle/between-file seconds: 30.0", txt)\n        self.assertIn("job_paused_seconds", csv_text)\n        self.assertIn("400", csv_text)\n        self.assertIn("America/Indiana/Indianapolis", csv_text)\n',
    "report timing render assertions",
)
