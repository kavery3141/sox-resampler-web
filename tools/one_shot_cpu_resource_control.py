from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write_new(path: str, content: str) -> None:
    file_path = Path(path)
    if file_path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def patch_dockerfile() -> None:
    replace_once(
        "Dockerfile",
        "       util-linux \\\n       zfsutils-linux \\\n",
        "       util-linux \\\n       cpulimit \\\n       zfsutils-linux \\\n",
        "Dockerfile cpulimit package",
    )


def patch_main() -> None:
    replace_once(
        "app/main.py",
        "from .profiles_api import build_profiles_router\nfrom .reports import (\n",
        "from .profiles_api import build_profiles_router\nfrom .resource_control import (\n    build_resource_control_router,\n    configured_cpu_limit,\n    cpulimit_available,\n)\nfrom .reports import (\n",
        "main resource-control import",
    )
    replace_once(
        "app/main.py",
        "app.include_router(build_profiles_router(DB_PATH))\napp.include_router(build_update_router(APP_VERSION))\napp.include_router(\n",
        "app.include_router(build_profiles_router(DB_PATH))\napp.include_router(build_update_router(APP_VERSION))\napp.include_router(build_resource_control_router(DB_PATH, TIMEZONE, job_manager))\napp.include_router(\n",
        "main resource-control router",
    )
    replace_once(
        "app/main.py",
        "    flac = _tool_version([\"flac\", \"--version\"])\n    zfs = zfs_pool_health()\n    try:\n        db.init(DB_PATH)\n        db_ok = True\n        read_only_mode = bool(db.get_setting(DB_PATH, \"read_only_mode\", False))\n    except Exception:\n        db_ok = False\n        read_only_mode = False\n",
        "    flac = _tool_version([\"flac\", \"--version\"])\n    cpu_limiter = _tool_version([\"cpulimit\", \"-h\"]) if cpulimit_available() else None\n    zfs = zfs_pool_health()\n    try:\n        db.init(DB_PATH)\n        db_ok = True\n        read_only_mode = bool(db.get_setting(DB_PATH, \"read_only_mode\", False))\n        cpu_limit_percent = configured_cpu_limit(DB_PATH)\n    except Exception:\n        db_ok = False\n        read_only_mode = False\n        cpu_limit_percent = None\n",
        "main health cpu limiter state",
    )
    replace_once(
        "app/main.py",
        "        zfs=zfs,\n        read_only_mode=read_only_mode,\n    )\n",
        "        zfs=zfs,\n        read_only_mode=read_only_mode,\n        cpu_limit_percent=cpu_limit_percent,\n        cpu_limiter_available=bool(cpu_limiter),\n    )\n",
        "main health summary cpu args",
    )
    replace_once(
        "app/main.py",
        '        "tools": {"sox": sox, "sox_ultra_37": ultra_sox, "flac": flac},\n',
        '        "tools": {"sox": sox, "sox_ultra_37": ultra_sox, "flac": flac, "cpulimit": cpu_limiter},\n        "resource_control": {\n            "cpu_limit_percent": cpu_limit_percent,\n            "enabled": cpu_limit_percent is not None,\n            "scope": "per-worker-sox",\n        },\n',
        "main health tools",
    )
    replace_once(
        "app/main.py",
        '        "read_only_mode": bool(db.get_setting(DB_PATH, "read_only_mode", False)),\n        "library": db.library_summary(DB_PATH),\n',
        '        "read_only_mode": bool(db.get_setting(DB_PATH, "read_only_mode", False)),\n        "cpu_limit_percent": configured_cpu_limit(DB_PATH),\n        "library": db.library_summary(DB_PATH),\n',
        "main status cpu limit",
    )


def patch_health_status() -> None:
    replace_once(
        "app/health_status.py",
        "    zfs: dict[str, Any],\n    read_only_mode: bool,\n) -> dict[str, Any]:\n",
        "    zfs: dict[str, Any],\n    read_only_mode: bool,\n    cpu_limit_percent: int | None = None,\n    cpu_limiter_available: bool = True,\n) -> dict[str, Any]:\n",
        "health signature",
    )
    replace_once(
        "app/health_status.py",
        '    if read_only_mode:\n        conversion_blockers.append("Read-only Scan Mode is enabled")\n\n    health_reasons = list(dict.fromkeys(health_reasons))\n',
        '    if read_only_mode:\n        conversion_blockers.append("Read-only Scan Mode is enabled")\n    if cpu_limit_percent is not None and not cpu_limiter_available:\n        conversion_blockers.append(\n            "A conversion CPU cap is configured but the cpulimit runtime is unavailable"\n        )\n\n    health_reasons = list(dict.fromkeys(health_reasons))\n',
        "health cpu blocker",
    )


