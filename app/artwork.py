from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from mutagen.flac import FLAC
from PIL import Image

from . import db

THUMBNAIL_MAX_SIZE = (320, 320)
FALLBACK_NAMES = (
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "front.jpg",
    "front.jpeg",
    "front.png",
)
MAX_FALLBACK_BYTES = 64 * 1024**2


def _folder_key(folder: str) -> str:
    return hashlib.sha256(folder.encode("utf-8", errors="surrogatepass")).hexdigest()


def _cache_root(data_root: Path) -> Path:
    return data_root.resolve() / "artwork" / "albums"


def _cache_path(data_root: Path, folder: str) -> Path:
    digest = _folder_key(folder)
    return _cache_root(data_root) / digest[:2] / f"{digest}.png"


def _inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except OSError:
        return False
    return resolved == root_resolved or root_resolved in resolved.parents


def _remove_cache_file(path_text: str | None, data_root: Path) -> None:
    if not path_text:
        return
    path = Path(path_text)
    root = _cache_root(data_root)
    if not _inside(path, root):
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _fallback_image(folder: Path) -> Path | None:
    try:
        entries = {
            child.name.lower(): child
            for child in folder.iterdir()
            if child.is_file() and not child.is_symlink()
        }
    except OSError:
        return None
    for name in FALLBACK_NAMES:
        path = entries.get(name)
        if path is not None:
            return path
    return None


def _source_for_folder(db_path: Path, folder: Path) -> dict[str, Any] | None:
    with db.session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT path,size_bytes,mtime_ns,picture_count
            FROM tracks WHERE folder=?
            ORDER BY path COLLATE NOCASE
            """,
            (str(folder),),
        ).fetchall()

    for row in rows:
        if int(row["picture_count"] or 0) <= 0:
            continue
        path = Path(row["path"])
        signature = (
            f"embedded|{path}|{int(row['size_bytes'])}|{int(row['mtime_ns'])}|"
            f"{int(row['picture_count'])}"
        )
        return {
            "kind": "embedded",
            "path": path,
            "signature": signature,
        }

    fallback = _fallback_image(folder)
    if fallback is None:
        return None
    try:
        stat = fallback.stat()
    except OSError:
        return None
    if stat.st_size > MAX_FALLBACK_BYTES:
        return {
            "kind": "file-too-large",
            "path": fallback,
            "signature": f"file-too-large|{fallback}|{stat.st_size}|{stat.st_mtime_ns}",
        }
    return {
        "kind": "file",
        "path": fallback,
        "signature": f"file|{fallback}|{stat.st_size}|{stat.st_mtime_ns}",
    }


def _embedded_image_bytes(path: Path) -> bytes:
    audio = FLAC(path)
    if not audio.pictures:
        raise ValueError("Indexed embedded artwork is no longer present")
    front = next((picture for picture in audio.pictures if int(picture.type) == 3), None)
    picture = front or audio.pictures[0]
    if not picture.data:
        raise ValueError("Embedded artwork block is empty")
    return bytes(picture.data)


def _render_thumbnail(source: dict[str, Any], destination: Path) -> tuple[str, int, int]:
    kind = str(source["kind"])
    source_path = Path(source["path"])
    if kind == "file-too-large":
        raise ValueError(f"Artwork file exceeds {MAX_FALLBACK_BYTES // 1024**2} MB safety limit")

    if kind == "embedded":
        image_source: Any = io.BytesIO(_embedded_image_bytes(source_path))
    elif kind == "file":
        image_source = source_path
    else:
        raise ValueError(f"Unsupported artwork source: {kind}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.tmp")
    try:
        with Image.open(image_source) as opened:
            opened.load()
            image = opened.copy()
        image.thumbnail(THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA", "LA", "L", "P"}:
            image = image.convert("RGBA")
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("Artwork image has invalid dimensions")
        image.save(temp, format="PNG", optimize=True)
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, destination)
        try:
            dir_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return digest, width, height


def _upsert_artwork(
    db_path: Path,
    *,
    folder: str,
    source_kind: str,
    source_path: str | None,
    source_signature: str | None,
    cache_path: str | None,
    cache_sha256: str | None,
    width: int | None,
    height: int | None,
    status: str,
    updated_at: str,
    error_text: str | None,
) -> int:
    with db.session(db_path) as conn:
        conn.execute(
            """
            INSERT INTO album_art(
              folder,source_kind,source_path,source_signature,cache_path,cache_sha256,
              width,height,status,updated_at,error_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(folder) DO UPDATE SET
              source_kind=excluded.source_kind,
              source_path=excluded.source_path,
              source_signature=excluded.source_signature,
              cache_path=excluded.cache_path,
              cache_sha256=excluded.cache_sha256,
              width=excluded.width,
              height=excluded.height,
              status=excluded.status,
              updated_at=excluded.updated_at,
              error_text=excluded.error_text
            """,
            (
                folder,
                source_kind,
                source_path,
                source_signature,
                cache_path,
                cache_sha256,
                width,
                height,
                status,
                updated_at,
                error_text,
            ),
        )
        row = conn.execute("SELECT id FROM album_art WHERE folder=?", (folder,)).fetchone()
    return int(row["id"])


def refresh_album_artwork(
    db_path: Path,
    data_root: Path,
    folder: Path,
    updated_at: str,
) -> dict[str, Any]:
    """Refresh one album-folder thumbnail using only local indexed/library data.

    Embedded FLAC artwork has priority. External fallback names are checked only when no indexed
    FLAC in the folder contains embedded pictures. The UI never reads the music mount directly.
    """
    folder_text = str(folder)
    destination = _cache_path(data_root, folder_text)
    source = _source_for_folder(db_path, folder)
    with db.session(db_path) as conn:
        old_row = conn.execute("SELECT * FROM album_art WHERE folder=?", (folder_text,)).fetchone()
    old = dict(old_row) if old_row else None

    if source is None:
        if old:
            _remove_cache_file(old.get("cache_path"), data_root)
        artwork_id = _upsert_artwork(
            db_path,
            folder=folder_text,
            source_kind="none",
            source_path=None,
            source_signature=None,
            cache_path=None,
            cache_sha256=None,
            width=None,
            height=None,
            status="missing",
            updated_at=updated_at,
            error_text=None,
        )
        return {"id": artwork_id, "folder": folder_text, "status": "missing", "changed": bool(old and old.get("status") != "missing")}

    signature = str(source["signature"])
    if (
        old
        and old.get("status") == "ready"
        and old.get("source_signature") == signature
        and old.get("cache_path")
        and Path(str(old["cache_path"])).is_file()
    ):
        return {
            "id": int(old["id"]),
            "folder": folder_text,
            "status": "ready",
            "source_kind": old.get("source_kind"),
            "changed": False,
        }

    try:
        cache_sha256, width, height = _render_thumbnail(source, destination)
        artwork_id = _upsert_artwork(
            db_path,
            folder=folder_text,
            source_kind=str(source["kind"]),
            source_path=str(source["path"]),
            source_signature=signature,
            cache_path=str(destination),
            cache_sha256=cache_sha256,
            width=width,
            height=height,
            status="ready",
            updated_at=updated_at,
            error_text=None,
        )
        return {
            "id": artwork_id,
            "folder": folder_text,
            "status": "ready",
            "source_kind": str(source["kind"]),
            "cache_sha256": cache_sha256,
            "width": width,
            "height": height,
            "changed": True,
        }
    except Exception as exc:
        _remove_cache_file(str(destination), data_root)
        artwork_id = _upsert_artwork(
            db_path,
            folder=folder_text,
            source_kind=str(source["kind"]),
            source_path=str(source["path"]),
            source_signature=signature,
            cache_path=None,
            cache_sha256=None,
            width=None,
            height=None,
            status="error",
            updated_at=updated_at,
            error_text=str(exc),
        )
        return {
            "id": artwork_id,
            "folder": folder_text,
            "status": "error",
            "source_kind": str(source["kind"]),
            "error": str(exc),
            "changed": True,
        }


def prune_album_artwork(db_path: Path, data_root: Path) -> dict[str, int]:
    """Remove cache rows/files only for folders no longer represented in the local track index."""
    with db.session(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM album_art
            WHERE folder NOT IN (SELECT DISTINCT folder FROM tracks)
            """
        ).fetchall()
    for row in rows:
        _remove_cache_file(row["cache_path"], data_root)
    if rows:
        ids = [(int(row["id"]),) for row in rows]
        with db.session(db_path) as conn:
            conn.executemany("DELETE FROM album_art WHERE id=?", ids)
    return {"removed": len(rows)}


