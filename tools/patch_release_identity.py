from pathlib import Path

# Correct release identity handling so same-title releases with different MBIDs stay separate,
# while multidisc folders sharing one MBID remain one logical release.

# --- app/issues.py ---
p = Path('app/issues.py')
text = p.read_text()
start = text.index('    # Cross-folder checks operate on the logical album identity used by the Library and\n')
end = text.index('    # A MusicBrainz release ID should not point at conflicting ALBUMARTIST/ALBUM identities.', start)
replacement = '''    # Cross-folder release checks are keyed by MusicBrainz release ID when present. A shared\n    # MBID across Disc 01/Disc 02/etc. is normal for one multidisc release and is not an issue.\n    # Same artist/title with different MBIDs are separate releases and must never be merged.\n    by_release: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)\n    for row in rows:\n        mbid = _text(row.get("musicbrainz_albumid"))\n        release_key = ("mbid", mbid.casefold()) if mbid else ("folder", str(row["folder"]).casefold())\n        by_release[release_key].append(row)\n    for (_kind, _release_id), tracks in sorted(by_release.items(), key=lambda item: item[0]):\n        folders = sorted({str(track["folder"]) for track in tracks}, key=str.casefold)\n        if len(folders) < 2:\n            continue\n        values = sorted({_text(track.get("releasetype")) for track in tracks if _text(track.get("releasetype"))}, key=str.casefold)\n        if len(values) > 1:\n            affected = [\n                {\n                    "path": track["path"],\n                    "filename": track["filename"],\n                    "value": _track_value(track, "releasetype"),\n                }\n                for track in tracks\n            ]\n            issues.append(_issue(\n                "blocking",\n                "inconsistent_releasetype_across_folders",\n                folders[0],\n                tracks,\n                affected,\n                f"RELEASETYPE is inconsistent across {len(folders)} folders in this release: {' | '.join(values)}.",\n                folders=folders,\n            ))\n\n'''
text = text[:start] + replacement + text[end:]
start = text.index('    # Duplicate release IDs across different folders are informational; they may be deliberate.\n')
end = text.index('    order = {"blocking": 0, "warning": 1, "info": 2}', start)
text = text[:start] + '''    # A shared MusicBrainz release ID across multiple physical folders is expected for\n    # multidisc releases, so it is intentionally not reported as a duplicate.\n\n''' + text[end:]
p.write_text(text)

# --- app/db.py ---
p = Path('app/db.py')
text = p.read_text()
text = text.replace(
'''      COALESCE(tracks.albumartist,'') albumartist,\n      COALESCE(tracks.album,'') album,\n      MIN(tracks.folder) folder,''',
'''      COALESCE(tracks.albumartist,'') albumartist,\n      COALESCE(tracks.album,'') album,\n      COALESCE(NULLIF(TRIM(tracks.musicbrainz_albumid),''), tracks.folder) release_key,\n      MIN(tracks.folder) folder,''',
1,
)
text = text.replace(
'''    GROUP BY tracks.albumartist, tracks.album\n    HAVING matching_tracks > 0''',
'''    GROUP BY tracks.albumartist, tracks.album, release_key\n    HAVING matching_tracks > 0''',
1,
)
text = text.replace(
'''            SELECT COALESCE(albumartist,'') albumartist,COALESCE(album,'') album,folder\n            FROM tracks\n            GROUP BY albumartist,album,folder''',
'''            SELECT COALESCE(albumartist,'') albumartist,COALESCE(album,'') album,\n                   COALESCE(NULLIF(TRIM(musicbrainz_albumid),''), folder) release_key,folder\n            FROM tracks\n            GROUP BY albumartist,album,release_key,folder''',
1,
)
text = text.replace(
'''              COALESCE(albumartist,'') albumartist,\n              COALESCE(album,'') album,\n              SUM(CASE WHEN releasetype IS NULL OR TRIM(releasetype)='' THEN 1 ELSE 0 END) missing_releasetype,''',
'''              COALESCE(albumartist,'') albumartist,\n              COALESCE(album,'') album,\n              COALESCE(NULLIF(TRIM(musicbrainz_albumid),''), folder) release_key,\n              SUM(CASE WHEN releasetype IS NULL OR TRIM(releasetype)='' THEN 1 ELSE 0 END) missing_releasetype,''',
1,
)
text = text.replace(
'''            GROUP BY albumartist,album\n            """\n        ).fetchall()\n        mbid_identity_rows''',
'''            GROUP BY albumartist,album,release_key\n            """\n        ).fetchall()\n        mbid_identity_rows''',
1,
)
text = text.replace(
'''    album_folders: dict[tuple[str, str], list[str]] = {}\n    for item in album_folder_rows:\n        key = (str(item["albumartist"]), str(item["album"]))\n        album_folders.setdefault(key, []).append(str(item["folder"]))''',
'''    album_folders: dict[tuple[str, str, str], list[str]] = {}\n    for item in album_folder_rows:\n        key = (str(item["albumartist"]), str(item["album"]), str(item["release_key"]))\n        album_folders.setdefault(key, []).append(str(item["folder"]))''',
1,
)
text = text.replace(
'''    album_health = {\n        (str(row["albumartist"]), str(row["album"])): dict(row)\n        for row in album_health_rows\n    }''',
'''    album_health = {\n        (str(row["albumartist"]), str(row["album"]), str(row["release_key"])): dict(row)\n        for row in album_health_rows\n    }''',
1,
)
text = text.replace(
'''        folders = album_folders.get((str(row["albumartist"]), str(row["album"])), [])''',
'''        release_key = str(row.get("release_key") or row.get("folder") or "")\n        folders = album_folders.get((str(row["albumartist"]), str(row["album"]), release_key), [])''',
1,
)
text = text.replace(
'''        logical_health = album_health.get((str(row["albumartist"]), str(row["album"])), {})''',
'''        logical_health = album_health.get((str(row["albumartist"]), str(row["album"]), release_key), {})''',
1,
)
p.write_text(text)

