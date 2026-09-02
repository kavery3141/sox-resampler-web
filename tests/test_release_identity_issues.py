import tempfile
from pathlib import Path

from app import db
from app.issues import build_metadata_issues


def _insert(db_path: Path, *, folder: str, album: str, mbid: str, title: str) -> None:
    path = f"{folder}/{title}.flac"
    with db.session(db_path) as conn:
        conn.execute(
            """INSERT INTO tracks(path,rel_path,folder,filename,size_bytes,mtime_ns,sample_rate,bits_per_sample,channels,duration,albumartist,album,releasetype,musicbrainz_albumid,artist,title,tracknumber,discnumber,replaygain_track_gain,replaygain_track_peak,replaygain_album_gain,replaygain_album_peak,picture_count,first_seen,last_seen,tag_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (path, path, folder, f"{title}.flac", 1000, 1, 96000, 24, 2, 1.0, "Weezer", album, "album", mbid, "Weezer", title, "1", "1", "-1 dB", "0.5", "-1 dB", "0.5", 0, "x", "x", "{}"),
        )


def test_same_title_different_mbids_not_reported_as_cross_folder_conflict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "library.db"
        db.init(db_path)
        _insert(db_path, folder="/music/Weezer/Weezer (2001)", album="Weezer", mbid="green", title="One")
        _insert(db_path, folder="/music/Weezer/Weezer (2019)", album="Weezer", mbid="teal", title="Two")
        issues = build_metadata_issues(db_path)
        types = {issue["issue_type"] for issue in issues}
        assert "inconsistent_musicbrainz_albumid_across_folders" not in types
        assert "duplicate_musicbrainz_albumid" not in types


def test_multidisc_shared_mbid_not_reported_as_duplicate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "library.db"
        db.init(db_path)
        for index, disc in enumerate(("Disc 01", "Disc 02", "Disc 03"), start=1):
            _insert(db_path, folder=f"/music/Artist/Album/{disc}", album="Album", mbid="same-release", title=f"Track {index}")
        issues = build_metadata_issues(db_path)
        assert all(issue["issue_type"] != "duplicate_musicbrainz_albumid" for issue in issues)
