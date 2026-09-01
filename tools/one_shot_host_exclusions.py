from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Allow Settings to accept/present real TrueNAS paths while keeping operational exclusions under
# the /music container mount in SQLite and scanner code.
replace_once(
    "app/admin.py",
    "from .operations_log import log_disk_usage, recent_events, record_event\n",
    "from .operations_log import log_disk_usage, recent_events, record_event\nfrom .path_display import host_music_path, internal_music_path\n",
    "admin path mapping imports",
)
admin_path = Path("app/admin.py")
admin = admin_path.read_text(encoding="utf-8")
start = admin.index("def _normalize_exclusions(")
end = admin.index("def _excluded(", start)
replacement = '''def _normalize_exclusions(\n    music_root: Path,\n    paths: list[str],\n    globs: list[str],\n    host_music_root: Path | None = None,\n) -> tuple[list[str], list[str]]:\n    root = music_root.resolve(strict=False)\n    host_root = (host_music_root or music_root).resolve(strict=False)\n    normalized_paths: list[str] = []\n    for raw in paths:\n        text = str(raw).strip()\n        if not text:\n            continue\n        resolved = Path(internal_music_path(text, root, host_root)).resolve(strict=False)\n        if resolved != root and root not in resolved.parents:\n            raise ValueError(f"Excluded path must be inside the music root: {text}")\n        normalized_paths.append(str(resolved))\n\n    normalized_globs: list[str] = []\n    host_prefix = host_root.as_posix().rstrip("/")\n    internal_prefix = root.as_posix().rstrip("/")\n    for raw in globs:\n        pattern = str(raw).strip().replace("\\\\", "/")\n        if not pattern:\n            continue\n        if "\\x00" in pattern:\n            raise ValueError("Exclusion glob contains an invalid NUL character")\n        if pattern == host_prefix or pattern.startswith(host_prefix + "/"):\n            pattern = internal_prefix + pattern[len(host_prefix):]\n        normalized_globs.append(pattern)\n\n    return sorted(set(normalized_paths)), sorted(set(normalized_globs))\n\n\ndef _display_exclusion_glob(\n    pattern: str, music_root: Path, host_music_root: Path\n) -> str:\n    internal_prefix = music_root.resolve(strict=False).as_posix().rstrip("/")\n    host_prefix = host_music_root.resolve(strict=False).as_posix().rstrip("/")\n    if pattern == internal_prefix or pattern.startswith(internal_prefix + "/"):\n        return host_prefix + pattern[len(internal_prefix):]\n    return pattern\n\n\n'''
admin_path.write_text(admin[:start] + replacement + admin[end:], encoding="utf-8")

replace_once(
    "app/admin.py",
    "    recovery_status: Callable[[], list[dict[str, Any]]],\n) -> APIRouter:\n    router = APIRouter()\n    tz = ZoneInfo(timezone)\n",
    "    recovery_status: Callable[[], list[dict[str, Any]]],\n    host_music_root: Path | None = None,\n) -> APIRouter:\n    router = APIRouter()\n    tz = ZoneInfo(timezone)\n    host_root = (host_music_root or music_root).resolve(strict=False)\n",
    "admin router host root",
)
replace_once(
    "app/admin.py",
    '''    @router.get("/api/settings")\n    def get_settings() -> dict[str, Any]:\n        reserve = int(db.get_setting(db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))\n        return {\n            "read_only_mode": bool(db.get_setting(db_path, "read_only_mode", False)),\n            "free_space_reserve_bytes": reserve,\n            "free_space_reserve_gb": round(reserve / 1024**3, 3),\n            "exclude_paths": db.get_setting(db_path, "exclude_paths", []) or [],\n            "exclude_globs": db.get_setting(db_path, "exclude_globs", []) or [],\n            "timezone": timezone,\n        }\n''',
    '''    @router.get("/api/settings")\n    def get_settings() -> dict[str, Any]:\n        reserve = int(db.get_setting(db_path, "free_space_reserve_bytes", DEFAULT_RESERVE_BYTES))\n        stored_paths = db.get_setting(db_path, "exclude_paths", []) or []\n        stored_globs = db.get_setting(db_path, "exclude_globs", []) or []\n        return {\n            "read_only_mode": bool(db.get_setting(db_path, "read_only_mode", False)),\n            "free_space_reserve_bytes": reserve,\n            "free_space_reserve_gb": round(reserve / 1024**3, 3),\n            "exclude_paths": [host_music_path(item, music_root, host_root) for item in stored_paths],\n            "exclude_globs": [_display_exclusion_glob(item, music_root, host_root) for item in stored_globs],\n            "timezone": timezone,\n            "host_music_root": str(host_root),\n        }\n''',
    "settings display host paths",
)

