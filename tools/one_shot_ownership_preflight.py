from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_converter() -> None:
    replace_once(
        "app/converter.py",
        "RENAME_EXCHANGE = 2\nSOX_ULTRA_BIN = os.getenv(\"SOX_ULTRA_BIN\", \"/opt/sox-ultra/bin/sox\")\n",
        "RENAME_EXCHANGE = 2\nCAP_CHOWN = 0\nSOX_ULTRA_BIN = os.getenv(\"SOX_ULTRA_BIN\", \"/opt/sox-ultra/bin/sox\")\n",
        "converter CAP_CHOWN constant",
    )

    replace_once(
        "app/converter.py",
        '''def preservation_blockers(path: Path) -> list[str]:
    blocks = flac_metadata_block_types(path)
    blockers: list[str] = []
    if APPLICATION in blocks:
        blockers.append("FLAC APPLICATION metadata block present; safe preservation support is not implemented yet")
    if CUESHEET in blocks:
        blockers.append("Embedded FLAC CUESHEET present; offsets require sample-rate-aware rewriting")
    return blockers
''',
        '''def _effective_linux_capabilities() -> int:
    """Return Linux CapEff as a bitmask when available; fail closed to no capabilities."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("CapEff:"):
                return int(line.split(":", 1)[1].strip(), 16)
    except (OSError, ValueError):
        pass
    return 0


def ownership_preservation_blockers_for_ids(
    *,
    source_uid: int,
    source_gid: int,
    parent_gid: int,
    parent_setgid: bool,
    runtime_uid: int,
    runtime_gid: int,
    runtime_groups: set[int],
    can_chown: bool,
) -> list[str]:
    """Explain when a newly generated file cannot retain source ownership.

    SoX creates a new inode owned by the runtime user. A setgid parent directory can supply the
    source group without a later chown. Otherwise an unprivileged owner may only select one of its
    own groups. The check is intentionally conservative because replacement must not silently alter
    NAS ownership.
    """
    if runtime_uid == 0 or can_chown:
        return []

    blockers: list[str] = []
    if source_uid != runtime_uid:
        blockers.append(
            f"Source owner UID {source_uid} differs from runtime UID {runtime_uid}; "
            "exact ownership cannot be preserved by the unprivileged container"
        )

    created_gid = parent_gid if parent_setgid else runtime_gid
    allowed_groups = {runtime_gid, *runtime_groups}
    if source_gid != created_gid and source_gid not in allowed_groups:
        blockers.append(
            f"Source group GID {source_gid} cannot be assigned by runtime UID {runtime_uid}; "
            f"runtime groups are {','.join(str(value) for value in sorted(allowed_groups)) or '<none>'}"
        )
    return blockers


def ownership_preservation_blockers(path: Path) -> list[str]:
    st = path.stat(follow_symlinks=False)
    parent_st = path.parent.stat(follow_symlinks=False)
    runtime_uid = os.geteuid()
    runtime_gid = os.getegid()
    runtime_groups = set(os.getgroups())
    can_chown = bool(_effective_linux_capabilities() & (1 << CAP_CHOWN))
    return ownership_preservation_blockers_for_ids(
        source_uid=int(st.st_uid),
        source_gid=int(st.st_gid),
        parent_gid=int(parent_st.st_gid),
        parent_setgid=bool(parent_st.st_mode & stat.S_ISGID),
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
        runtime_groups=runtime_groups,
        can_chown=can_chown,
    )


def preservation_blockers(path: Path) -> list[str]:
    blocks = flac_metadata_block_types(path)
    blockers = ownership_preservation_blockers(path)
    if APPLICATION in blocks:
        blockers.append("FLAC APPLICATION metadata block present; safe preservation support is not implemented yet")
    if CUESHEET in blocks:
        blockers.append("Embedded FLAC CUESHEET present; offsets require sample-rate-aware rewriting")
    return blockers
''',
        "converter ownership preflight",
    )


def patch_admin() -> None:
    replace_once(
        "app/admin.py",
        '''            "music_root": str(music_root),
            "data_root": str(data_root),
            "free_bytes": usage.free if usage else None,
            "timezone": timezone,
''',
        '''            "music_root": str(music_root),
            "data_root": str(data_root),
            "free_bytes": usage.free if usage else None,
            "timezone": timezone,
            "runtime_identity": {
                "uid": os.geteuid(),
                "gid": os.getegid(),
                "supplementary_gids": sorted(set(os.getgroups())),
            },
''',
        "maintenance runtime identity",
    )


def patch_readme() -> None:
    replace_once(
        "README.md",
        "The two intended writable locations are the explicit `/music` and `/data` dataset mounts. CI validates the supplied Compose definition before building the container.\n",
        "The two intended writable locations are the explicit `/music` and `/data` dataset mounts. CI validates the supplied Compose definition before building the container. Because replacement creates a new verified inode before the atomic exchange, selected source files whose UID/GID cannot be reproduced by the unprivileged runtime are blocked during preflight rather than being converted and silently changing ownership. Maintenance reports the runtime UID/GID to make dataset-permission diagnosis straightforward.\n",
        "README ownership preflight note",
    )


def write_tests() -> None:
    path = Path("tests/test_filesystem_preservation.py")
    if path.exists():
        raise SystemExit("tests/test_filesystem_preservation.py already exists")
    path.write_text(
        '''from __future__ import annotations

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
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_converter()
    patch_admin()
    patch_readme()
    write_tests()


if __name__ == "__main__":
    main()
