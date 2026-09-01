from __future__ import annotations

import unittest

from app.converter import ownership_preservation_blockers_for_ids


class FilesystemOwnershipPreflightTests(unittest.TestCase):
    def check(self, **overrides):
        values = {
            "source_uid": 568,
            "source_gid": 568,
            "parent_gid": 568,
            "parent_setgid": False,
            "runtime_uid": 568,
            "runtime_gid": 568,
            "runtime_groups": {568},
            "can_chown": False,
        }
        values.update(overrides)
        return ownership_preservation_blockers_for_ids(**values)

    def test_matching_runtime_identity_is_preservable(self) -> None:
        self.assertEqual(self.check(), [])

    def test_different_owner_is_blocking_without_cap_chown(self) -> None:
        blockers = self.check(source_uid=1000)
        self.assertEqual(len(blockers), 1)
        self.assertIn("Source owner UID 1000 differs from runtime UID 568", blockers[0])

    def test_supplementary_group_can_be_preserved(self) -> None:
        self.assertEqual(
            self.check(source_gid=100, runtime_groups={100, 568}),
            [],
        )

    def test_setgid_parent_can_supply_source_group(self) -> None:
        self.assertEqual(
            self.check(source_gid=100, parent_gid=100, parent_setgid=True),
            [],
        )

    def test_unavailable_source_group_is_blocking(self) -> None:
        blockers = self.check(source_gid=100, runtime_groups={568})
        self.assertEqual(len(blockers), 1)
        self.assertIn("Source group GID 100 cannot be assigned", blockers[0])

    def test_cap_chown_allows_different_owner_and_group(self) -> None:
        self.assertEqual(
            self.check(source_uid=1000, source_gid=100, can_chown=True),
            [],
        )

    def test_root_runtime_can_preserve_ownership(self) -> None:
        self.assertEqual(
            self.check(source_uid=1000, source_gid=100, runtime_uid=0, runtime_gid=0),
            [],
        )


if __name__ == "__main__":
    unittest.main()
