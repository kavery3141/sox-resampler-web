from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    allowed_ambiguous_first = (
        label in {"retry review pre-hash pass", "retry start operational snapshot"}
        and count == 2
    )
    if count != 1 and not allowed_ambiguous_first:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Database schema version reflects the durable operational snapshot/checksum columns below.
replace_once(
    "app/db.py",
    "SCHEMA_VERSION = 4",
    "SCHEMA_VERSION = 5",
    "schema version",
)

# Converter: optional pre-conversion source checksum, computed only after the user starts a job.
replace_once(
    "app/converter.py",
    "    temp_sha256: str | None = None\n    final_sha256: str | None = None\n",
    "    source_sha256: str | None = None\n    temp_sha256: str | None = None\n    final_sha256: str | None = None\n",
    "conversion result source checksum",
)
replace_once(
    "app/converter.py",
    "def _sha256(path: Path) -> str:\n    h = hashlib.sha256()\n    with path.open(\"rb\") as handle:\n        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b\"\"):\n            h.update(chunk)\n    return h.hexdigest()\n",
    "def _sha256(\n    path: Path,\n    abort_check: Callable[[], bool] | None = None,\n) -> str:\n    h = hashlib.sha256()\n    with path.open(\"rb\") as handle:\n        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b\"\"):\n            if abort_check is not None and abort_check():\n                raise ConversionError(\"Force stop requested by user while hashing; original left untouched\")\n            h.update(chunk)\n    return h.hexdigest()\n",
    "abortable sha256",
)
replace_once(
    "app/converter.py",
    "    cpu_limit_percent: int | None = None,\n    abort_check: Callable[[], bool] | None = None,\n) -> ConversionResult:\n",
    "    cpu_limit_percent: int | None = None,\n    source_pre_hash: bool = False,\n    abort_check: Callable[[], bool] | None = None,\n) -> ConversionResult:\n",
    "convert source pre-hash argument",
)
replace_once(
    "app/converter.py",
    "    try:\n        _check_force_stop(combined_abort_check)\n        proc = _run_sox_command(\n",
    "    try:\n        _check_force_stop(combined_abort_check)\n        if source_pre_hash:\n            result.source_sha256 = _sha256(source, combined_abort_check)\n            if source_identity(source) != identity:\n                raise ConversionError(\n                    \"Source changed while computing pre-conversion SHA-256; refusing conversion\"\n                )\n        _check_force_stop(combined_abort_check)\n        proc = _run_sox_command(\n",
    "pre-hash before SoX",
)
replace_once(
    "app/converter.py",
    "        result.temp_sha256 = _sha256(temp)\n",
    "        result.temp_sha256 = _sha256(temp, combined_abort_check)\n",
    "abortable temp checksum",
)

