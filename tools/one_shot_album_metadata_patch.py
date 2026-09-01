from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_db() -> None:
    path = Path("app/db.py")
    text = path.read_text(encoding="utf-8")

    marker = "\n    album_folders: dict[tuple[str, str], list[str]] = {}\n"
    insertion = '''
        album_health_rows = db.execute(
            """
            SELECT
              COALESCE(albumartist,'') albumartist,
              COALESCE(album,'') album,
              SUM(CASE WHEN releasetype IS NULL OR TRIM(releasetype)='' THEN 1 ELSE 0 END) missing_releasetype,
              COUNT(DISTINCT NULLIF(TRIM(releasetype),'')) releasetype_values,
              SUM(CASE WHEN musicbrainz_albumid IS NULL OR TRIM(musicbrainz_albumid)='' THEN 1 ELSE 0 END) missing_mbid,
              COUNT(DISTINCT NULLIF(TRIM(musicbrainz_albumid),'')) mbid_values
            FROM tracks
            GROUP BY albumartist,album
            """
        ).fetchall()
        mbid_identity_rows = db.execute(
            """
            SELECT
              TRIM(musicbrainz_albumid) mbid,
              COALESCE(TRIM(albumartist),'') albumartist,
              COALESCE(TRIM(album),'') album
            FROM tracks
            WHERE musicbrainz_albumid IS NOT NULL AND TRIM(musicbrainz_albumid)<>''
            GROUP BY mbid,albumartist,album
            """
        ).fetchall()

    album_folders: dict[tuple[str, str], list[str]] = {}
'''
    text = replace_once(text, marker, insertion, "db album health queries")

    old = '''    folder_health = {str(row["folder"]): dict(row) for row in folder_health_rows}

    def any_folder_problem'''
    new = '''    folder_health = {str(row["folder"]): dict(row) for row in folder_health_rows}
    album_health = {
        (str(row["albumartist"]), str(row["album"])): dict(row)
        for row in album_health_rows
    }
    mbid_identities: dict[str, set[tuple[str, str]]] = {}
    for item in mbid_identity_rows:
        mbid_identities.setdefault(str(item["mbid"]), set()).add(
            (str(item["albumartist"]), str(item["album"]))
        )
    conflicting_mbids = {
        mbid for mbid, identities in mbid_identities.items() if len(identities) > 1
    }

    def any_folder_problem'''
    text = replace_once(text, old, new, "db album health maps")

    old = '''        if folders:
            row["folder"] = folders[0]
        if any_folder_problem(folders, "missing_albumartist", "albumartist_values"):
'''
    new = '''        if folders:
            row["folder"] = folders[0]
        logical_health = album_health.get((str(row["albumartist"]), str(row["album"])), {})
        if logical_health.get("missing_releasetype") or logical_health.get("releasetype_values") != 1:
            blockers.append("RELEASETYPE missing or inconsistent across logical album")
        if logical_health.get("missing_mbid") or logical_health.get("mbid_values") != 1:
            blockers.append("MUSICBRAINZ_ALBUMID missing or inconsistent across logical album")
        row_mbids = [value.strip() for value in str(row.get("mbids") or "").split(",") if value.strip()]
        for mbid in row_mbids:
            if mbid in conflicting_mbids:
                blockers.append(
                    f"MUSICBRAINZ_ALBUMID {mbid} maps to conflicting ALBUMARTIST/ALBUM values"
                )
        if any_folder_problem(folders, "missing_albumartist", "albumartist_values"):
'''
    text = replace_once(text, old, new, "db candidate logical blockers")

    text = replace_once(
        text,
        '        row["blockers"] = blockers\n',
        '        row["blockers"] = list(dict.fromkeys(blockers))\n',
        "db blocker dedupe",
    )
    path.write_text(text, encoding="utf-8")


