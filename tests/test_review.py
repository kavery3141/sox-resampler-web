from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.profiles import FOOBAR_ULTRA_37
from app.review import build_batch_review


class BatchReviewTest(unittest.TestCase):
    def test_ultra_profile_readiness_uses_current_profile_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.db"
            db.init(db_path)
            review = build_batch_review(
                db_path=db_path,
                music_root=root,
                album_keys=[],
                rates=[96000, 192000],
                above=None,
                profile=FOOBAR_ULTRA_37,
                workers=1,
                reserve_bytes=10 * 1024**3,
            )
            self.assertTrue(review["profile"]["implementation_ready"])
            self.assertFalse(review["can_start"])
            self.assertEqual(review["albums"], [])


if __name__ == "__main__":
    unittest.main()