# Jobs: snapshot operational options independently from DSP presets and source filters.
replace_once(
    "app/jobs.py",
    "                source_filter_json TEXT NOT NULL,\n                album_order_json TEXT NOT NULL,\n",
    "                source_filter_json TEXT NOT NULL,\n                operational_json TEXT NOT NULL DEFAULT '{}',\n                album_order_json TEXT NOT NULL,\n",
    "job operational column",
)
replace_once(
    "app/jobs.py",
    "                error_text TEXT,\n                temp_sha256 TEXT,\n                final_sha256 TEXT,\n",
    "                error_text TEXT,\n                source_sha256 TEXT,\n                temp_sha256 TEXT,\n                final_sha256 TEXT,\n",
    "file source checksum column",
)
replace_once(
    "app/jobs.py",
    "        if \"profile_json\" not in job_columns:\n            conn.execute(\"ALTER TABLE conversion_jobs ADD COLUMN profile_json TEXT\")\n        file_columns = {row[\"name\"] for row in conn.execute(\"PRAGMA table_info(conversion_files)\").fetchall()}\n        if \"defer_count\" not in file_columns:\n            conn.execute(\"ALTER TABLE conversion_files ADD COLUMN defer_count INTEGER NOT NULL DEFAULT 0\")\n",
    "        if \"profile_json\" not in job_columns:\n            conn.execute(\"ALTER TABLE conversion_jobs ADD COLUMN profile_json TEXT\")\n        if \"operational_json\" not in job_columns:\n            conn.execute(\"ALTER TABLE conversion_jobs ADD COLUMN operational_json TEXT NOT NULL DEFAULT '{}'\")\n        file_columns = {row[\"name\"] for row in conn.execute(\"PRAGMA table_info(conversion_files)\").fetchall()}\n        if \"defer_count\" not in file_columns:\n            conn.execute(\"ALTER TABLE conversion_files ADD COLUMN defer_count INTEGER NOT NULL DEFAULT 0\")\n        if \"source_sha256\" not in file_columns:\n            conn.execute(\"ALTER TABLE conversion_files ADD COLUMN source_sha256 TEXT\")\n",
    "job migrations",
)
replace_once(
    "app/jobs.py",
    "        workers: int,\n        source_filter: dict[str, Any],\n    ) -> int:\n",
    "        workers: int,\n        source_filter: dict[str, Any],\n        operational: dict[str, Any] | None = None,\n    ) -> int:\n",
    "create job operational argument",
)
replace_once(
    "app/jobs.py",
    "        album_order = [\n            {\"albumartist\": a[\"albumartist\"], \"album\": a[\"album\"], \"folder\": a[\"folder\"]}\n            for a in review[\"albums\"]\n        ]\n        created_at = self._now()\n",
    "        album_order = [\n            {\"albumartist\": a[\"albumartist\"], \"album\": a[\"album\"], \"folder\": a[\"folder\"]}\n            for a in review[\"albums\"]\n        ]\n        operational_payload = {\n            \"source_pre_hash\": bool((operational or {}).get(\"source_pre_hash\", False)),\n        }\n        created_at = self._now()\n",
    "create operational payload",
)
replace_once(
    "app/jobs.py",
    "                INSERT INTO conversion_jobs(\n                  created_at,status,profile_id,profile_json,workers,source_filter_json,album_order_json\n                ) VALUES(?,?,?,?,?,?,?)\n",
    "                INSERT INTO conversion_jobs(\n                  created_at,status,profile_id,profile_json,workers,source_filter_json,operational_json,album_order_json\n                ) VALUES(?,?,?,?,?,?,?,?)\n",
    "job insert columns",
)
replace_once(
    "app/jobs.py",
    "                    workers,\n                    json.dumps(source_filter, separators=(\",\", \":\")),\n                    json.dumps(album_order, separators=(\",\", \":\")),\n",
    "                    workers,\n                    json.dumps(source_filter, separators=(\",\", \":\")),\n                    json.dumps(operational_payload, separators=(\",\", \":\"), sort_keys=True),\n                    json.dumps(album_order, separators=(\",\", \":\")),\n",
    "job insert values",
)
replace_once(
    "app/jobs.py",
    "            {\"workers\": workers, \"profile_id\": profile_id, \"albums\": len(album_order)},\n",
    "            {\n                \"workers\": workers,\n                \"profile_id\": profile_id,\n                \"albums\": len(album_order),\n                \"source_pre_hash\": operational_payload[\"source_pre_hash\"],\n            },\n",
    "job created event operational detail",
)
replace_once(
    "app/jobs.py",
    "        profile: ResampleProfile,\n        expected_bytes: int,\n    ) -> dict[str, Any]:\n",
    "        profile: ResampleProfile,\n        expected_bytes: int,\n        source_pre_hash: bool = False,\n    ) -> dict[str, Any]:\n",
    "run file pre-hash argument",
)
replace_once(
    "app/jobs.py",
    "                result = convert_file(\n                    source,\n                    profile,\n                    cpu_limit_percent=cpu_limit_percent,\n                )\n                payload = asdict(result)\n                payload[\"cpu_limit_percent\"] = cpu_limit_percent\n",
    "                result = convert_file(\n                    source,\n                    profile,\n                    cpu_limit_percent=cpu_limit_percent,\n                    source_pre_hash=source_pre_hash,\n                )\n                payload = asdict(result)\n                payload[\"cpu_limit_percent\"] = cpu_limit_percent\n                payload[\"source_pre_hash\"] = bool(source_pre_hash)\n",
    "run file converter wiring",
)
replace_once(
    "app/jobs.py",
    "                        SET status=?,finished_at=?,error_text=?,temp_sha256=?,final_sha256=?,result_json=?\n",
    "                        SET status=?,finished_at=?,error_text=?,source_sha256=?,temp_sha256=?,final_sha256=?,result_json=?\n",
    "persist source checksum columns",
)
replace_once(
    "app/jobs.py",
    "                            result.error,\n                            result.temp_sha256,\n                            result.final_sha256,\n",
    "                            result.error,\n                            result.source_sha256,\n                            result.temp_sha256,\n                            result.final_sha256,\n",
    "persist source checksum values",
)
replace_once(
    "app/jobs.py",
    "    def _retry_deferred_files(\n        self,\n        job_id: int,\n        profile: ResampleProfile,\n    ) -> tuple[str, str | None]:\n",
    "    def _retry_deferred_files(\n        self,\n        job_id: int,\n        profile: ResampleProfile,\n        source_pre_hash: bool,\n    ) -> tuple[str, str | None]:\n",
    "deferred retry pre-hash argument",
)
replace_once(
    "app/jobs.py",
    "                profile,\n                int(row[\"source_bytes\"]),\n            )\n",
    "                profile,\n                int(row[\"source_bytes\"]),\n                source_pre_hash,\n            )\n",
    "deferred retry pre-hash pass",
)
replace_once(
    "app/jobs.py",
    "                else:\n                    # Compatibility for jobs created before profile snapshots were introduced.\n                    profile = get_profile(profile_id)\n                album_indices = [\n",
    "                else:\n                    # Compatibility for jobs created before profile snapshots were introduced.\n                    profile = get_profile(profile_id)\n                try:\n                    operational = json.loads(job[\"operational_json\"] or \"{}\")\n                except (TypeError, json.JSONDecodeError):\n                    operational = {}\n                if not isinstance(operational, dict):\n                    operational = {}\n                source_pre_hash = bool(operational.get(\"source_pre_hash\", False))\n                album_indices = [\n",
    "load operational snapshot",
)
replace_once(
    "app/jobs.py",
    "                                profile,\n                                int(r[\"source_bytes\"]),\n                            )\n",
    "                                profile,\n                                int(r[\"source_bytes\"]),\n                                source_pre_hash,\n                            )\n",
    "main wave pre-hash pass",
)
replace_once(
    "app/jobs.py",
    "                deferred_status, deferred_error = self._retry_deferred_files(job_id, profile)\n",
    "                deferred_status, deferred_error = self._retry_deferred_files(\n                    job_id, profile, source_pre_hash\n                )\n",
    "deferred retry invocation",
)
replace_once(
    "app/jobs.py",
    "        result.pop(\"profile_json\", None)\n        result[\"counts\"] = counts\n",
    "        result.pop(\"profile_json\", None)\n        try:\n            operational = json.loads(result.get(\"operational_json\") or \"{}\")\n        except (TypeError, json.JSONDecodeError):\n            operational = {}\n        result[\"operational\"] = operational if isinstance(operational, dict) else {}\n        result.pop(\"operational_json\", None)\n        result[\"counts\"] = counts\n",
    "job response operational snapshot",
)