# --- app/review.py ---
p = Path('app/review.py')
text = p.read_text()
text = text.replace(
'''    Album identity is ALBUMARTIST + ALBUM. All indexed physical folders carrying that identity are\n    reviewed together so multi-disc releases remain one batch album even when discs are stored in\n    separate subfolders. Retry batches pass ``include_paths`` so only exact failed source files are\n    selected while the complete album identity is still revalidated.''',
'''    Release identity is MusicBrainz Album ID when present. This keeps same-title releases with\n    different MBIDs separate while allowing Disc 01/Disc 02/etc. folders sharing one MBID to be\n    reviewed together. When MBID is absent, review falls back conservatively to the requested\n    physical folder. Retry batches pass ``include_paths`` so only exact failed source files are\n    selected while the complete release identity is still revalidated.''',
1,
)
old = '''            rows = conn.execute(\n                """\n                SELECT * FROM tracks\n                WHERE COALESCE(albumartist,'')=? AND COALESCE(album,'')=?\n                ORDER BY CAST(COALESCE(discnumber,'1') AS INTEGER),\n                         CAST(COALESCE(tracknumber,'0') AS INTEGER),\n                         folder COLLATE NOCASE,filename COLLATE NOCASE\n                """,\n                (albumartist, album),\n            ).fetchall()'''
new = '''            identity_rows = conn.execute(\n                """\n                SELECT DISTINCT TRIM(musicbrainz_albumid) mbid\n                FROM tracks\n                WHERE COALESCE(albumartist,'')=? AND COALESCE(album,'')=? AND folder=?\n                  AND musicbrainz_albumid IS NOT NULL AND TRIM(musicbrainz_albumid)<>''\n                """,\n                (albumartist, album, requested_folder),\n            ).fetchall()\n            requested_mbids = sorted({str(item["mbid"]) for item in identity_rows if str(item["mbid"] or "").strip()})\n            if len(requested_mbids) == 1:\n                rows = conn.execute(\n                    """\n                    SELECT * FROM tracks\n                    WHERE TRIM(musicbrainz_albumid)=?\n                    ORDER BY CAST(COALESCE(discnumber,'1') AS INTEGER),\n                             CAST(COALESCE(tracknumber,'0') AS INTEGER),\n                             folder COLLATE NOCASE,filename COLLATE NOCASE\n                    """,\n                    (requested_mbids[0],),\n                ).fetchall()\n            else:\n                rows = conn.execute(\n                    """\n                    SELECT * FROM tracks\n                    WHERE COALESCE(albumartist,'')=? AND COALESCE(album,'')=? AND folder=?\n                    ORDER BY CAST(COALESCE(discnumber,'1') AS INTEGER),\n                             CAST(COALESCE(tracknumber,'0') AS INTEGER),\n                             filename COLLATE NOCASE\n                    """,\n                    (albumartist, album, requested_folder),\n                ).fetchall()'''
if old not in text:
    raise SystemExit('review query anchor not found')
text = text.replace(old, new, 1)
p.write_text(text)

