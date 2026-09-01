from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import db
from app.profile_store import (
    create_custom_profile,
    delete_custom_profile,
    duplicate_profile,
    export_profile,
    get_profile,
    import_profile,
    list_all_profiles,
    preview_import,
    update_custom_profile,
)
from app.profiles import FOOBAR_ULTRA_37, apply_profile_override


class ProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_builtin_presets_are_read_only_but_duplicable(self) -> None:
        builtin = get_profile(self.db_path, "foobar-ultra-37-48k")
        self.assertTrue(builtin.read_only)
        duplicate = duplicate_profile(self.db_path, builtin.id)
        self.assertFalse(duplicate.read_only)
        self.assertTrue(duplicate.id.startswith("custom-"))
        with self.assertRaises(ValueError):
            update_custom_profile(self.db_path, builtin.id, {"target_rate": 44100})
        with self.assertRaises(ValueError):
            delete_custom_profile(self.db_path, builtin.id)

    def test_custom_preset_round_trip_update_and_delete(self) -> None:
        payload = FOOBAR_ULTRA_37.to_dict()
        payload.update({"name": "My 48k Preset", "description": "Test", "notes": "Keep this"})
        profile = create_custom_profile(self.db_path, payload)
        loaded = get_profile(self.db_path, profile.id)
        self.assertEqual(loaded.name, "My 48k Preset")
        self.assertEqual(loaded.notes, "Keep this")
        updated = update_custom_profile(
            self.db_path,
            profile.id,
            {"target_rate": 44100, "headroom_db": -1.5, "dither": "shibata"},
        )
        self.assertEqual(updated.target_rate, 44100)
        self.assertEqual(updated.headroom_db, -1.5)
        self.assertEqual(updated.dither, "shibata")
        delete_custom_profile(self.db_path, profile.id)
        with self.assertRaises(ValueError):
            get_profile(self.db_path, profile.id)

    def test_batch_override_does_not_mutate_base_preset(self) -> None:
        changed = apply_profile_override(
            FOOBAR_ULTRA_37,
            {"target_rate": 44100, "headroom_db": -2.0, "flac_compression": 6},
        )
        self.assertEqual(changed.target_rate, 44100)
        self.assertEqual(changed.headroom_db, -2.0)
        self.assertEqual(FOOBAR_ULTRA_37.target_rate, 48000)
        self.assertEqual(FOOBAR_ULTRA_37.headroom_db, 0.0)
        with self.assertRaises(ValueError):
            apply_profile_override(FOOBAR_ULTRA_37, {"name": "Not allowed"})

    def test_export_import_schema_is_validated(self) -> None:
        document = export_profile(FOOBAR_ULTRA_37)
        preview = preview_import(document)
        self.assertEqual(preview.target_rate, 48000)
        imported = import_profile(self.db_path, document, "Imported Ultra")
        self.assertEqual(imported.name, "Imported Ultra")
        self.assertFalse(imported.read_only)
        bad = dict(document)
        bad["schema_version"] = 999
        with self.assertRaises(ValueError):
            preview_import(bad)

    def test_list_contains_builtins_and_customs(self) -> None:
        duplicate_profile(self.db_path, "factory-defaults", "Factory Variant")
        profiles = list_all_profiles(self.db_path)
        names = {profile.name for profile in profiles}
        self.assertIn("Factory Defaults", names)
        self.assertIn("Foobar Ultra 37 - 48 kHz", names)
        self.assertIn("Factory Variant", names)


if __name__ == "__main__":
    unittest.main()