# API/review: the option is per batch and deliberately separate from profile_override.
replace_once(
    "app/main.py",
    "    profile_override: dict[str, Any] | None = None\n    workers: int = 1\n",
    "    profile_override: dict[str, Any] | None = None\n    workers: int = 1\n    source_pre_hash: bool = False\n",
    "review request pre-hash",
)
replace_once(
    "app/main.py",
    "class RetryStartRequest(BaseModel):\n    workers: int = 1\n    acknowledged_replace_in_place: bool = False\n",
    "class RetryStartRequest(BaseModel):\n    workers: int = 1\n    source_pre_hash: bool = False\n    acknowledged_replace_in_place: bool = False\n",
    "retry request pre-hash",
)
replace_once(
    "app/main.py",
    "    profile: ResampleProfile,\n    workers: int,\n    include_paths: set[str] | None = None,\n) -> dict[str, Any]:\n",
    "    profile: ResampleProfile,\n    workers: int,\n    source_pre_hash: bool = False,\n    include_paths: set[str] | None = None,\n) -> dict[str, Any]:\n",
    "resolved review pre-hash argument",
)
replace_once(
    "app/main.py",
    "    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    return _apply_operational_review_checks(review, reserve)\n",
    "    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n    review[\"source_pre_hash\"] = bool(source_pre_hash)\n    return _apply_operational_review_checks(review, reserve)\n",
    "resolved review operational result",
)
replace_once(
    "app/main.py",
    "        profile=profile,\n        workers=request.workers,\n    )\n",
    "        profile=profile,\n        workers=request.workers,\n        source_pre_hash=request.source_pre_hash,\n    )\n",
    "normal review pre-hash pass",
)
replace_once(
    "app/main.py",
    "def _retry_review(job_id: int, workers: int) -> tuple[dict[str, Any], dict[str, Any]]:\n",
    "def _retry_review(\n    job_id: int, workers: int, source_pre_hash: bool = False\n) -> tuple[dict[str, Any], dict[str, Any]]:\n",
    "retry review signature",
)
replace_once(
    "app/main.py",
    "        profile=spec[\"profile\"],\n        workers=workers,\n        include_paths=set(spec[\"paths\"]),\n    )\n    review[\"retry\"] = {\n",
    "        profile=spec[\"profile\"],\n        workers=workers,\n        source_pre_hash=source_pre_hash,\n        include_paths=set(spec[\"paths\"]),\n    )\n    review[\"retry\"] = {\n",
    "retry review pre-hash pass",
)
replace_once(
    "app/main.py",
    "    workers: int,\n    headroom_db: float | None,\n) -> tuple[dict[str, Any], dict[str, Any]]:\n",
    "    workers: int,\n    headroom_db: float | None,\n    source_pre_hash: bool = False,\n) -> tuple[dict[str, Any], dict[str, Any]]:\n",
    "headroom review signature",
)
# This same profile/workers/include_paths block occurs once more in the headroom helper after the first replacement.
replace_once(
    "app/main.py",
    "        profile=spec[\"profile\"],\n        workers=workers,\n        include_paths=set(spec[\"paths\"]),\n    )\n    review[\"retry\"] = {\n",
    "        profile=spec[\"profile\"],\n        workers=workers,\n        source_pre_hash=source_pre_hash,\n        include_paths=set(spec[\"paths\"]),\n    )\n    review[\"retry\"] = {\n",
    "headroom review pre-hash pass",
)
replace_once(
    "app/main.py",
    "            {\"rates\": request.rates, \"above\": request.above},\n        )\n",
    "            {\"rates\": request.rates, \"above\": request.above},\n            {\"source_pre_hash\": request.source_pre_hash},\n        )\n",
    "normal start operational snapshot",
)
replace_once(
    "app/main.py",
    "def retry_failed_review(job_id: int, workers: int = Query(default=1, ge=1, le=2)) -> dict[str, Any]:\n    review, _ = _retry_review(job_id, workers)\n",
    "def retry_failed_review(\n    job_id: int,\n    workers: int = Query(default=1, ge=1, le=2),\n    source_pre_hash: bool = Query(default=False),\n) -> dict[str, Any]:\n    review, _ = _retry_review(job_id, workers, source_pre_hash)\n",
    "retry review endpoint pre-hash",
)
replace_once(
    "app/main.py",
    "    review, spec = _retry_review(job_id, request.workers)\n",
    "    review, spec = _retry_review(job_id, request.workers, request.source_pre_hash)\n",
    "retry start pre-hash review",
)
replace_once(
    "app/main.py",
    "            request.workers,\n            source_filter,\n        )\n",
    "            request.workers,\n            source_filter,\n            {\"source_pre_hash\": request.source_pre_hash},\n        )\n",
    "retry start operational snapshot",
)
replace_once(
    "app/main.py",
    "    headroom_db: float | None = Query(default=None, ge=-30.0, lt=0.0),\n) -> dict[str, Any]:\n    review, _ = _headroom_retry_review(job_id, workers, headroom_db)\n",
    "    headroom_db: float | None = Query(default=None, ge=-30.0, lt=0.0),\n    source_pre_hash: bool = Query(default=False),\n) -> dict[str, Any]:\n    review, _ = _headroom_retry_review(job_id, workers, headroom_db, source_pre_hash)\n",
    "headroom review endpoint pre-hash",
)
replace_once(
    "app/main.py",
    "    review, spec = _headroom_retry_review(job_id, request.workers, request.headroom_db)\n",
    "    review, spec = _headroom_retry_review(\n        job_id, request.workers, request.headroom_db, request.source_pre_hash\n    )\n",
    "headroom start pre-hash review",
)
# There are now two remaining create_job calls with this shape; target the headroom-specific source_filter context.
replace_once(
    "app/main.py",
    "            spec[\"profile_id\"],\n            request.workers,\n            source_filter,\n        )\n        job_manager.start(new_job_id)\n",
    "            spec[\"profile_id\"],\n            request.workers,\n            source_filter,\n            {\"source_pre_hash\": request.source_pre_hash},\n        )\n        job_manager.start(new_job_id)\n",
    "headroom start operational snapshot",
)