def artwork_summary(db_path: Path) -> dict[str, int]:
    with db.session(db_path) as conn:
        rows = conn.execute("SELECT status,COUNT(*) count FROM album_art GROUP BY status").fetchall()
    counts = {str(row["status"]): int(row["count"] or 0) for row in rows}
    return {
        "ready": counts.get("ready", 0),
        "missing": counts.get("missing", 0),
        "error": counts.get("error", 0),
        "total": sum(counts.values()),
    }


def build_artwork_router(db_path: Path, data_root: Path) -> APIRouter:
    router = APIRouter()
    root = _cache_root(data_root)

    @router.get("/api/artwork/albums/{artwork_id}")
    def album_artwork(artwork_id: int) -> FileResponse:
        with db.session(db_path) as conn:
            row = conn.execute(
                "SELECT cache_path,status,cache_sha256 FROM album_art WHERE id=?",
                (artwork_id,),
            ).fetchone()
        if not row or row["status"] != "ready" or not row["cache_path"]:
            raise HTTPException(status_code=404, detail="Album artwork is not cached")
        path = Path(str(row["cache_path"]))
        if not _inside(path, root) or not path.is_file():
            raise HTTPException(status_code=404, detail="Album artwork cache file is unavailable")
        headers = {"Cache-Control": "public, max-age=300"}
        if row["cache_sha256"]:
            headers["ETag"] = f'"{row["cache_sha256"]}"'
        return FileResponse(path, media_type="image/png", headers=headers)

    @router.get("/api/artwork/status")
    def artwork_status() -> dict[str, int]:
        return artwork_summary(db_path)

    return router