# --- tests ---
p = Path('tests/test_candidate_albums.py')
text = p.read_text()
insert = '''\n    def test_same_title_different_mbids_are_separate_candidates(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            db_path = Path(tmp) / "library.db"\n            db.init(db_path)\n            self._insert_track(\n                db_path, path="/music/Weezer/Weezer (2001)/01.flac", folder="/music/Weezer/Weezer (2001)",\n                rate=96000, size=1000, tracknumber="1", albumartist="Weezer", album="Weezer", mbid="green-album",\n            )\n            self._insert_track(\n                db_path, path="/music/Weezer/Weezer (2019)/01.flac", folder="/music/Weezer/Weezer (2019)",\n                rate=96000, size=1000, tracknumber="1", albumartist="Weezer", album="Weezer", mbid="teal-album",\n            )\n            rows = db.candidate_albums(db_path, [96000], above=None)\n            self.assertEqual(len(rows), 2)\n            self.assertEqual({tuple(row["folders"]) for row in rows}, {\n                ("/music/Weezer/Weezer (2001)",), ("/music/Weezer/Weezer (2019)",),\n            })\n            self.assertTrue(all(row["selectable"] for row in rows))\n\n    def test_multidisc_same_mbid_is_one_candidate_without_duplicate_warning(self) -> None:\n        with tempfile.TemporaryDirectory() as tmp:\n            db_path = Path(tmp) / "library.db"\n            db.init(db_path)\n            for disc in ("Disc 01", "Disc 02", "Disc 03"):\n                folder = f"/music/Test Artist/Test Album/{disc}"\n                self._insert_track(\n                    db_path, path=f"{folder}/01.flac", folder=folder, rate=96000, size=1000,\n                    tracknumber="1", mbid="multidisc-release",\n                )\n            rows = db.candidate_albums(db_path, [96000], above=None)\n            self.assertEqual(len(rows), 1)\n            self.assertEqual(rows[0]["folder_count"], 3)\n            self.assertTrue(rows[0]["selectable"])\n\n'''
marker = '\n\nif __name__ == "__main__":\n'
if marker not in text:
    raise SystemExit('candidate test marker not found')
text = text.replace(marker, insert + marker, 1)
p.write_text(text)

# Add focused metadata issue tests.
p = Path('tests/test_release_identity_issues.py')
p.write_text('''import tempfile\nfrom pathlib import Path\n\nfrom app import db\nfrom app.issues import build_metadata_issues\n\n\ndef _insert(db_path: Path, *, folder: str, album: str, mbid: str, title: str) -> None:\n    path = f"{folder}/{title}.flac"\n    with db.session(db_path) as conn:\n        conn.execute(\n            """INSERT INTO tracks(path,rel_path,folder,filename,size_bytes,mtime_ns,sample_rate,bits_per_sample,channels,duration,albumartist,album,releasetype,musicbrainz_albumid,artist,title,tracknumber,discnumber,replaygain_track_gain,replaygain_track_peak,replaygain_album_gain,replaygain_album_peak,picture_count,first_seen,last_seen,tag_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",\n            (path, path, folder, f"{title}.flac", 1000, 1, 96000, 24, 2, 1.0, "Weezer", album, "album", mbid, "Weezer", title, "1", "1", "-1 dB", "0.5", "-1 dB", "0.5", 0, "x", "x", "{}"),\n        )\n\n\ndef test_same_title_different_mbids_not_reported_as_cross_folder_conflict() -> None:\n    with tempfile.TemporaryDirectory() as tmp:\n        db_path = Path(tmp) / "library.db"\n        db.init(db_path)\n        _insert(db_path, folder="/music/Weezer/Weezer (2001)", album="Weezer", mbid="green", title="One")\n        _insert(db_path, folder="/music/Weezer/Weezer (2019)", album="Weezer", mbid="teal", title="Two")\n        issues = build_metadata_issues(db_path)\n        types = {issue["issue_type"] for issue in issues}\n        assert "inconsistent_musicbrainz_albumid_across_folders" not in types\n        assert "duplicate_musicbrainz_albumid" not in types\n\n\ndef test_multidisc_shared_mbid_not_reported_as_duplicate() -> None:\n    with tempfile.TemporaryDirectory() as tmp:\n        db_path = Path(tmp) / "library.db"\n        db.init(db_path)\n        for index, disc in enumerate(("Disc 01", "Disc 02", "Disc 03"), start=1):\n            _insert(db_path, folder=f"/music/Artist/Album/{disc}", album="Album", mbid="same-release", title=f"Track {index}")\n        issues = build_metadata_issues(db_path)\n        assert all(issue["issue_type"] != "duplicate_musicbrainz_albumid" for issue in issues)\n''')

print('release identity patch applied')