# Reports expose the setting in preflight and the source digest in post-conversion audit output.
replace_once(
    "app/reports.py",
    "        f\"CPU cap per worker: {str(review.get('cpu_limit_percent')) + '%' if review.get('cpu_limit_percent') is not None else 'disabled'}\",\n        f\"Albums: {review.get('album_count') or 0}\",\n",
    "        f\"CPU cap per worker: {str(review.get('cpu_limit_percent')) + '%' if review.get('cpu_limit_percent') is not None else 'disabled'}\",\n        f\"Source SHA-256 pre-hash: {'enabled' if review.get('source_pre_hash') else 'disabled'}\",\n        f\"Albums: {review.get('album_count') or 0}\",\n",
    "review txt pre-hash",
)
replace_once(
    "app/reports.py",
    "        \"workers\",\n        \"cpu_limit_percent\",\n        \"albumartist\",\n",
    "        \"workers\",\n        \"cpu_limit_percent\",\n        \"source_pre_hash\",\n        \"albumartist\",\n",
    "review csv pre-hash field",
)
replace_once(
    "app/reports.py",
    "                    \"cpu_limit_percent\": review.get(\"cpu_limit_percent\") if review.get(\"cpu_limit_percent\") is not None else \"\",\n                    \"albumartist\": album.get(\"albumartist\") or \"\",\n",
    "                    \"cpu_limit_percent\": review.get(\"cpu_limit_percent\") if review.get(\"cpu_limit_percent\") is not None else \"\",\n                    \"source_pre_hash\": bool(review.get(\"source_pre_hash\")),\n                    \"albumartist\": album.get(\"albumartist\") or \"\",\n",
    "review csv pre-hash value",
)
replace_once(
    "app/reports.py",
    "                \"cpu_limit_percent\": payload.get(\"cpu_limit_percent\"),\n                \"temp_sha256\": item.get(\"temp_sha256\"),\n",
    "                \"cpu_limit_percent\": payload.get(\"cpu_limit_percent\"),\n                \"source_sha256\": item.get(\"source_sha256\") or payload.get(\"source_sha256\"),\n                \"temp_sha256\": item.get(\"temp_sha256\"),\n",
    "job report source checksum",
)
replace_once(
    "app/reports.py",
    "    try:\n        album_order = json.loads(job_data.get(\"album_order_json\") or \"[]\")\n    except json.JSONDecodeError:\n        album_order = []\n",
    "    try:\n        album_order = json.loads(job_data.get(\"album_order_json\") or \"[]\")\n    except json.JSONDecodeError:\n        album_order = []\n    operational = _result_payload(job_data.get(\"operational_json\"))\n",
    "job report operational snapshot parse",
)
replace_once(
    "app/reports.py",
    "        \"source_filter\": source_filter,\n        \"album_order\": album_order,\n",
    "        \"source_filter\": source_filter,\n        \"operational\": operational,\n        \"album_order\": album_order,\n",
    "job report operational snapshot",
)
replace_once(
    "app/reports.py",
    "        f\"Final concurrency: {report.get('workers')}\",\n        f\"Files: {totals['files']} total, {totals['completed']} completed, {totals['failed']} failed, {totals['remaining']} remaining\",\n",
    "        f\"Final concurrency: {report.get('workers')}\",\n        f\"Source SHA-256 pre-hash: {'enabled' if (report.get('operational') or {}).get('source_pre_hash') else 'disabled'}\",\n        f\"Files: {totals['files']} total, {totals['completed']} completed, {totals['failed']} failed, {totals['remaining']} remaining\",\n",
    "job txt operational pre-hash",
)
replace_once(
    "app/reports.py",
    "        if item.get(\"final_sha256\"):\n            lines.append(f\"  SHA-256: {item['final_sha256']}\")\n",
    "        if item.get(\"source_sha256\"):\n            lines.append(f\"  Source SHA-256: {item['source_sha256']}\")\n        if item.get(\"final_sha256\"):\n            lines.append(f\"  Final SHA-256: {item['final_sha256']}\")\n",
    "job txt source and final checksums",
)
replace_once(
    "app/reports.py",
    "        \"final_concurrency\",\n        \"job_event_timeline\",\n",
    "        \"final_concurrency\",\n        \"source_pre_hash\",\n        \"job_event_timeline\",\n",
    "job csv pre-hash field",
)
replace_once(
    "app/reports.py",
    "        \"index_refresh_error\",\n        \"final_sha256\",\n",
    "        \"index_refresh_error\",\n        \"source_sha256\",\n        \"final_sha256\",\n",
    "job csv checksum fields",
)
replace_once(
    "app/reports.py",
    "                \"final_concurrency\": report.get(\"workers\") or \"\",\n                \"job_event_timeline\": event_timeline,\n",
    "                \"final_concurrency\": report.get(\"workers\") or \"\",\n                \"source_pre_hash\": bool((report.get(\"operational\") or {}).get(\"source_pre_hash\")),\n                \"job_event_timeline\": event_timeline,\n",
    "job csv pre-hash value",
)
replace_once(
    "app/reports.py",
    "                \"index_refresh_error\": item.get(\"index_refresh_error\") or \"\",\n                \"final_sha256\": item.get(\"final_sha256\") or \"\",\n",
    "                \"index_refresh_error\": item.get(\"index_refresh_error\") or \"\",\n                \"source_sha256\": item.get(\"source_sha256\") or \"\",\n                \"final_sha256\": item.get(\"final_sha256\") or \"\",\n",
    "job csv source checksum value",
)