def patch_review() -> None:
    path = Path("app/review.py")
    text = path.read_text(encoding="utf-8")

    old = '''    with db.session(db_path) as conn:
        for key in album_keys:
'''
    new = '''    with db.session(db_path) as conn:
        mbid_identity_rows = conn.execute(
            """
            SELECT
              TRIM(musicbrainz_albumid) mbid,
              COALESCE(TRIM(albumartist),'') albumartist,
              COALESCE(TRIM(album),'') album
            FROM tracks
            WHERE musicbrainz_albumid IS NOT NULL AND TRIM(musicbrainz_albumid)<>''
            GROUP BY mbid,albumartist,album
            """
        ).fetchall()
        mbid_identities: dict[str, set[tuple[str, str]]] = {}
        for item in mbid_identity_rows:
            mbid_identities.setdefault(str(item["mbid"]), set()).add(
                (str(item["albumartist"]), str(item["album"]))
            )

        for key in album_keys:
'''
    text = replace_once(text, old, new, "review mbid identity preload")

    old = '''            album_warnings: list[str] = []
            album_blockers: list[str] = []
            matching = 0

            folder_counts: dict[str, int] = {}
'''
    new = '''            album_warnings: list[str] = []
            album_blockers: list[str] = []
            matching = 0

            indexed_items = [dict(row) for row in rows]
            for field, tag_name in KEY_TAGS:
                values = sorted({
                    str(item.get(field) or "").strip()
                    for item in indexed_items
                    if str(item.get(field) or "").strip()
                }, key=str.casefold)
                missing_count = sum(
                    1 for item in indexed_items if not str(item.get(field) or "").strip()
                )
                if missing_count:
                    album_blockers.append(
                        f"{tag_name} missing on {missing_count} indexed track(s) across logical album"
                    )
                if len(values) > 1:
                    album_blockers.append(
                        f"{tag_name} inconsistent across logical album: {' | '.join(values)}"
                    )

            selected_mbids = sorted({
                str(item.get("musicbrainz_albumid") or "").strip()
                for item in indexed_items
                if str(item.get("musicbrainz_albumid") or "").strip()
            })
            for mbid in selected_mbids:
                identities = mbid_identities.get(mbid, set())
                if len(identities) > 1:
                    identity_text = "; ".join(
                        f"{artist or '<missing>'} / {title or '<missing>'}"
                        for artist, title in sorted(identities, key=lambda value: (value[0].casefold(), value[1].casefold()))
                    )
                    album_blockers.append(
                        f"MUSICBRAINZ_ALBUMID {mbid} maps to conflicting ALBUMARTIST/ALBUM identities in the index: {identity_text}"
                    )

            folder_counts: dict[str, int] = {}
'''
    text = replace_once(text, old, new, "review logical metadata blockers")
    path.write_text(text, encoding="utf-8")


def patch_issues() -> None:
    path = Path("app/issues.py")
    text = path.read_text(encoding="utf-8")

    old = '''    affected: list[dict[str, Any]],
    summary: str,
) -> dict[str, Any]:
'''
    new = '''    affected: list[dict[str, Any]],
    summary: str,
    folders: list[str] | None = None,
) -> dict[str, Any]:
'''
    text = replace_once(text, old, new, "issues signature")

    old = '''        "album": album,
        "folder": folder,
        "summary": summary,
'''
    new = '''        "album": album,
        "folder": folder,
        "folders": sorted(set(folders or ([folder] if folder else [])), key=str.casefold),
        "summary": summary,
'''
    text = replace_once(text, old, new, "issues folders field")

    marker = '''    # Duplicate release IDs across different folders are informational; they may be deliberate.
'''
    insertion = '''    # Cross-folder checks operate on the logical album identity used by the Library and
    # conversion review: ALBUMARTIST + ALBUM. Folder-local checks above remain important because a
    # bad ALBUMARTIST/ALBUM value can otherwise split a damaged release into separate logical rows.
    by_album: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_album[(_text(row.get("albumartist")), _text(row.get("album")))].append(row)
    for (_albumartist, _album), tracks in sorted(
        by_album.items(), key=lambda item: (item[0][0].lower(), item[0][1].lower())
    ):
        folders = sorted({str(track["folder"]) for track in tracks}, key=str.casefold)
        if len(folders) < 2:
            continue
        for field, tag_name in (
            ("releasetype", "RELEASETYPE"),
            ("musicbrainz_albumid", "MUSICBRAINZ_ALBUMID"),
        ):
            values = sorted({_text(track.get(field)) for track in tracks if _text(track.get(field))}, key=str.casefold)
            if len(values) <= 1:
                continue
            affected = [
                {
                    "path": track["path"],
                    "filename": track["filename"],
                    "value": _track_value(track, field),
                }
                for track in tracks
            ]
            issues.append(_issue(
                "blocking",
                f"inconsistent_{field}_across_folders",
                folders[0],
                tracks,
                affected,
                f"{tag_name} is inconsistent across {len(folders)} folders in this logical album: {' | '.join(values)}.",
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

    # Duplicate release IDs across different folders are informational; they may be deliberate.
'''
    text = replace_once(text, marker, insertion, "issues album-wide diagnostics")

    old = '''    for mbid, folders in sorted(mbid_folders.items()):
        if len(folders) < 2:
            continue
'''
    new = '''    for mbid, folders in sorted(mbid_folders.items()):
        if len(folders) < 2 or mbid in conflicting_mbids:
            continue
'''
    text = replace_once(text, old, new, "issues duplicate conflict suppression")

    start = text.index('def render_issues_txt(')
    end = text.index('\ndef render_issues_csv(', start)
    new_txt = '''def render_issues_txt(issues: list[dict[str, Any]], timezone: str) -> str:
    out = [f"SoX Resampler Web Metadata Issues ({timezone})", f"Issues: {len(issues)}", ""]
    for issue in issues:
        folders = issue.get("folders") or ([issue.get("folder", "")] if issue.get("folder") else [])
        out.extend([
            f"[{issue['severity'].upper()}] {issue['albumartist']} / {issue['album']}",
            f"Path{'s' if len(folders) != 1 else ''}: {' | '.join(folders)}",
            f"Issue: {issue['summary']}",
        ])
        for track in issue["affected_tracks"]:
            track_path = track.get("path", "")
            suffix = f" [{track_path}]" if track_path else ""
            out.append(f"  {track['filename']}: {track['value']}{suffix}")
        out.append("")
    return "\\n".join(out)

'''
    text = text[:start] + new_txt + text[end + 1:]

    start = text.index('def render_issues_csv(')
    new_csv = '''def render_issues_csv(issues: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "severity", "issue_type", "albumartist", "album", "folder", "path",
        "track", "current_value", "summary",
    ])
    for issue in issues:
        affected = issue["affected_tracks"] or [{"filename": "", "value": "", "path": ""}]
        for track in affected:
            track_path = str(track.get("path", ""))
            folder = str(Path(track_path).parent) if track_path else issue.get("folder", "")
            writer.writerow([
                issue["severity"], issue["issue_type"], issue["albumartist"], issue["album"],
                folder, track_path, track.get("filename", ""), track.get("value", ""), issue["summary"],
            ])
    return buffer.getvalue()
'''
    text = text[:start] + new_csv + "\n"
    path.write_text(text, encoding="utf-8")