def patch_converter() -> None:
    replace_once(
        "app/converter.py",
        "import re\nimport signal\nimport stat\nimport subprocess\n",
        "import re\nimport shutil\nimport signal\nimport stat\nimport subprocess\n",
        "converter shutil import",
    )
    replace_once(
        "app/converter.py",
        "from .profiles import ResampleProfile\nfrom .transactions import ReplacementJournal, recover_journals\n",
        "from .profiles import ResampleProfile\nfrom .resource_control import CPU_LIMIT_MAX, CPU_LIMIT_MIN\nfrom .transactions import ReplacementJournal, recover_journals\n",
        "converter resource constants import",
    )
    replace_once(
        "app/converter.py",
        "    return command\n\n\ndef preview(source: Path, profile: ResampleProfile) -> dict[str, Any]:\n",
        '''    return command\n\n\ndef apply_cpu_limit(command: list[str], cpu_limit_percent: int | None) -> list[str]:\n    """Wrap a SoX command with a per-worker CPU throttle when configured.\n\n    ``cpulimit`` measures percentage relative to one logical CPU. Each conversion worker receives\n    its own cap, so two workers may together consume up to roughly twice the configured value.\n    The wrapper is operational only; it does not alter DSP settings or the resampling preset.\n    """\n    if cpu_limit_percent is None:\n        return command\n    try:\n        limit = int(cpu_limit_percent)\n    except (TypeError, ValueError) as exc:\n        raise ConversionError("CPU limit must be an integer percentage") from exc\n    if not CPU_LIMIT_MIN <= limit <= CPU_LIMIT_MAX:\n        raise ConversionError(\n            f"CPU limit must be between {CPU_LIMIT_MIN} and {CPU_LIMIT_MAX} percent per worker"\n        )\n    if shutil.which("cpulimit") is None:\n        raise ProfileUnavailable(\n            "A conversion CPU cap is configured but the cpulimit runtime is unavailable"\n        )\n    return ["cpulimit", "-q", "-l", str(limit), "--", *command]\n\n\ndef preview(\n    source: Path,\n    profile: ResampleProfile,\n    *,\n    cpu_limit_percent: int | None = None,\n) -> dict[str, Any]:\n''',
        "converter cpu wrapper",
    )
    replace_once(
        "app/converter.py",
        "        command = build_sox_command(source, temp, profile, source_bits)\n        profile_available = True\n",
        "        command = build_sox_command(source, temp, profile, source_bits)\n        command = apply_cpu_limit(command, cpu_limit_percent)\n        profile_available = True\n",
        "converter preview cpu wrapper",
    )
    replace_once(
        "app/converter.py",
        "    *,\n    abort_check: Callable[[], bool] | None = None,\n) -> ConversionResult:\n",
        "    *,\n    cpu_limit_percent: int | None = None,\n    abort_check: Callable[[], bool] | None = None,\n) -> ConversionResult:\n",
        "converter convert signature",
    )
    replace_once(
        "app/converter.py",
        "    command = build_sox_command(source, temp, profile, src_bits)\n    result = ConversionResult(\n",
        "    command = build_sox_command(source, temp, profile, src_bits)\n    command = apply_cpu_limit(command, cpu_limit_percent)\n    result = ConversionResult(\n",
        "converter execution cpu wrapper",
    )


def patch_review() -> None:
    replace_once(
        "app/review.py",
        "from .converter import preview\nfrom .profiles import ResampleProfile\n",
        "from .converter import preview\nfrom .profiles import ResampleProfile\nfrom .resource_control import configured_cpu_limit\n",
        "review cpu import",
    )
    replace_once(
        "app/review.py",
        "    hard_blockers: list[str] = []\n    seen_exact_paths: set[str] = set()\n\n    with db.session(db_path) as conn:\n",
        "    hard_blockers: list[str] = []\n    seen_exact_paths: set[str] = set()\n    cpu_limit_percent = configured_cpu_limit(db_path)\n\n    with db.session(db_path) as conn:\n",
        "review configured cpu limit",
    )
    replace_once(
        "app/review.py",
        "                        detail = preview(resolved_source, profile)\n",
        "                        detail = preview(\n                            resolved_source,\n                            profile,\n                            cpu_limit_percent=cpu_limit_percent,\n                        )\n",
        "review preview cpu limit",
    )
    replace_once(
        "app/review.py",
        '        "workers": workers,\n        "albums": albums,\n',
        '        "workers": workers,\n        "cpu_limit_percent": cpu_limit_percent,\n        "albums": albums,\n',
        "review response cpu limit",
    )