# Main Advanced UI: explicit per-batch safety control, intentionally excluded from preset payloads.
replace_once(
    "app/static/advanced-presets.js",
    "        <label class=\"advancedCheck\"><input id=\"advAliasing\" type=\"checkbox\">Allow aliasing / imaging</label>\n      </div>\n      <div class=\"advancedActions\">",
    "        <label class=\"advancedCheck\"><input id=\"advAliasing\" type=\"checkbox\">Allow aliasing / imaging</label>\n      </div>\n      <div style=\"margin-top:16px;padding-top:14px;border-top:1px solid var(--border)\"><strong>Per-batch safety</strong><label class=\"advancedCheck\" style=\"margin-top:10px\"><input id=\"advSourcePreHash\" type=\"checkbox\">SHA-256 pre-hash each source FLAC before SoX</label><div class=\"muted\" style=\"margin-top:6px\">Disabled by default. This adds one full source-file read before conversion, is recorded with the job, and is never saved in DSP presets.</div></div>\n      <div class=\"advancedActions\">",
    "advanced per-batch pre-hash UI",
)
replace_once(
    "app/static/advanced-presets.js",
    "  $('presetImportFile').onchange=advancedPreviewImport;\n  $('importPresetButton').onclick=advancedImport;\n}\n",
    "  $('presetImportFile').onchange=advancedPreviewImport;\n  $('importPresetButton').onclick=advancedImport;\n  $('advSourcePreHash').onchange=()=>{resetAck();advancedMessage($('advSourcePreHash').checked?'Source SHA-256 pre-hash enabled for this batch. Refresh Review before conversion.':'Source SHA-256 pre-hash disabled for this batch. Refresh Review before conversion.','info')};\n}\n\nfunction resetOperationalBatchOptions(){\n  if($('advSourcePreHash'))$('advSourcePreHash').checked=false;\n}\n",
    "advanced pre-hash behavior",
)
replace_once(
    "app/static/advanced-presets.js",
    "  box.innerHTML=`<div class=\"resolvedDspTitle\"><strong>Resolved DSP for this batch</strong>${advancedState.override?'<span class=\"badge warn\">Batch override</span>':''}</div><div class=\"resolvedDspGrid\"><span>Target</span><strong>${Number(profile.target_rate).toLocaleString()} Hz</strong><span>Bit depth</span><strong>${esc(String(profile.bit_depth))}</strong><span>Quality</span><strong>${esc(profile.quality)}</strong><span>Passband</span><strong>${esc(profile.passband_percent)}%</strong><span>Phase</span><strong>${esc(profile.phase_percent)}%</strong><span>Aliasing</span><strong>${profile.allow_aliasing?'Allowed':'Disabled'}</strong><span>Compression</span><strong>FLAC ${esc(profile.flac_compression)}</strong><span>Dither</span><strong>${esc(profile.dither||'Automatic TPDF')}</strong><span>Headroom</span><strong>${Number(profile.headroom_db||0).toFixed(1)} dB</strong></div>`;\n",
    "  box.innerHTML=`<div class=\"resolvedDspTitle\"><strong>Resolved DSP for this batch</strong>${advancedState.override?'<span class=\"badge warn\">Batch override</span>':''}</div><div class=\"resolvedDspGrid\"><span>Target</span><strong>${Number(profile.target_rate).toLocaleString()} Hz</strong><span>Bit depth</span><strong>${esc(String(profile.bit_depth))}</strong><span>Quality</span><strong>${esc(profile.quality)}</strong><span>Passband</span><strong>${esc(profile.passband_percent)}%</strong><span>Phase</span><strong>${esc(profile.phase_percent)}%</strong><span>Aliasing</span><strong>${profile.allow_aliasing?'Allowed':'Disabled'}</strong><span>Compression</span><strong>FLAC ${esc(profile.flac_compression)}</strong><span>Dither</span><strong>${esc(profile.dither||'Automatic TPDF')}</strong><span>Headroom</span><strong>${Number(profile.headroom_db||0).toFixed(1)} dB</strong></div><div class=\"resolvedDspTitle\" style=\"margin-top:12px\"><strong>Per-batch safety</strong></div><div class=\"resolvedDspGrid\"><span>Source SHA-256 pre-hash</span><strong>${state.review.source_pre_hash?'Enabled':'Disabled'}</strong></div>`;\n",
    "advanced review operational summary",
)
replace_once(
    "app/static/advanced-presets.js",
    "  if(advancedState.override)body.profile_override={...advancedState.override};\n  return body;\n",
    "  if(advancedState.override)body.profile_override={...advancedState.override};\n  body.source_pre_hash=Boolean($('advSourcePreHash')?.checked);\n  return body;\n",
    "advanced review body pre-hash",
)

