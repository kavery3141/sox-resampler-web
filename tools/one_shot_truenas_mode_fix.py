from pathlib import Path

converter = Path('app/converter.py')
s = converter.read_text()
old = '''def _apply_filesystem_metadata(target: Path, expected: FilesystemMetadata) -> None:\n    try:\n        os.chmod(target, expected.mode, follow_symlinks=False)\n    except OSError as exc:\n        raise ConversionError(f"Cannot preserve mode {expected.mode:o}") from exc\n\n    target_st = target.stat(follow_symlinks=False)\n'''
new = '''def _apply_filesystem_metadata(target: Path, expected: FilesystemMetadata) -> None:\n    # TrueNAS/ZFS datasets can use inheritable NFSv4 ACLs with aclmode=restricted. In that\n    # configuration chmod may be forbidden even when the newly-created file already has the\n    # exact effective mode we need. Avoid rewriting mode bits unless they actually differ.\n    target_st = target.stat(follow_symlinks=False)\n    actual_mode = stat.S_IMODE(target_st.st_mode)\n    if actual_mode != expected.mode:\n        try:\n            os.chmod(target, expected.mode, follow_symlinks=False)\n        except OSError as exc:\n            raise ConversionError(\n                f"Cannot preserve mode {expected.mode:o}; generated output has mode {actual_mode:o}"\n            ) from exc\n        target_st = target.stat(follow_symlinks=False)\n\n'''
if s.count(old) != 1:
    raise SystemExit(f'converter replacement count={s.count(old)}')
s = s.replace(old, new, 1)
converter.write_text(s)

test = Path('tests/test_filesystem_preservation.py')
t = test.read_text()
t = t.replace('import unittest\n\nfrom app.converter import ownership_preservation_blockers_for_ids\n', 'import os\nimport stat\nimport tempfile\nimport unittest\nfrom pathlib import Path\nfrom unittest import mock\n\nfrom app.converter import FilesystemMetadata, ConversionError, _apply_filesystem_metadata, ownership_preservation_blockers_for_ids\n', 1)
insert = '''\n\nclass FilesystemModePreservationTests(unittest.TestCase):\n    def _metadata(self, mode: int) -> FilesystemMetadata:\n        return FilesystemMetadata(\n            mode=mode,\n            uid=os.geteuid(),\n            gid=os.getegid(),\n            atime_ns=1_700_000_000_000_000_000,\n            mtime_ns=1_700_000_000_000_000_000,\n            xattrs=(),\n        )\n\n    def test_matching_inherited_mode_does_not_call_chmod(self) -> None:\n        with tempfile.TemporaryDirectory() as td:\n            path = Path(td) / 'out.flac'\n            path.write_bytes(b'x')\n            os.chmod(path, 0o770)\n            expected = self._metadata(0o770)\n            with mock.patch('app.converter.os.chmod', side_effect=PermissionError('ACL restricted')) as chmod:\n                _apply_filesystem_metadata(path, expected)\n            chmod.assert_not_called()\n            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o770)\n\n    def test_different_mode_still_fails_closed_when_chmod_is_forbidden(self) -> None:\n        with tempfile.TemporaryDirectory() as td:\n            path = Path(td) / 'out.flac'\n            path.write_bytes(b'x')\n            os.chmod(path, 0o660)\n            expected = self._metadata(0o770)\n            with mock.patch('app.converter.os.chmod', side_effect=PermissionError('ACL restricted')):\n                with self.assertRaisesRegex(ConversionError, 'generated output has mode 660'):\n                    _apply_filesystem_metadata(path, expected)\n'''
needle = '\n\nif __name__ == "__main__":\n'
if t.count(needle) != 1:
    raise SystemExit('test insertion point not unique')
t = t.replace(needle, insert + needle, 1)
test.write_text(t)