def patch_jobs() -> None:
    replace_once(
        "app/jobs.py",
        "from .profiles import ResampleProfile, get_profile, profile_from_dict\nfrom .storage_health import zfs_pool_health\n",
        "from .profiles import ResampleProfile, get_profile, profile_from_dict\nfrom .resource_control import configured_cpu_limit\nfrom .storage_health import zfs_pool_health\n",
        "jobs cpu import",
    )
    replace_once(
        "app/jobs.py",
        "                result = convert_file(source, profile)\n                payload = asdict(result)\n                payload[\"advisory_busy_guard_supported\"] = bool(guard.supported)\n",
        "                cpu_limit_percent = configured_cpu_limit(self.db_path)\n                result = convert_file(\n                    source,\n                    profile,\n                    cpu_limit_percent=cpu_limit_percent,\n                )\n                payload = asdict(result)\n                payload[\"cpu_limit_percent\"] = cpu_limit_percent\n                payload[\"advisory_busy_guard_supported\"] = bool(guard.supported)\n",
        "jobs cpu execution wiring",
    )


def patch_reports() -> None:
    replace_once(
        "app/reports.py",
        '        f"Workers: {review.get(\'workers\') or \'\'}",\n        f"Albums: {review.get(\'album_count\') or 0}",\n',
        '        f"Workers: {review.get(\'workers\') or \'\'}",\n        f"CPU cap per worker: {str(review.get(\'cpu_limit_percent\')) + \'%\' if review.get(\'cpu_limit_percent\') is not None else \'disabled\'}",\n        f"Albums: {review.get(\'album_count\') or 0}",\n',
        "reports review txt cpu",
    )
    replace_once(
        "app/reports.py",
        '        "workers",\n        "albumartist",\n',
        '        "workers",\n        "cpu_limit_percent",\n        "albumartist",\n',
        "reports review csv field",
    )
    replace_once(
        "app/reports.py",
        '                    "workers": review.get("workers") or "",\n                    "albumartist": album.get("albumartist") or "",\n',
        '                    "workers": review.get("workers") or "",\n                    "cpu_limit_percent": review.get("cpu_limit_percent") if review.get("cpu_limit_percent") is not None else "",\n                    "albumartist": album.get("albumartist") or "",\n',
        "reports review csv value",
    )
    replace_once(
        "app/reports.py",
        '                "target_bits": payload.get("target_bits"),\n                "temp_sha256": item.get("temp_sha256"),\n',
        '                "target_bits": payload.get("target_bits"),\n                "cpu_limit_percent": payload.get("cpu_limit_percent"),\n                "temp_sha256": item.get("temp_sha256"),\n',
        "reports job file cpu load",
    )
    replace_once(
        "app/reports.py",
        '            f"Bits: {item.get(\'source_bits\') or \'\'} -> {item.get(\'target_bits\') or \'\'}; "\n            f"Bytes: {item[\'source_bytes\']} -> {item[\'final_bytes\']}; "\n',
        '            f"Bits: {item.get(\'source_bits\') or \'\'} -> {item.get(\'target_bits\') or \'\'}; "\n            f"CPU cap: {str(item.get(\'cpu_limit_percent\')) + \'% per worker\' if item.get(\'cpu_limit_percent\') is not None else \'disabled\'}; "\n            f"Bytes: {item[\'source_bytes\']} -> {item[\'final_bytes\']}; "\n',
        "reports job txt cpu",
    )
    replace_once(
        "app/reports.py",
        '        "target_bits",\n        "source_bytes",\n',
        '        "target_bits",\n        "cpu_limit_percent",\n        "source_bytes",\n',
        "reports job csv field",
    )
    replace_once(
        "app/reports.py",
        '                "target_bits": item.get("target_bits") or "",\n                "source_bytes": item["source_bytes"],\n',
        '                "target_bits": item.get("target_bits") or "",\n                "cpu_limit_percent": item.get("cpu_limit_percent") if item.get("cpu_limit_percent") is not None else "",\n                "source_bytes": item["source_bytes"],\n',
        "reports job csv value",
    )