def patch_issues_ui() -> None:
    path = Path("app/static/issues-ui.js")
    text = path.read_text(encoding="utf-8")

    old = '''  const tracks=(issue.affected_tracks||[]).map(t=>`${t.filename||''} ${t.path||''} ${t.value||''}`).join(' ');
  return `${issue.albumartist||''} ${issue.album||''} ${issue.folder||''} ${issue.summary||''} ${issue.issue_type||''} ${tracks}`.toLowerCase().includes(issueUiState.query);
'''
    new = '''  const tracks=(issue.affected_tracks||[]).map(t=>`${t.filename||''} ${t.path||''} ${t.value||''}`).join(' ');
  const folders=(issue.folders||[]).join(' ');
  return `${issue.albumartist||''} ${issue.album||''} ${issue.folder||''} ${folders} ${issue.summary||''} ${issue.issue_type||''} ${tracks}`.toLowerCase().includes(issueUiState.query);
'''
    text = replace_once(text, old, new, "issues UI search folders")

    old = '''  box.innerHTML=rows.map((issue,index)=>`\n    <section class="card issueCard" data-issue-index="${index}">\n      <div class="issueHead"><span class="statusPill ${esc(issue.severity)}">${esc(issue.severity)}</span><div class="issueHeadMain"><div class="issueArtist">${esc(issue.albumartist||'Missing Album Artist')}</div><div class="issueAlbum">${esc(issue.album||'Missing Album')}</div><div class="issueSummaryText">${esc(issue.summary||'')}</div><div class="issueType">${esc(issue.issue_type||'')}</div></div></div>\n      <div class="issueFolder"><span class="muted">Folder</span><code>${esc(issue.folder||'')}</code><button data-copy-folder="${index}">Copy Path</button></div>\n      <div class="issueTracks">${(issue.affected_tracks||[]).map((track,trackIndex)=>`<div class="issueTrack"><code>${esc(track.filename||track.path||'Unknown track')}</code><span>${esc(track.value||'')}</span><button data-copy-track="${index}:${trackIndex}">Copy Track Path</button></div>`).join('')}</div>\n    </section>`).join('');\n\n  box.querySelectorAll('[data-copy-folder]').forEach(button=>button.onclick=()=>{const issue=rows[Number(button.dataset.copyFolder)];navigator.clipboard?.writeText(issue.folder||'')});\n'''
    new = '''  box.innerHTML=rows.map((issue,index)=>{\n    const folders=(issue.folders||[]).length?issue.folders:[issue.folder].filter(Boolean);\n    return `\n    <section class="card issueCard" data-issue-index="${index}">\n      <div class="issueHead"><span class="statusPill ${esc(issue.severity)}">${esc(issue.severity)}</span><div class="issueHeadMain"><div class="issueArtist">${esc(issue.albumartist||'Missing Album Artist')}</div><div class="issueAlbum">${esc(issue.album||'Missing Album')}</div><div class="issueSummaryText">${esc(issue.summary||'')}</div><div class="issueType">${esc(issue.issue_type||'')}</div></div></div>\n      ${folders.map((folder,folderIndex)=>`<div class="issueFolder"><span class="muted">${folders.length===1?'Folder':`Folder ${folderIndex+1}`}</span><code>${esc(folder)}</code><button data-copy-folder="${index}:${folderIndex}">Copy Path</button></div>`).join('')}\n      <div class="issueTracks">${(issue.affected_tracks||[]).map((track,trackIndex)=>`<div class="issueTrack"><code>${esc(track.filename||track.path||'Unknown track')}</code><span>${esc(track.value||'')}</span><button data-copy-track="${index}:${trackIndex}">Copy Track Path</button></div>`).join('')}</div>\n    </section>`;\n  }).join('');\n\n  box.querySelectorAll('[data-copy-folder]').forEach(button=>button.onclick=()=>{const [i,f]=button.dataset.copyFolder.split(':').map(Number);const issue=rows[i];const folders=(issue?.folders||[]).length?issue.folders:[issue?.folder].filter(Boolean);navigator.clipboard?.writeText(folders[f]||'')});\n'''
    text = replace_once(text, old, new, "issues UI multi-folder rendering")
    path.write_text(text, encoding="utf-8")


