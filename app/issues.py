from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import db

CRITICAL_FIELDS = (
    ("albumartist", "ALBUMARTIST"),
    ("album", "ALBUM"),
    ("releasetype", "RELEASETYPE"),
    ("musicbrainz_albumid", "MUSICBRAINZ_ALBUMID"),
)
REPLAYGAIN_FIELDS = (
    ("replaygain_track_gain", "REPLAYGAIN_TRACK_GAIN"),
    ("replaygain_track_peak", "REPLAYGAIN_TRACK_PEAK"),
    ("replaygain_album_gain", "REPLAYGAIN_ALBUM_GAIN"),
    ("replaygain_album_peak", "REPLAYGAIN_ALBUM_PEAK"),
)
STANDARD_HIGH_RATES = {88200, 96000, 176400, 192000}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _track_value(track: dict[str, Any], field: str) -> str:
    value = _text(track.get(field))
    return value if value else "(missing)"


def _display_album(tracks: list[dict[str, Any]]) -> tuple[str, str]:
    artists = sorted({_text(t.get("albumartist")) for t in tracks if _text(t.get("albumartist"))})
    albums = sorted({_text(t.get("album")) for t in tracks if _text(t.get("album"))})
    artist = artists[0] if len(artists) == 1 else (" / ".join(artists) if artists else "Missing Album Artist")
    album = albums[0] if len(albums) == 1 else (" / ".join(albums) if albums else "Missing Album")
    return artist, album


def _issue(
    severity: str,
    issue_type: str,
    folder: str,
    tracks: list[dict[str, Any]],
    affected: list[dict[str, Any]],
    summary: str,
    folders: list[str] | None = None,
) -> dict[str, Any]:
    artist, album = _display_album(tracks)
    return {
        "severity": severity,
        "issue_type": issue_type,
        "albumartist": artist,
        "album": album,
        "folder": folder,
        "folders": sorted(set(folders or ([folder] if folder else [])), key=str.casefold),
        "summary": summary,
        "affected_tracks": affected,
    }