def patch_admin() -> None:
    replace_once(
        "app/admin.py",
        '                "metaflac": _tool_version(["metaflac", "--version"]),\n                "python": _tool_version(["python", "--version"]),\n',
        '                "metaflac": _tool_version(["metaflac", "--version"]),\n                "cpulimit": _tool_version(["cpulimit", "-h"]),\n                "python": _tool_version(["python", "--version"]),\n',
        "admin cpulimit version",
    )


def patch_settings_extras() -> None:
    replace_once(
        "app/settings_extras.py",
        '        db.set_setting(db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES)\n        db.set_setting(db_path, "read_only_mode", False)\n        db.set_setting(db_path, "daily_scan_time", DEFAULT_DAILY_SCAN_TIME)\n',
        '        db.set_setting(db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES)\n        db.set_setting(db_path, "read_only_mode", False)\n        db.set_setting(db_path, "conversion_cpu_limit_percent", None)\n        db.set_setting(db_path, "daily_scan_time", DEFAULT_DAILY_SCAN_TIME)\n',
        "settings reset cpu limit",
    )
    replace_once(
        "app/settings_extras.py",
        '            "read_only_mode": False,\n            "free_space_reserve_bytes": DEFAULT_RESERVE_BYTES,\n',
        '            "read_only_mode": False,\n            "cpu_limit_percent": None,\n            "free_space_reserve_bytes": DEFAULT_RESERVE_BYTES,\n',
        "settings reset cpu result",
    )


def patch_ui() -> None:
    replace_once(
        "app/static/source-rates.js",
        "  loadUiAddon('/static/settings-extras-ui.js');\n  loadUiAddon('/static/album-thumbnails.js');\n",
        "  loadUiAddon('/static/settings-extras-ui.js');\n  loadUiAddon('/static/resource-control.js');\n  loadUiAddon('/static/album-thumbnails.js');\n",
        "source-rates resource addon",
    )
    replace_once(
        "app/static/settings-extras-ui.js",
        "including the 10 GB free-space reserve, 10:00 daily scan time, System theme, Comfortable density, the normal 96/192 kHz source filter and the built-in default resampler preset.",
        "including the 10 GB free-space reserve, disabled conversion CPU cap, 10:00 daily scan time, System theme, Comfortable density, the normal 96/192 kHz source filter and the built-in default resampler preset.",
        "settings reset UI cpu wording",
    )
    replace_once(
        "app/static/app.js",
        "<div class=\"reviewMetric\"><span>ZFS</span><strong>${d.zfs?.ok?'Healthy':'Blocked'}</strong></div>`;",
        "<div class=\"reviewMetric\"><span>ZFS</span><strong>${d.zfs?.ok?'Healthy':'Blocked'}</strong></div><div class=\"reviewMetric\"><span>CPU cap</span><strong>${d.cpu_limit_percent!==null&&d.cpu_limit_percent!==undefined?`${d.cpu_limit_percent}% / worker`:'Disabled'}</strong></div>`;",
        "review UI cpu metric",
    )


def patch_readme() -> None:
    replace_once(
        "README.md",
        "New destructive conversion work fails closed if the configured ZFS pool is not confirmed healthy, the music dataset is not writable, free space drops below the configured reserve, Read-only Scan Mode is enabled, or recovery state requires manual attention. On Linux/OpenZFS the app prefers the read-only `/proc/spl/kstat/zfs/<pool>/state` pool heartbeat and retains `zpool status -x` as a fallback.\n",
        "New destructive conversion work fails closed if the configured ZFS pool is not confirmed healthy, the music dataset is not writable, free space drops below the configured reserve, Read-only Scan Mode is enabled, or recovery state requires manual attention. On Linux/OpenZFS the app prefers the read-only `/proc/spl/kstat/zfs/<pool>/state` pool heartbeat and retains `zpool status -x` as a fallback.\n\nConversion CPU throttling is optional and disabled by default. When enabled in Settings, each SoX conversion worker is wrapped with `cpulimit` at the configured 10–100% per-worker ceiling; changes take effect when the next file starts and never initiate conversion.\n",
        "README cpu resource control",
    )


