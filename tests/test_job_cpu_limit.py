from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db
from app.converter import ConversionResult
from app.jobs import ConversionJobManager
from app.profiles import FACTORY_DEFAULTS


class JobCpuLimitWiringTests(unittest.TestCase):
    def test_job_reads_cpu_limit_when_each_file_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            music.mkdir()
            db_path = root / "data" / "test.db"
            db.init(db_path)
            manager = ConversionJobManager(db_path, music, "America/Indiana/Indianapolis")
            source = music / "track.flac"
            source.write_bytes(b"synthetic source")
            with db.session(db_path) as conn:
                job_cur = conn.execute(
                    """
                    INSERT INTO conversion_jobs(
                      created_at,status,profile_id,profile_json,workers,source_filter_json,album_order_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (manager._now(), "running", FACTORY_DEFAULTS.id, None, 1, "{}", "[]"),
                )
                job_id = int(job_cur.lastrowid)
                file_cur = conn.execute(
                    """
                    INSERT INTO conversion_files(
                      job_id,album_index,file_index,albumartist,album,path,source_bytes,status
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (job_id, 0, 0, "Artist", "Album", str(source), source.stat().st_size, "pending"),
                )
                file_id = int(file_cur.lastrowid)

            synthetic = ConversionResult(
                source=str(source),
                status="failed",
                command=["synthetic"],
                error="synthetic failure",
            )
            with patch("app.jobs.configured_cpu_limit", return_value=55), patch(
                "app.jobs.convert_file", return_value=synthetic
            ) as convert:
                payload = manager._run_file(
                    job_id, file_id, str(source), FACTORY_DEFAULTS, source.stat().st_size
                )

            convert.assert_called_once_with(
                source, FACTORY_DEFAULTS, cpu_limit_percent=55, source_pre_hash=False
            )
            self.assertEqual(payload["cpu_limit_percent"], 55)
            self.assertFalse(payload["source_pre_hash"])
            self.assertEqual(payload["status"], "failed")

    def test_job_passes_enabled_source_pre_hash_to_converter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            music = root / "music"
            music.mkdir()
            db_path = root / "data" / "test.db"
            db.init(db_path)
            manager = ConversionJobManager(db_path, music, "America/Indiana/Indianapolis")
            source = music / "track.flac"
            source.write_bytes(b"synthetic source")
            with db.session(db_path) as conn:
                job_cur = conn.execute(
                    """
                    INSERT INTO conversion_jobs(
                      created_at,status,profile_id,profile_json,workers,source_filter_json,operational_json,album_order_json
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (manager._now(), "running", FACTORY_DEFAULTS.id, None, 1, "{}", '{"source_pre_hash":true}', "[]"),
                )
                job_id = int(job_cur.lastrowid)
                file_cur = conn.execute(
                    """
                    INSERT INTO conversion_files(
                      job_id,album_index,file_index,albumartist,album,path,source_bytes,status
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (job_id, 0, 0, "Artist", "Album", str(source), source.stat().st_size, "pending"),
                )
                file_id = int(file_cur.lastrowid)

            synthetic = ConversionResult(
                source=str(source),
                status="failed",
                command=["synthetic"],
                source_sha256="abc123",
                error="synthetic failure",
            )
            with patch("app.jobs.configured_cpu_limit", return_value=None), patch(
                "app.jobs.convert_file", return_value=synthetic
            ) as convert:
                payload = manager._run_file(
                    job_id, file_id, str(source), FACTORY_DEFAULTS, source.stat().st_size, True
                )

            convert.assert_called_once_with(
                source, FACTORY_DEFAULTS, cpu_limit_percent=None, source_pre_hash=True
            )
            self.assertTrue(payload["source_pre_hash"])
            with db.session(db_path) as conn:
                stored = conn.execute("SELECT source_sha256 FROM conversion_files WHERE id=?", (file_id,)).fetchone()
            self.assertEqual(stored["source_sha256"], "abc123")


if __name__ == "__main__":
    unittest.main()