# Reset the per-batch safety option as soon as a successfully reviewed job is created.
replace_once(
    "app/static/app.js",
    "state.jobId=d.job_id;$('replaceAck').checked=false;$('ackArea').classList.add('hidden');$('startActions').classList.add('hidden');watchJob(d.job_id,true)",
    "state.jobId=d.job_id;if(typeof resetOperationalBatchOptions==='function')resetOperationalBatchOptions();$('replaceAck').checked=false;$('ackArea').classList.add('hidden');$('startActions').classList.add('hidden');watchJob(d.job_id,true)",
    "reset batch operational options after start",
)

# Retry UIs also expose the per-batch option and reset it for every retry batch.
replace_once(
    "app/static/retry-failed.js",
    "      <div class=\"toolbar\"><label>Concurrent conversions <select id=\"retryFailedWorkers\"><option value=\"1\">1 — Low load</option><option value=\"2\">2 — Faster</option></select></label><button id=\"retryFailedRefresh\">Refresh Retry Review</button></div>\n",
    "      <div class=\"toolbar\"><label>Concurrent conversions <select id=\"retryFailedWorkers\"><option value=\"1\">1 — Low load</option><option value=\"2\">2 — Faster</option></select></label><label><input id=\"retryFailedSourcePreHash\" type=\"checkbox\"> SHA-256 pre-hash sources</label><button id=\"retryFailedRefresh\">Refresh Retry Review</button></div>\n",
    "retry failed pre-hash control",
)
replace_once(
    "app/static/retry-failed.js",
    "    $('retryFailedWorkers').onchange=()=>{retryFailedResetAck();retryFailedRefresh()};\n",
    "    $('retryFailedWorkers').onchange=()=>{retryFailedResetAck();retryFailedRefresh()};\n    $('retryFailedSourcePreHash').onchange=()=>{retryFailedResetAck();retryFailedRefresh()};\n",
    "retry failed pre-hash change",
)
replace_once(
    "app/static/retry-failed.js",
    "retryFailedInstall();retryFailedState.sourceJobId=Number(jobId);$('retryFailedWorkers').value='1';$('retryFailedCard').classList.remove('hidden');\n",
    "retryFailedInstall();retryFailedState.sourceJobId=Number(jobId);$('retryFailedWorkers').value='1';$('retryFailedSourcePreHash').checked=false;$('retryFailedCard').classList.remove('hidden');\n",
    "retry failed pre-hash default",
)
replace_once(
    "app/static/retry-failed.js",
    "    const workers=Number($('retryFailedWorkers').value||1);\n    const response=await fetch(`/api/convert/jobs/${jobId}/retry-review?workers=${workers}`);\n",
    "    const workers=Number($('retryFailedWorkers').value||1);\n    const params=new URLSearchParams({workers:String(workers),source_pre_hash:String(Boolean($('retryFailedSourcePreHash').checked))});\n    const response=await fetch(`/api/convert/jobs/${jobId}/retry-review?${params}`);\n",
    "retry failed review query",
)
replace_once(
    "app/static/retry-failed.js",
    "<div class=\"reviewMetric\"><span>ZFS</span><strong>${review.zfs?.ok?'Healthy':'Blocked'}</strong></div>`;\n",
    "<div class=\"reviewMetric\"><span>ZFS</span><strong>${review.zfs?.ok?'Healthy':'Blocked'}</strong></div><div class=\"reviewMetric\"><span>Source pre-hash</span><strong>${review.source_pre_hash?'Enabled':'Disabled'}</strong></div>`;\n",
    "retry failed review summary",
)
replace_once(
    "app/static/retry-failed.js",
    "body:JSON.stringify({workers:Number($('retryFailedWorkers').value||1),acknowledged_replace_in_place:true})",
    "body:JSON.stringify({workers:Number($('retryFailedWorkers').value||1),source_pre_hash:Boolean($('retryFailedSourcePreHash').checked),acknowledged_replace_in_place:true})",
    "retry failed start body",
)