def patch_health_test() -> None:
    replace_once(
        "tests/test_health_status.py",
        '''    def test_missing_ultra_backend_is_visible_and_blocks_conversion(self) -> None:\n        result = self.healthy(ultra_sox=None)\n        self.assertEqual(result["status"], "degraded")\n        self.assertFalse(result["conversion_ready"])\n        self.assertIn("Ultra 37 SoX backend is unavailable", result["health_reasons"])\n\n\nif __name__ == "__main__":\n''',
        '''    def test_missing_ultra_backend_is_visible_and_blocks_conversion(self) -> None:\n        result = self.healthy(ultra_sox=None)\n        self.assertEqual(result["status"], "degraded")\n        self.assertFalse(result["conversion_ready"])\n        self.assertIn("Ultra 37 SoX backend is unavailable", result["health_reasons"])\n\n    def test_enabled_cpu_cap_without_runtime_blocks_conversion_only(self) -> None:\n        result = self.healthy(cpu_limit_percent=50, cpu_limiter_available=False)\n        self.assertEqual(result["status"], "ok")\n        self.assertFalse(result["conversion_ready"])\n        self.assertIn("cpulimit runtime is unavailable", " ".join(result["conversion_blockers"]))\n\n\nif __name__ == "__main__":\n''',
        "health cpu test",
    )


def write_resource_control_module() -> None:
    write_new(
        "app/resource_control.py",
        '''from __future__ import annotations\n\nimport shutil\nfrom datetime import datetime\nfrom pathlib import Path\nfrom typing import Any\nfrom zoneinfo import ZoneInfo\n\nfrom fastapi import APIRouter, HTTPException\nfrom pydantic import BaseModel, Field\n\nfrom . import db\nfrom .operations_log import record_event\n\nCPU_LIMIT_SETTING = "conversion_cpu_limit_percent"\nCPU_LIMIT_MIN = 10\nCPU_LIMIT_MAX = 100\n\n\nclass ResourceSettingsRequest(BaseModel):\n    cpu_limit_percent: int | None = Field(default=None, ge=CPU_LIMIT_MIN, le=CPU_LIMIT_MAX)\n\n\ndef configured_cpu_limit(db_path: Path) -> int | None:\n    raw = db.get_setting(db_path, CPU_LIMIT_SETTING, None)\n    if raw is None:\n        return None\n    try:\n        value = int(raw)\n    except (TypeError, ValueError):\n        return None\n    if not CPU_LIMIT_MIN <= value <= CPU_LIMIT_MAX:\n        return None\n    return value\n\n\ndef cpulimit_available() -> bool:\n    return shutil.which("cpulimit") is not None\n\n\ndef resource_status(db_path: Path, *, active_job_id: int | None = None) -> dict[str, Any]:\n    limit = configured_cpu_limit(db_path)\n    return {\n        "cpu_limit_percent": limit,\n        "enabled": limit is not None,\n        "available": cpulimit_available(),\n        "min_percent": CPU_LIMIT_MIN,\n        "max_percent": CPU_LIMIT_MAX,\n        "scope": "per-worker-sox",\n        "takes_effect": "next-file",\n        "active_job_id": active_job_id,\n    }\n\n\ndef build_resource_control_router(\n    db_path: Path,\n    timezone: str,\n    job_manager: Any,\n) -> APIRouter:\n    router = APIRouter()\n    tz = ZoneInfo(timezone)\n\n    def active_job_id() -> int | None:\n        return job_manager.active_job_id()\n\n    @router.get("/api/settings/resources")\n    def get_resource_settings() -> dict[str, Any]:\n        return resource_status(db_path, active_job_id=active_job_id())\n\n    @router.post("/api/settings/resources")\n    def set_resource_settings(request: ResourceSettingsRequest) -> dict[str, Any]:\n        limit = request.cpu_limit_percent\n        if limit is not None and not cpulimit_available():\n            raise HTTPException(\n                status_code=409,\n                detail="Cannot enable the conversion CPU cap because cpulimit is unavailable",\n            )\n        db.set_setting(db_path, CPU_LIMIT_SETTING, limit)\n        current_job = active_job_id()\n        record_event(\n            db_path,\n            datetime.now(tz).isoformat(timespec="seconds"),\n            "conversion_cpu_limit_changed",\n            {\n                "cpu_limit_percent": limit,\n                "scope": "per-worker-sox",\n                "takes_effect": "next-file",\n                "active_job_id": current_job,\n            },\n        )\n        return resource_status(db_path, active_job_id=current_job)\n\n    return router\n''',
    )