def patch_candidate_tests() -> None:
    path = Path("tests/test_candidate_albums.py")
    text = path.read_text(encoding="utf-8")
    marker = '''    def test_inconsistent_critical_tag_in_folder_blocks_candidate_rows(self) -> None:
'''
    insertion = '''    def test_cross_folder_releasetype_conflict_blocks_logical_album(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "library.db"
            db.init(db_path)
            for index, (folder, releasetype) in enumerate((
                ("/music/Test Artist/Test Album/Disc 1", "album"),
                ("/music/Test Artist/Test Album/Disc 2", "album; compilation"),
            ), start=1):
                self._insert_track(
                    db_path,
                    path=f"{folder}/01.flac",
                    folder=folder,
                    rate=96000,
                    size=1000,
                    tracknumber=str(index),
                    releasetype=releasetype,
                )

            rows = db.candidate_albums(db_path, [96000], above=None)
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["selectable"])
            self.assertIn(
                "RELEASETYPE missing or inconsistent across logical album",
                rows[0]["blockers"],
            )

    def test_shared_mbid_with_conflicting_album_identity_blocks_each_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "library.db"
            db.init(db_path)
            self._insert_track(
                db_path,
                path="/music/Test Artist/Test Album/01.flac",
                folder="/music/Test Artist/Test Album",
                rate=96000,
                size=1000,
                tracknumber="1",
                mbid="shared-mbid",
            )
            self._insert_track(
                db_path,
                path="/music/Other Artist/Other Album/01.flac",
                folder="/music/Other Artist/Other Album",
                rate=96000,
                size=1000,
                tracknumber="1",
                albumartist="Other Artist",
                album="Other Album",
                mbid="shared-mbid",
            )

            rows = db.candidate_albums(db_path, [96000], above=None)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(not row["selectable"] for row in rows))
            self.assertTrue(all(
                any("maps to conflicting ALBUMARTIST/ALBUM values" in blocker for blocker in row["blockers"])
                for row in rows
            ))

    def test_inconsistent_critical_tag_in_folder_blocks_candidate_rows(self) -> None:
'''
    text = replace_once(text, marker, insertion, "candidate album-wide tests")
    path.write_text(text, encoding="utf-8")