replace_once(
    "app/static/retry-headroom.js",
    "        <label>Concurrent conversions <select id=\"retryHeadroomWorkers\"><option value=\"1\">1 — Low load</option><option value=\"2\">2 — Faster</option></select></label>\n        <button id=\"retryHeadroomRefresh\">Refresh Headroom Review</button>\n",
    "        <label>Concurrent conversions <select id=\"retryHeadroomWorkers\"><option value=\"1\">1 — Low load</option><option value=\"2\">2 — Faster</option></select></label>\n        <label><input id=\"retryHeadroomSourcePreHash\" type=\"checkbox\"> SHA-256 pre-hash sources</label>\n        <button id=\"retryHeadroomRefresh\">Refresh Headroom Review</button>\n",
    "headroom pre-hash control",
)
replace_once(
    "app/static/retry-headroom.js",
    "    $('retryHeadroomWorkers').onchange=()=>{retryHeadroomResetAck();retryHeadroomRefresh()};\n",
    "    $('retryHeadroomWorkers').onchange=()=>{retryHeadroomResetAck();retryHeadroomRefresh()};\n    $('retryHeadroomSourcePreHash').onchange=()=>{retryHeadroomResetAck();retryHeadroomRefresh()};\n",
    "headroom pre-hash change",
)
replace_once(
    "app/static/retry-headroom.js",
    "    $('retryHeadroomDb').value=Number(options.default_headroom_db).toFixed(1);$('retryHeadroomWorkers').value='1';$('retryHeadroomCard').classList.remove('hidden');\n",
    "    $('retryHeadroomDb').value=Number(options.default_headroom_db).toFixed(1);$('retryHeadroomWorkers').value='1';$('retryHeadroomSourcePreHash').checked=false;$('retryHeadroomCard').classList.remove('hidden');\n",
    "headroom pre-hash default",
)
replace_once(
    "app/static/retry-headroom.js",
    "    const params=new URLSearchParams({workers:String(workers),headroom_db:String(headroom)});\n",
    "    const params=new URLSearchParams({workers:String(workers),headroom_db:String(headroom),source_pre_hash:String(Boolean($('retryHeadroomSourcePreHash').checked))});\n",
    "headroom review query",
)
replace_once(
    "app/static/retry-headroom.js",
    "<div class=\"reviewMetric\"><span>ZFS</span><strong>${review.zfs?.ok?'Healthy':'Blocked'}</strong></div>`;\n",
    "<div class=\"reviewMetric\"><span>ZFS</span><strong>${review.zfs?.ok?'Healthy':'Blocked'}</strong></div><div class=\"reviewMetric\"><span>Source pre-hash</span><strong>${review.source_pre_hash?'Enabled':'Disabled'}</strong></div>`;\n",
    "headroom review summary",
)
replace_once(
    "app/static/retry-headroom.js",
    "    const body={workers:Number($('retryHeadroomWorkers').value||1),headroom_db:Number($('retryHeadroomDb').value),acknowledged_replace_in_place:true};\n",
    "    const body={workers:Number($('retryHeadroomWorkers').value||1),headroom_db:Number($('retryHeadroomDb').value),source_pre_hash:Boolean($('retryHeadroomSourcePreHash').checked),acknowledged_replace_in_place:true};\n",
    "headroom start body",
)

# Resource-control UI existed but was not loaded by the addon chain; wire it now.
replace_once(
    "app/static/ui.js",
    "loadUiAddon('/static/update-status.js');",
    "loadUiAddon('/static/update-status.js');\nloadUiAddon('/static/resource-control.js');",
    "load resource-control UI",
)

