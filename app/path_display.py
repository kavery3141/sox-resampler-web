from __future__ import annotations

from pathlib import Path
from typing import Any


def host_music_path(value: str | Path | None, music_root: Path, host_music_root: Path) -> str:
    """Map an internal music-mount path to its host-visible TrueNAS path.

    Operational paths remain unchanged. Values outside the configured music root are returned
    unchanged so diagnostics never invent a host path for unrelated files.
    """
    if value is None:
        return ""
    text = str(value)
    try:
        relative = Path(text).relative_to(music_root)
    except ValueError:
        return text
    return str(host_music_root / relative)


def decorate_album_paths(
    album: dict[str, Any], music_root: Path, host_music_root: Path
) -> dict[str, Any]:
    folder = album.get("folder")
    if folder:
        album["display_folder"] = host_music_path(folder, music_root, host_music_root)
    folders = album.get("folders")
    if isinstance(folders, list):
        album["display_folders"] = [
            host_music_path(folder, music_root, host_music_root) for folder in folders
        ]
    tracks = album.get("tracks")
    if isinstance(tracks, list):
        for track in tracks:
            if not isinstance(track, dict):
                continue
            path = track.get("path")
            if path:
                track["display_path"] = host_music_path(path, music_root, host_music_root)
            track_folder = track.get("folder")
            if track_folder:
                track["display_folder"] = host_music_path(
                    track_folder, music_root, host_music_root
                )
    return album


def decorate_review_paths(
    review: dict[str, Any], music_root: Path, host_music_root: Path
) -> dict[str, Any]:
    for album in review.get("albums") or []:
        if isinstance(album, dict):
            decorate_album_paths(album, music_root, host_music_root)
    review["host_music_root"] = str(host_music_root)
    return review


def decorate_issue_paths(
    issues: list[dict[str, Any]], music_root: Path, host_music_root: Path
) -> list[dict[str, Any]]:
    for issue in issues:
        folder = issue.get("folder")
        if folder:
            issue["display_folder"] = host_music_path(folder, music_root, host_music_root)
        folders = issue.get("folders")
        if isinstance(folders, list):
            issue["display_folders"] = [
                host_music_path(item, music_root, host_music_root) for item in folders
            ]
        for track in issue.get("affected_tracks") or []:
            if isinstance(track, dict) and track.get("path"):
                track["display_path"] = host_music_path(
                    track["path"], music_root, host_music_root
                )
    return issues


def decorate_job_report_paths(
    report: dict[str, Any], music_root: Path, host_music_root: Path
) -> dict[str, Any]:
    for item in report.get("files") or []:
        if isinstance(item, dict) and item.get("path"):
            item["display_path"] = host_music_path(
                item["path"], music_root, host_music_root
            )
    report["host_music_root"] = str(host_music_root)
    return report