def patch_review_tests() -> None:
    path = Path("tests/test_review_revalidation.py")
    text = path.read_text(encoding="utf-8")
    marker = '''    def test_exact_path_retry_review_does_not_pull_other_matching_tracks(self) -> None:
'''
    insertion = '''    def test_cross_folder_releasetype_conflict_blocks_start(self) -> None:
        second_folder = self.folder / "Disc 2"
        second_folder.mkdir()
        second = second_folder / "02 - Conflict.flac"
        second.write_bytes(self.track.read_bytes())
        audio = FLAC(second)
        audio["TRACKNUMBER"] = ["2"]
        audio["DISCNUMBER"] = ["2"]
        audio["RELEASETYPE"] = ["album; compilation"]
        audio.save()
        refresh_track(
            self.db_path,
            self.music,
            second,
            "America/Indiana/Indianapolis",
        )

        review = self.review()
        self.assertFalse(review["can_start"])
        self.assertIn("RELEASETYPE inconsistent across logical album", " | ".join(review["blockers"]))

    def test_shared_mbid_with_conflicting_identity_blocks_start(self) -> None:
        other_folder = self.music / "Other Artist" / "Other Album"
        other_folder.mkdir(parents=True)
        other = other_folder / "01 - Other.flac"
        other.write_bytes(self.track.read_bytes())
        audio = FLAC(other)
        audio["ALBUMARTIST"] = ["Other Artist"]
        audio["ALBUM"] = ["Other Album"]
        audio["TRACKNUMBER"] = ["1"]
        audio.save()
        refresh_track(
            self.db_path,
            self.music,
            other,
            "America/Indiana/Indianapolis",
        )

        review = self.review()
        self.assertFalse(review["can_start"])
        text = " | ".join(review["blockers"])
        self.assertIn("maps to conflicting ALBUMARTIST/ALBUM identities", text)
        self.assertIn("Other Artist / Other Album", text)

    def test_exact_path_retry_review_does_not_pull_other_matching_tracks(self) -> None:
'''
    text = replace_once(text, marker, insertion, "review album-wide tests")
    path.write_text(text, encoding="utf-8")


def patch_issue_tests() -> None:
    path = Path("tests/test_issues.py")
    text = path.read_text(encoding="utf-8")
    marker = '''    def test_issue_exports_contain_severity_path_and_track(self) -> None:
'''
    insertion = '''    def test_cross_folder_releasetype_conflict_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(
                db_path,
                folder="/music/Test Artist/Test Album/Disc 1",
                path="/music/Test Artist/Test Album/Disc 1/01.flac",
                rel_path="Test Artist/Test Album/Disc 1/01.flac",
            )
            self._insert_track(
                db_path,
                folder="/music/Test Artist/Test Album/Disc 2",
                path="/music/Test Artist/Test Album/Disc 2/02.flac",
                rel_path="Test Artist/Test Album/Disc 2/02.flac",
                filename="02.flac",
                tracknumber="2",
                discnumber="2",
                releasetype="album; compilation",
            )
            issues = build_metadata_issues(db_path)
            issue = next(i for i in issues if i["issue_type"] == "inconsistent_releasetype_across_folders")
            self.assertEqual(issue["severity"], "blocking")
            self.assertEqual(len(issue["folders"]), 2)
            self.assertEqual({t["value"] for t in issue["affected_tracks"]}, {"album", "album; compilation"})

    def test_shared_mbid_identity_conflict_is_blocking_not_duplicate_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db.init(db_path)
            self._insert_track(db_path, musicbrainz_albumid="shared-mbid")
            self._insert_track(
                db_path,
                path="/music/Other Artist/Other Album/01.flac",
                rel_path="Other Artist/Other Album/01.flac",
                folder="/music/Other Artist/Other Album",
                albumartist="Other Artist",
                album="Other Album",
                musicbrainz_albumid="shared-mbid",
            )
            issues = build_metadata_issues(db_path)
            conflict = next(i for i in issues if i["issue_type"] == "musicbrainz_albumid_identity_conflict")
            self.assertEqual(conflict["severity"], "blocking")
            self.assertEqual(len(conflict["affected_tracks"]), 2)
            self.assertFalse(any(
                i["issue_type"] == "duplicate_musicbrainz_albumid"
                and any(t["value"] == "shared-mbid" for t in i["affected_tracks"])
                for i in issues
            ))

    def test_issue_exports_contain_severity_path_and_track(self) -> None:
'''
    text = replace_once(text, marker, insertion, "issues album-wide tests")

    old = '''            self.assertIn("severity,issue_type", csv_text)
            self.assertIn("missing_releasetype", csv_text)
'''
    new = '''            self.assertIn("severity,issue_type", csv_text)
            self.assertIn("path,track,current_value", csv_text)
            self.assertIn("/music/Test Artist/Test Album/01.flac", csv_text)
            self.assertIn("missing_releasetype", csv_text)
'''
    text = replace_once(text, old, new, "issues export path assertion")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_db()
    patch_review()
    patch_issues()
    patch_issues_ui()
    patch_candidate_tests()
    patch_review_tests()
    patch_issue_tests()


if __name__ == "__main__":
    main()