# Integration and wiring tests.
replace_once(
    "tests/test_converter_integration.py",
    "import os\nimport subprocess\n",
    "import hashlib\nimport os\nimport subprocess\n",
    "integration hashlib import",
)
replace_once(
    "tests/test_converter_integration.py",
    "            result = convert_file(source, FACTORY_DEFAULTS)\n",
    "            expected_source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()\n            result = convert_file(source, FACTORY_DEFAULTS, source_pre_hash=True)\n",
    "integration pre-hash invocation",
)
replace_once(
    "tests/test_converter_integration.py",
    "            self.assertIsNotNone(result.temp_sha256)\n            self.assertEqual(result.temp_sha256, result.final_sha256)\n",
    "            self.assertEqual(result.source_sha256, expected_source_sha256)\n            self.assertIsNotNone(result.temp_sha256)\n            self.assertEqual(result.temp_sha256, result.final_sha256)\n",
    "integration source checksum assertion",
)
replace_once(
    "tests/test_job_cpu_limit.py",
    "            convert.assert_called_once_with(source, FACTORY_DEFAULTS, cpu_limit_percent=55)\n",
    "            convert.assert_called_once_with(\n                source, FACTORY_DEFAULTS, cpu_limit_percent=55, source_pre_hash=False\n            )\n",
    "job wiring default pre-hash assertion",
)
replace_once(
    "tests/test_job_cpu_limit.py",
    "            self.assertEqual(payload[\"cpu_limit_percent\"], 55)\n            self.assertEqual(payload[\"status\"], \"failed\")\n",
    "            self.assertEqual(payload[\"cpu_limit_percent\"], 55)\n            self.assertFalse(payload[\"source_pre_hash\"])\n            self.assertEqual(payload[\"status\"], \"failed\")\n\n    def test_job_passes_enabled_source_pre_hash_to_converter(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp)\n            music = root / \"music\"\n            music.mkdir()\n            db_path = root / \"data\" / \"test.db\"\n            db.init(db_path)\n            manager = ConversionJobManager(db_path, music, \"America/Indiana/Indianapolis\")\n            source = music / \"track.flac\"\n            source.write_bytes(b\"synthetic source\")\n            with db.session(db_path) as conn:\n                job_cur = conn.execute(\n                    \"\"\"\n                    INSERT INTO conversion_jobs(\n                      created_at,status,profile_id,profile_json,workers,source_filter_json,operational_json,album_order_json\n                    ) VALUES(?,?,?,?,?,?,?,?)\n                    \"\"\",\n                    (manager._now(), \"running\", FACTORY_DEFAULTS.id, None, 1, \"{}\", '{\"source_pre_hash\":true}', \"[]\"),\n                )\n                job_id = int(job_cur.lastrowid)\n                file_cur = conn.execute(\n                    \"\"\"\n                    INSERT INTO conversion_files(\n                      job_id,album_index,file_index,albumartist,album,path,source_bytes,status\n                    ) VALUES(?,?,?,?,?,?,?,?)\n                    \"\"\",\n                    (job_id, 0, 0, \"Artist\", \"Album\", str(source), source.stat().st_size, \"pending\"),\n                )\n                file_id = int(file_cur.lastrowid)\n\n            synthetic = ConversionResult(\n                source=str(source),\n                status=\"failed\",\n                command=[\"synthetic\"],\n                source_sha256=\"abc123\",\n                error=\"synthetic failure\",\n            )\n            with patch(\"app.jobs.configured_cpu_limit\", return_value=None), patch(\n                \"app.jobs.convert_file\", return_value=synthetic\n            ) as convert:\n                payload = manager._run_file(\n                    job_id, file_id, str(source), FACTORY_DEFAULTS, source.stat().st_size, True\n                )\n\n            convert.assert_called_once_with(\n                source, FACTORY_DEFAULTS, cpu_limit_percent=None, source_pre_hash=True\n            )\n            self.assertTrue(payload[\"source_pre_hash\"])\n            with db.session(db_path) as conn:\n                stored = conn.execute(\"SELECT source_sha256 FROM conversion_files WHERE id=?\", (file_id,)).fetchone()\n            self.assertEqual(stored[\"source_sha256\"], \"abc123\")\n",
    "job wiring enabled pre-hash test",
)

replace_once(
    "README.md",
    "Each source FLAC is converted to a hidden same-directory temporary file. Before replacement the app verifies technical output properties, user metadata and embedded pictures, performs a full FLAC decode test, checks clipping, preserves filesystem metadata, revalidates source identity, and hashes the verified output. Replacement uses a persistent crash-recovery journal and an atomic same-filesystem exchange. The old source remains available until the new file has passed final verification; failures leave the original untouched.\n",
    "Each source FLAC is converted to a hidden same-directory temporary file. Before replacement the app verifies technical output properties, user metadata and embedded pictures, performs a full FLAC decode test, checks clipping, preserves filesystem metadata, revalidates source identity, and hashes the verified output. Advanced batch safety can optionally SHA-256 pre-hash each source before SoX; this is disabled by default, is recorded in the job/report, and is deliberately not stored in DSP presets. Replacement uses a persistent crash-recovery journal and an atomic same-filesystem exchange. The old source remains available until the new file has passed final verification; failures leave the original untouched.\n",
    "README source pre-hash",
)

print("Source pre-hash patch applied successfully")
