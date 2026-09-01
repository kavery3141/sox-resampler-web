from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import db
from .profiles import BUILTIN_PROFILES, ResampleProfile, profile_from_dict, profile_with_identity

PRESET_SCHEMA = "sox-resampler-preset"
PRESET_SCHEMA_VERSION = 1
PROFILE_JSON_KEYS = {
    "id",
    "name",
    "description",
    "notes",
    "target_rate",
    "bit_depth",
    "quality",
    "passband_percent",
    "phase_percent",
    "allow_aliasing",
    "flac_compression",
    "dither",
    "headroom_db",
    "read_only",
    "implementation_ready",
}


def ensure_tables(db_path: Path) -> None:
    with db.session(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS custom_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _row_profile(row: Any) -> ResampleProfile:
    try:
        payload = json.loads(row["profile_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Stored custom preset {row['id']} contains invalid JSON") from exc
    payload.update(
        {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"] or ""),
            "notes": str(row["notes"] or ""),
            "read_only": False,
        }
    )
    return profile_from_dict(payload, id_override=str(row["id"]), read_only_override=False)


def _profile_payload(profile: ResampleProfile) -> str:
    payload = profile.to_dict()
    payload["read_only"] = False
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def list_custom_profiles(db_path: Path) -> list[ResampleProfile]:
    ensure_tables(db_path)
    with db.session(db_path) as conn:
        rows = conn.execute("SELECT * FROM custom_profiles ORDER BY name COLLATE NOCASE,id").fetchall()
    return [_row_profile(row) for row in rows]


def list_all_profiles(db_path: Path) -> list[ResampleProfile]:
    return list(BUILTIN_PROFILES.values()) + list_custom_profiles(db_path)


def get_profile(db_path: Path, profile_id: str) -> ResampleProfile:
    builtin = BUILTIN_PROFILES.get(profile_id)
    if builtin is not None:
        return builtin
    ensure_tables(db_path)
    with db.session(db_path) as conn:
        row = conn.execute("SELECT * FROM custom_profiles WHERE id=?", (profile_id,)).fetchone()
    if not row:
        raise ValueError(f"Unknown preset: {profile_id}")
    return _row_profile(row)


def _new_id() -> str:
    return f"custom-{uuid.uuid4().hex[:16]}"


def _name_exists(db_path: Path, name: str, excluding_id: str | None = None) -> bool:
    ensure_tables(db_path)
    with db.session(db_path) as conn:
        if excluding_id:
            row = conn.execute(
                "SELECT 1 FROM custom_profiles WHERE name=? COLLATE NOCASE AND id<>? LIMIT 1",
                (name, excluding_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM custom_profiles WHERE name=? COLLATE NOCASE LIMIT 1",
                (name,),
            ).fetchone()
    return bool(row)


def _validate_unique_name(db_path: Path, name: str, excluding_id: str | None = None) -> None:
    if any(name.casefold() == profile.name.casefold() for profile in BUILTIN_PROFILES.values()):
        raise ValueError("Custom preset name conflicts with a built-in preset")
    if _name_exists(db_path, name, excluding_id):
        raise ValueError("A custom preset with that name already exists")


def create_custom_profile(db_path: Path, payload: dict[str, Any]) -> ResampleProfile:
    ensure_tables(db_path)
    profile_id = _new_id()
    profile = profile_from_dict(
        {**payload, "id": profile_id, "read_only": False, "implementation_ready": True},
        id_override=profile_id,
        read_only_override=False,
    )
    _validate_unique_name(db_path, profile.name)
    now = _now()
    with db.session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO custom_profiles(id,name,description,notes,profile_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                profile.id,
                profile.name,
                profile.description,
                profile.notes,
                _profile_payload(profile),
                now,
                now,
            ),
        )
    return profile


def update_custom_profile(db_path: Path, profile_id: str, payload: dict[str, Any]) -> ResampleProfile:
    current = get_profile(db_path, profile_id)
    if current.read_only:
        raise ValueError("Built-in presets are read-only; duplicate the preset before editing")
    merged = current.to_dict()
    merged.update(payload)
    merged.update({"id": profile_id, "read_only": False, "implementation_ready": True})
    profile = profile_from_dict(merged, id_override=profile_id, read_only_override=False)
    _validate_unique_name(db_path, profile.name, excluding_id=profile_id)
    with db.session(db_path) as conn:
        conn.execute(
            """
            UPDATE custom_profiles
            SET name=?,description=?,notes=?,profile_json=?,updated_at=?
            WHERE id=?
            """,
            (
                profile.name,
                profile.description,
                profile.notes,
                _profile_payload(profile),
                _now(),
                profile_id,
            ),
        )
    return profile


def delete_custom_profile(db_path: Path, profile_id: str) -> None:
    if profile_id in BUILTIN_PROFILES:
        raise ValueError("Built-in presets cannot be deleted")
    ensure_tables(db_path)
    with db.session(db_path) as conn:
        cur = conn.execute("DELETE FROM custom_profiles WHERE id=?", (profile_id,))
    if cur.rowcount == 0:
        raise ValueError("Custom preset not found")


def _copy_name(db_path: Path, source_name: str) -> str:
    stem = f"{source_name} Copy"
    if not _name_exists(db_path, stem) and all(stem.casefold() != p.name.casefold() for p in BUILTIN_PROFILES.values()):
        return stem
    index = 2
    while True:
        candidate = f"{source_name} Copy {index}"
        if not _name_exists(db_path, candidate) and all(candidate.casefold() != p.name.casefold() for p in BUILTIN_PROFILES.values()):
            return candidate
        index += 1


def duplicate_profile(db_path: Path, profile_id: str, name: str | None = None) -> ResampleProfile:
    source = get_profile(db_path, profile_id)
    copy_name = str(name or "").strip() or _copy_name(db_path, source.name)
    copy = profile_with_identity(
        source,
        profile_id=_new_id(),
        name=copy_name,
        description=source.description,
        notes=source.notes,
    )
    _validate_unique_name(db_path, copy.name)
    now = _now()
    with db.session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO custom_profiles(id,name,description,notes,profile_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (copy.id, copy.name, copy.description, copy.notes, _profile_payload(copy), now, now),
        )
    return copy


def export_profile(profile: ResampleProfile) -> dict[str, Any]:
    preset = profile.to_dict()
    preset.pop("read_only", None)
    preset.pop("implementation_ready", None)
    return {
        "schema": PRESET_SCHEMA,
        "schema_version": PRESET_SCHEMA_VERSION,
        "preset": preset,
    }


def preview_import(payload: dict[str, Any]) -> ResampleProfile:
    if payload.get("schema") != PRESET_SCHEMA:
        raise ValueError("Not a SoX Resampler Web preset file")
    try:
        version = int(payload.get("schema_version"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Preset schema version is missing or invalid") from exc
    if version > PRESET_SCHEMA_VERSION:
        raise ValueError(
            f"Preset schema version {version} is newer than this app supports ({PRESET_SCHEMA_VERSION})"
        )
    if version < 1:
        raise ValueError("Preset schema version is unsupported")
    preset = payload.get("preset")
    if not isinstance(preset, dict):
        raise ValueError("Preset payload is missing")
    unknown = sorted(set(preset) - PROFILE_JSON_KEYS)
    if unknown:
        raise ValueError(f"Preset contains unsupported field(s): {', '.join(unknown)}")
    preview_id = str(preset.get("id") or "custom-import-preview")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", preview_id):
        preview_id = "custom-import-preview"
    return profile_from_dict(
        {**preset, "id": preview_id, "read_only": False, "implementation_ready": True},
        id_override=preview_id,
        read_only_override=False,
    )


def import_profile(db_path: Path, payload: dict[str, Any], name_override: str | None = None) -> ResampleProfile:
    preview = preview_import(payload)
    data = preview.to_dict()
    data.pop("id", None)
    if name_override is not None and str(name_override).strip():
        data["name"] = str(name_override).strip()
    return create_custom_profile(db_path, data)