def write_resource_control_ui() -> None:
    write_new(
        "app/static/resource-control.js",
        '''function resourceControlInstall(){\n  if($("resourceControlCard"))return;\n  const view=$("settingsView");\n  if(!view)return;\n  const card=document.createElement("section");\n  card.id="resourceControlCard";\n  card.className="card";\n  card.style.marginTop="14px";\n  card.innerHTML=`\n    <h3 style="margin-top:0">Conversion resource control</h3>\n    <div class="muted" style="margin-bottom:12px">Optional CPU throttling applies only to the SoX resampling process and is disabled by default. The percentage is a per-worker ceiling relative to one logical CPU; with two workers, each worker is capped independently. Changes take effect when the next file starts and never start conversion.</div>\n    <div class="resourceControlRow">\n      <label class="resourceControlToggle"><input id="cpuCapEnabled" type="checkbox"> Enable per-worker CPU cap</label>\n      <label>CPU cap per worker (%)<input id="cpuCapPercent" type="number" min="10" max="100" step="5" value="75"></label>\n      <div><span class="muted">Limiter runtime</span><strong id="cpuCapRuntime">—</strong></div>\n      <div><span class="muted">Current setting</span><strong id="cpuCapState">Disabled</strong></div>\n    </div>\n    <div class="toolbar" style="margin-top:14px"><button id="saveResourceControl" class="primary">Save Resource Control</button></div>\n    <div id="resourceControlNotice" class="notice hidden"></div>`;\n  const reset=$("resetDefaultsCard");\n  if(reset)reset.insertAdjacentElement("beforebegin",card);else view.appendChild(card);\n\n  if(!document.querySelector("style[data-resource-control]")){\n    const style=document.createElement("style");\n    style.dataset.resourceControl="1";\n    style.textContent=`.resourceControlRow{display:grid;grid-template-columns:minmax(220px,1.2fr) minmax(190px,.8fr) minmax(160px,.7fr) minmax(160px,.7fr);gap:14px;align-items:end}.resourceControlRow>div,.resourceControlRow>label{display:grid;gap:6px}.resourceControlToggle{display:flex!important;align-items:center;gap:8px;padding-bottom:9px}@media(max-width:900px){.resourceControlRow{grid-template-columns:1fr}}`;\n    document.head.appendChild(style);\n  }\n  $("cpuCapEnabled").onchange=resourceControlToggle;\n  $("saveResourceControl").onclick=resourceControlSave;\n}\n\nfunction resourceControlToggle(){\n  const enabled=Boolean($("cpuCapEnabled")?.checked);\n  if($("cpuCapPercent"))$("cpuCapPercent").disabled=!enabled;\n}\n\nfunction resourceControlRender(data){\n  resourceControlInstall();\n  const enabled=Boolean(data.enabled);\n  $("cpuCapEnabled").checked=enabled;\n  if(data.cpu_limit_percent!==null&&data.cpu_limit_percent!==undefined){\n    $("cpuCapPercent").value=String(data.cpu_limit_percent);\n  }\n  $("cpuCapPercent").min=String(data.min_percent||10);\n  $("cpuCapPercent").max=String(data.max_percent||100);\n  $("cpuCapRuntime").textContent=data.available?"Available":"Unavailable";\n  $("cpuCapState").textContent=enabled?`${data.cpu_limit_percent}% per worker`:"Disabled";\n  $("cpuCapEnabled").disabled=!data.available&&!enabled;\n  resourceControlToggle();\n}\n\nasync function resourceControlLoad(){\n  resourceControlInstall();\n  try{\n    const response=await fetch("/api/settings/resources");\n    const data=await response.json();\n    if(!response.ok)throw new Error(data.detail||"Unable to load resource-control settings");\n    resourceControlRender(data);\n  }catch(error){notice("resourceControlNotice",error.message,"bad")}\n}\n\nasync function resourceControlSave(){\n  const enabled=Boolean($("cpuCapEnabled").checked);\n  let limit=null;\n  if(enabled){\n    limit=Number($("cpuCapPercent").value);\n    const min=Number($("cpuCapPercent").min||10);\n    const max=Number($("cpuCapPercent").max||100);\n    if(!Number.isInteger(limit)||limit<min||limit>max){\n      notice("resourceControlNotice",`CPU cap must be a whole number from ${min} through ${max}.`,"bad");\n      return;\n    }\n  }\n  const button=$("saveResourceControl");\n  button.disabled=true;\n  try{\n    const response=await fetch("/api/settings/resources",{\n      method:"POST",\n      headers:{"Content-Type":"application/json"},\n      body:JSON.stringify({cpu_limit_percent:limit}),\n    });\n    const data=await response.json();\n    if(!response.ok)throw new Error(data.detail||"Unable to save resource-control settings");\n    resourceControlRender(data);\n    const suffix=data.active_job_id?` Active job ${data.active_job_id} will use the new setting when its next file starts.`:"";\n    notice("resourceControlNotice",data.enabled?`CPU cap set to ${data.cpu_limit_percent}% per worker.${suffix}`:`CPU cap disabled.${suffix}`,"good");\n    await loadStatus();\n  }catch(error){notice("resourceControlNotice",error.message,"bad")}\n  finally{button.disabled=false}\n}\n\nresourceControlInstall();\nconst resourceControlBaseLoadSettings=loadSettings;\nloadSettings=async function(){\n  await resourceControlBaseLoadSettings();\n  await resourceControlLoad();\n};\n''',
    )