admin = admin_path.read_text(encoding="utf-8")
old_normalize = "            exact, globs = _normalize_exclusions(music_root, request.exclude_paths, request.exclude_globs)\n"
new_normalize = "            exact, globs = _normalize_exclusions(music_root, request.exclude_paths, request.exclude_globs, host_root)\n"
count = admin.count(old_normalize)
if count != 2:
    raise SystemExit(f"settings exclusion normalization: expected two matches in app/admin.py, found {count}")
admin_path.write_text(admin.replace(old_normalize, new_normalize), encoding="utf-8")

replace_once(
    "app/admin.py",
    '''        return {\n            "free_space_reserve_bytes": reserve,\n            "free_space_reserve_gb": round(reserve / 1024**3, 3),\n            "exclude_paths": exact,\n            "exclude_globs": globs,\n        }\n''',
    '''        return {\n            "free_space_reserve_bytes": reserve,\n            "free_space_reserve_gb": round(reserve / 1024**3, 3),\n            "exclude_paths": [host_music_path(item, music_root, host_root) for item in exact],\n            "exclude_globs": [_display_exclusion_glob(item, music_root, host_root) for item in globs],\n        }\n''',
    "save exclusion host response",
)
replace_once(
    "app/admin.py",
    '        return {**_preview_exclusions(music_root, exact, globs), "exclude_paths": exact, "exclude_globs": globs}\n',
    '        return {**_preview_exclusions(music_root, exact, globs), "exclude_paths": [host_music_path(item, music_root, host_root) for item in exact], "exclude_globs": [_display_exclusion_glob(item, music_root, host_root) for item in globs]}\n',
    "preview exclusion host response",
)

replace_once(
    "app/main.py",
    "        recovery_status=lambda: recovery_status,\n    )\n)",
    "        recovery_status=lambda: recovery_status,\n        host_music_root=HOST_MUSIC_ROOT,\n    )\n)",
    "main admin host root",
)

# Add regression coverage for copy/pasting a TrueNAS-visible path into Settings.
replace_once(
    "tests/test_admin.py",
    '''    def test_exclusion_cannot_escape_music_root(self) -> None:\n''',
    '''    def test_true_nas_exclusion_path_normalizes_to_internal_mount(self) -> None:\n        root = Path("/music")\n        host = Path("/mnt/MainStorage/StorageDataset/Music")\n        exact, globs = _normalize_exclusions(\n            root,\n            ["/mnt/MainStorage/StorageDataset/Music/Artist/Album"],\n            ["/mnt/MainStorage/StorageDataset/Music/Archive/*"],\n            host,\n        )\n        self.assertEqual(exact, ["/music/Artist/Album"])\n        self.assertEqual(globs, ["/music/Archive/*"])\n\n    def test_exclusion_cannot_escape_music_root(self) -> None:\n''',
    "host exclusion normalization test",
)

# Reset-to-defaults must include the cover preference introduced after the original reset UI.
replace_once(
    "app/static/settings-extras-ui.js",
    "    'sox-resampler-last-preset',\n",
    "    'sox-resampler-last-preset',\n    'sox-resampler-cover-thumbnails',\n",
    "cover preference reset key",
)
replace_once(
    "app/static/settings-extras-ui.js",
    "  if(typeof applyAppearance==='function')applyAppearance();\n  resetAck();\n",
    "  if(typeof applyAppearance==='function')applyAppearance();\n  if(typeof applyAlbumThumbnailPreference==='function')applyAlbumThumbnailPreference();\n  resetAck();\n",
    "cover preference reset apply",
)
