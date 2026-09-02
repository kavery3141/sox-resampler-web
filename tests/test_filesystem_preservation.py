from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.converter import FilesystemMetadata, ConversionError, _apply_filesystem_metadata, ownership_preservation_blockers_for_ids


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


class FilesystemModePreservationTests(unittest.TestCase):
    def _metadata(self, mode: int) -> FilesystemMetadata:
        return FilesystemMetadata(
            mode=mode,
            uid=os.geteuid(),
            gid=os.getegid(),
            atime_ns=1_700_000_000_000_000_000,
            mtime_ns=1_700_000_000_000_000_000,
            xattrs=(),
        )

    def test_matching_inherited_mode_does_not_call_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'out.flac'
            path.write_bytes(b'x')
            os.chmod(path, 0o770)
            expected = self._metadata(0o770)
            with mock.patch('app.converter.os.chmod', side_effect=PermissionError('ACL restricted')) as chmod:
                _apply_filesystem_metadata(path, expected)
            chmod.assert_not_called()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o770)

    def test_different_mode_still_fails_closed_when_chmod_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'out.flac'
            path.write_bytes(b'x')
            os.chmod(path, 0o660)
            expected = self._metadata(0o770)
            with mock.patch('app.converter.os.chmod', side_effect=PermissionError('ACL restricted')):
                with self.assertRaisesRegex(ConversionError, 'generated output has mode 660'):
                    _apply_filesystem_metadata(path, expected)


if __name__ == "__main__":
    unittest.main()