def write_tests() -> None:
    write_new(
        "tests/test_cpu_limit.py",
        '''from __future__ import annotations\n\nimport unittest\nfrom unittest.mock import patch\n\nfrom app.converter import ConversionError, ProfileUnavailable, apply_cpu_limit\n\n\nclass CpuLimitCommandTests(unittest.TestCase):\n    def test_disabled_limit_leaves_command_unchanged(self) -> None:\n        command = ["nice", "-n", "10", "sox", "in.flac", "out.flac"]\n        self.assertIs(apply_cpu_limit(command, None), command)\n\n    def test_enabled_limit_wraps_complete_execution_command(self) -> None:\n        command = ["nice", "-n", "10", "ionice", "-c", "2", "sox", "in.flac", "out.flac"]\n        with patch("app.converter.shutil.which", return_value="/usr/bin/cpulimit"):\n            wrapped = apply_cpu_limit(command, 55)\n        self.assertEqual(wrapped[:6], ["cpulimit", "-q", "-l", "55", "--", "nice"])\n        self.assertEqual(wrapped[5:], command)\n\n    def test_invalid_limit_is_rejected(self) -> None:\n        with self.assertRaises(ConversionError):\n            apply_cpu_limit(["sox"], 9)\n        with self.assertRaises(ConversionError):\n            apply_cpu_limit(["sox"], 101)\n\n    def test_missing_cpulimit_fails_before_conversion(self) -> None:\n        with patch("app.converter.shutil.which", return_value=None):\n            with self.assertRaises(ProfileUnavailable):\n                apply_cpu_limit(["sox"], 50)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    )
    write_new(
        "tests/test_resource_control.py",
        '''from __future__ import annotations\n\nimport tempfile\nimport unittest\nfrom pathlib import Path\nfrom unittest.mock import patch\n\nfrom fastapi import HTTPException\nfrom pydantic import ValidationError\n\nfrom app import db\nfrom app.resource_control import (\n    ResourceSettingsRequest,\n    build_resource_control_router,\n    configured_cpu_limit,\n    resource_status,\n)\n\n\nclass DummyJobs:\n    def __init__(self, active: int | None = None) -> None:\n        self.active = active\n\n    def active_job_id(self) -> int | None:\n        return self.active\n\n\nclass ResourceControlTests(unittest.TestCase):\n    def setUp(self) -> None:\n        self.tmp = tempfile.TemporaryDirectory()\n        self.db_path = Path(self.tmp.name) / "data" / "test.db"\n        db.init(self.db_path)\n\n    def tearDown(self) -> None:\n        self.tmp.cleanup()\n\n    def post_endpoint(self, active: int | None = None):\n        router = build_resource_control_router(\n            self.db_path,\n            "America/Indiana/Indianapolis",\n            DummyJobs(active),\n        )\n        return next(\n            route.endpoint\n            for route in router.routes\n            if getattr(route, "path", None) == "/api/settings/resources"\n            and "POST" in getattr(route, "methods", set())\n        )\n\n    def test_default_is_uncapped(self) -> None:\n        with patch("app.resource_control.shutil.which", return_value="/usr/bin/cpulimit"):\n            status = resource_status(self.db_path)\n        self.assertIsNone(configured_cpu_limit(self.db_path))\n        self.assertFalse(status["enabled"])\n        self.assertEqual(status["scope"], "per-worker-sox")\n\n    def test_enabling_and_disabling_persists_setting(self) -> None:\n        endpoint = self.post_endpoint(active=12)\n        with patch("app.resource_control.shutil.which", return_value="/usr/bin/cpulimit"):\n            enabled = endpoint(ResourceSettingsRequest(cpu_limit_percent=60))\n            self.assertEqual(enabled["cpu_limit_percent"], 60)\n            self.assertEqual(enabled["active_job_id"], 12)\n            disabled = endpoint(ResourceSettingsRequest(cpu_limit_percent=None))\n        self.assertIsNone(disabled["cpu_limit_percent"])
        self.assertIsNone(configured_cpu_limit(self.db_path))\n\n    def test_enabling_without_runtime_is_rejected(self) -> None:\n        endpoint = self.post_endpoint()\n        with patch("app.resource_control.shutil.which", return_value=None):\n            with self.assertRaises(HTTPException) as ctx:\n                endpoint(ResourceSettingsRequest(cpu_limit_percent=50))\n        self.assertEqual(ctx.exception.status_code, 409)\n        self.assertIsNone(configured_cpu_limit(self.db_path))\n\n    def test_request_bounds_are_validated(self) -> None:\n        with self.assertRaises(ValidationError):\n            ResourceSettingsRequest(cpu_limit_percent=9)\n        with self.assertRaises(ValidationError):\n            ResourceSettingsRequest(cpu_limit_percent=101)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    )
    write_new(
        "tests/test_job_cpu_limit.py",
        '''from __future__ import annotations\n\nimport tempfile\nimport unittest\nfrom pathlib import Path\nfrom unittest.mock import patch\n\nfrom app import db\nfrom app.converter import ConversionResult\nfrom app.jobs import ConversionJobManager\nfrom app.profiles import FACTORY_DEFAULTS\n\n\nclass JobCpuLimitWiringTests(unittest.TestCase):\n    def test_job_reads_cpu_limit_when_each_file_starts(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp)\n            music = root / "music"\n            music.mkdir()\n            db_path = root / "data" / "test.db"\n            db.init(db_path)\n            manager = ConversionJobManager(db_path, music, "America/Indiana/Indianapolis")\n            source = music / "track.flac"\n            source.write_bytes(b"synthetic source")\n            with db.session(db_path) as conn:\n                job_cur = conn.execute(\n                    """\n                    INSERT INTO conversion_jobs(\n                      created_at,status,profile_id,profile_json,workers,source_filter_json,album_order_json\n                    ) VALUES(?,?,?,?,?,?,?)\n                    """,\n                    (manager._now(), "running", FACTORY_DEFAULTS.id, None, 1, "{}", "[]"),\n                )\n                job_id = int(job_cur.lastrowid)\n                file_cur = conn.execute(\n                    """\n                    INSERT INTO conversion_files(\n                      job_id,album_index,file_index,albumartist,album,path,source_bytes,status\n                    ) VALUES(?,?,?,?,?,?,?,?)\n                    """,\n                    (job_id, 0, 0, "Artist", "Album", str(source), source.stat().st_size, "pending"),\n                )\n                file_id = int(file_cur.lastrowid)\n\n            synthetic = ConversionResult(\n                source=str(source),\n                status="failed",\n                command=["synthetic"],\n                error="synthetic failure",\n            )\n            with patch("app.jobs.configured_cpu_limit", return_value=55), patch(\n                "app.jobs.convert_file", return_value=synthetic\n            ) as convert:\n                payload = manager._run_file(\n                    job_id, file_id, str(source), FACTORY_DEFAULTS, source.stat().st_size\n                )\n\n            convert.assert_called_once_with(source, FACTORY_DEFAULTS, cpu_limit_percent=55)\n            self.assertEqual(payload["cpu_limit_percent"], 55)\n            self.assertEqual(payload["status"], "failed")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    )


def main() -> None:
    patch_dockerfile()
    patch_main()
    patch_health_status()
    patch_converter()
    patch_review()
    patch_jobs()
    patch_reports()
    patch_admin()
    patch_settings_extras()
    patch_ui()
    patch_readme()
    patch_health_test()
    write_resource_control_module()
    write_resource_control_ui()
    write_tests()


if __name__ == "__main__":
    main()