def build_metadata_issues(db_path: Path) -> list[dict[str, Any]]:
    """Return album-folder-scoped metadata problems with exact affected tracks.

    Folder grouping is intentional here: a bad ALBUMARTIST or ALBUM tag must not split the
    physical release into separate groups and thereby hide the inconsistency we are trying to
    report. Normal library browsing still groups strictly by ALBUMARTIST + ALBUM.
    """
    with db.session(db_path) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM tracks ORDER BY folder,path").fetchall()]

    by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_folder[str(row["folder"])].append(row)

    issues: list[dict[str, Any]] = []
    for folder, tracks in sorted(by_folder.items(), key=lambda item: item[0].lower()):
        for field, tag_name in CRITICAL_FIELDS:
            values = {_text(t.get(field)) for t in tracks if _text(t.get(field))}
            missing = [
                {"path": t["path"], "filename": t["filename"], "value": "(missing)"}
                for t in tracks if not _text(t.get(field))
            ]
            if missing:
                issues.append(_issue(
                    "blocking", f"missing_{field}", folder, tracks, missing,
                    f"{tag_name} is missing from {len(missing)} track(s).",
                ))
            if len(values) > 1:
                affected = [
                    {"path": t["path"], "filename": t["filename"], "value": _track_value(t, field)}
                    for t in tracks
                ]
                issues.append(_issue(
                    "blocking", f"inconsistent_{field}", folder, tracks, affected,
                    f"{tag_name} is inconsistent across this album folder.",
                ))

        replaygain_affected: list[dict[str, Any]] = []
        for track in tracks:
            missing_tags = [name for field, name in REPLAYGAIN_FIELDS if not _text(track.get(field))]
            if missing_tags:
                replaygain_affected.append({
                    "path": track["path"],
                    "filename": track["filename"],
                    "value": ", ".join(missing_tags),
                })
        if replaygain_affected:
            issues.append(_issue(
                "warning", "replaygain_incomplete", folder, tracks, replaygain_affected,
                f"ReplayGain is incomplete on {len(replaygain_affected)} track(s).",
            ))

        multichannel = [
            {"path": t["path"], "filename": t["filename"], "value": f"{t.get('channels')} channels"}
            for t in tracks if int(t.get("channels") or 0) > 2
        ]
        if multichannel:
            issues.append(_issue(
                "info", "multichannel", folder, tracks, multichannel,
                f"Multichannel FLAC detected on {len(multichannel)} track(s).",
            ))

        oddball = [
            {"path": t["path"], "filename": t["filename"], "value": f"{int(t['sample_rate'])} Hz"}
            for t in tracks
            if int(t.get("sample_rate") or 0) > 48000 and int(t.get("sample_rate") or 0) not in STANDARD_HIGH_RATES
        ]
        if oddball:
            issues.append(_issue(
                "info", "oddball_sample_rate", folder, tracks, oddball,
                f"Non-standard sample rate above 48 kHz detected on {len(oddball)} track(s).",
            ))

    # Cross-folder release checks are keyed by MusicBrainz release ID when present. A shared
    # MBID across Disc 01/Disc 02/etc. is normal for one multidisc release and is not an issue.
    # Same artist/title with different MBIDs are separate releases and must never be merged.
    by_release: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mbid = _text(row.get("musicbrainz_albumid"))
        release_key = ("mbid", mbid.casefold()) if mbid else ("folder", str(row["folder"]).casefold())
        by_release[release_key].append(row)
    for (_kind, _release_id), tracks in sorted(by_release.items(), key=lambda item: item[0]):
        folders = sorted({str(track["folder"]) for track in tracks}, key=str.casefold)
        if len(folders) < 2:
            continue
        values = sorted({_text(track.get("releasetype")) for track in tracks if _text(track.get("releasetype"))}, key=str.casefold)
        if len(values) > 1:
            affected = [
                {
                    "path": track["path"],
                    "filename": track["filename"],
                    "value": _track_value(track, "releasetype"),
                }
                for track in tracks
            ]
            issues.append(_issue(
                "blocking",
                "inconsistent_releasetype_across_folders",
                folders[0],
                tracks,
                affected,
                f"RELEASETYPE is inconsistent across {len(folders)} folders in this release: {' | '.join(values)}.",
                folders=folders,
            ))

    # A MusicBrainz release ID should not point at conflicting ALBUMARTIST/ALBUM identities. Exact
    # duplicate folders with the same identity remain informational below, because they can be
    # deliberate. Identity conflicts are blocking and include every affected track/value.
    mbid_tracks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        mbid = _text(row.get("musicbrainz_albumid"))
        if mbid:
            mbid_tracks[mbid].append(row)
    conflicting_mbids: set[str] = set()
    for mbid, tracks in sorted(mbid_tracks.items()):
        identities = {
            (_text(track.get("albumartist")), _text(track.get("album")))
            for track in tracks
        }
        if len(identities) <= 1:
            continue
        conflicting_mbids.add(mbid)
        folders = sorted({str(track["folder"]) for track in tracks}, key=str.casefold)
        affected = [
            {
                "path": track["path"],
                "filename": track["filename"],
                "value": (
                    f"ALBUMARTIST={_track_value(track, 'albumartist')}; "
                    f"ALBUM={_track_value(track, 'album')}; MUSICBRAINZ_ALBUMID={mbid}"
                ),
            }
            for track in tracks
        ]
        issues.append(_issue(
            "blocking",
            "musicbrainz_albumid_identity_conflict",
            folders[0] if folders else "",
            tracks,
            affected,
            f"MusicBrainz Album ID {mbid} maps to conflicting ALBUMARTIST/ALBUM identities.",
            folders=folders,
        ))

    # A shared MusicBrainz release ID across multiple physical folders is expected for
    # multidisc releases, so it is intentionally not reported as a duplicate.

    order = {"blocking": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: (order.get(i["severity"], 9), i["albumartist"].lower(), i["album"].lower(), i["issue_type"]))
    return issues


def filter_issues(issues: list[dict[str, Any]], severity: str | None = None) -> list[dict[str, Any]]:
    if not severity or severity == "all":
        return issues
    if severity not in {"blocking", "warning", "info"}:
        raise ValueError("Invalid issue severity")
    return [issue for issue in issues if issue["severity"] == severity]


def render_issues_txt(issues: list[dict[str, Any]], timezone: str) -> str:
    out = [f"SoX Resampler Web Metadata Issues ({timezone})", f"Issues: {len(issues)}", ""]
    for issue in issues:
        folders = issue.get("display_folders") or issue.get("folders") or ([issue.get("display_folder") or issue.get("folder", "")] if (issue.get("display_folder") or issue.get("folder")) else [])
        out.extend([
            f"[{issue['severity'].upper()}] {issue['albumartist']} / {issue['album']}",
            f"Path{'s' if len(folders) != 1 else ''}: {' | '.join(folders)}",
            f"Issue: {issue['summary']}",
        ])
        for track in issue["affected_tracks"]:
            track_path = track.get("display_path") or track.get("path", "")
            suffix = f" [{track_path}]" if track_path else ""
            out.append(f"  {track['filename']}: {track['value']}{suffix}")
        out.append("")
    return "\n".join(out)

def render_issues_csv(issues: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "severity", "issue_type", "albumartist", "album", "folder", "path",
        "track", "current_value", "summary",
    ])
    for issue in issues:
        affected = issue["affected_tracks"] or [{"filename": "", "value": "", "path": ""}]
        for track in affected:
            track_path = str(track.get("display_path") or track.get("path", ""))
            folder = str(Path(track_path).parent) if track_path else (issue.get("display_folder") or issue.get("folder", ""))
            writer.writerow([
                issue["severity"], issue["issue_type"], issue["albumartist"], issue["album"],
                folder, track_path, track.get("filename", ""), track.get("value", ""), issue["summary"],
            ])
    return buffer.getvalue()

