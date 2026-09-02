from pathlib import Path

path = Path('app/converter.py')
text = path.read_text()

old = '''def preservation_blockers(path: Path) -> list[str]:
    blocks = flac_metadata_block_types(path)
    blockers = ownership_preservation_blockers(path)
    if APPLICATION in blocks:
        blockers.append("FLAC APPLICATION metadata block present; safe preservation support is not implemented yet")
    if CUESHEET in blocks:
        blockers.append("Embedded FLAC CUESHEET present; offsets require sample-rate-aware rewriting")
    return blockers


def _normalize_tags(audio: FLAC) -> dict[str, tuple[str, ...]]:
'''
new = '''def preservation_blockers(path: Path) -> list[str]:
    blocks = flac_metadata_block_types(path)
    blockers = ownership_preservation_blockers(path)
    if CUESHEET in blocks:
        blockers.append("Embedded FLAC CUESHEET present; offsets require sample-rate-aware rewriting")
    return blockers


def _read_raw_flac_metadata(path: Path) -> tuple[list[tuple[int, bytes]], int]:
    blocks: list[tuple[int, bytes]] = []
    with path.open("rb") as handle:
        if handle.read(4) != b"fLaC":
            raise ConversionError(f"Not a native FLAC file: {path}")
        last = False
        while not last:
            header = handle.read(4)
            if len(header) != 4:
                raise ConversionError(f"Truncated FLAC metadata: {path}")
            last = bool(header[0] & 0x80)
            block_type = header[0] & 0x7F
            length = int.from_bytes(header[1:4], "big")
            payload = handle.read(length)
            if len(payload) != length:
                raise ConversionError(f"Truncated FLAC metadata payload: {path}")
            blocks.append((block_type, payload))
        audio_offset = handle.tell()
    if not blocks or blocks[0][0] != STREAMINFO:
        raise ConversionError(f"FLAC STREAMINFO is missing or not first: {path}")
    return blocks, audio_offset


def _application_payloads(path: Path) -> tuple[bytes, ...]:
    blocks, _ = _read_raw_flac_metadata(path)
    return tuple(payload for block_type, payload in blocks if block_type == APPLICATION)


def _copy_application_blocks(source: Path, target: Path) -> None:
    source_apps = _application_payloads(source)
    target_blocks, audio_offset = _read_raw_flac_metadata(target)
    if not source_apps and not any(block_type == APPLICATION for block_type, _ in target_blocks):
        return

    kept = [(block_type, payload) for block_type, payload in target_blocks if block_type != APPLICATION]
    rebuilt = [kept[0], *((APPLICATION, payload) for payload in source_apps), *kept[1:]]
    rewrite = target.with_name(f".{target.name}.application-metadata.tmp")
    try:
        with target.open("rb") as src_handle, rewrite.open("wb") as out:
            out.write(b"fLaC")
            for index, (block_type, payload) in enumerate(rebuilt):
                if len(payload) > 0xFFFFFF:
                    raise ConversionError("FLAC metadata block exceeds the 24-bit length limit")
                first = block_type | (0x80 if index == len(rebuilt) - 1 else 0)
                out.write(bytes((first,)))
                out.write(len(payload).to_bytes(3, "big"))
                out.write(payload)
            src_handle.seek(audio_offset)
            shutil.copyfileobj(src_handle, out, length=4 * 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        os.replace(rewrite, target)
    finally:
        rewrite.unlink(missing_ok=True)


def _compare_application_blocks(source: Path, target: Path) -> None:
    expected = _application_payloads(source)
    actual = _application_payloads(target)
    if actual != expected:
        raise ConversionError(
            f"FLAC APPLICATION metadata blocks differ after copy: expected {len(expected)}, got {len(actual)}"
        )


def _normalize_tags(audio: FLAC) -> dict[str, tuple[str, ...]]:
'''
if old not in text:
    raise SystemExit('preservation blocker anchor not found')
text = text.replace(old, new, 1)

old = '''def copy_user_metadata(source: Path, target: Path) -> None:
    src = FLAC(source)
    dst = FLAC(target)
    dst.clear()
    if src.tags:
        for key, values in src.tags.items():
            dst[key] = list(values)
    dst.clear_pictures()
    for picture in src.pictures:
        dst.add_picture(picture)
    dst.save()


def compare_user_metadata(source: Path, target: Path) -> None:
'''
new = '''def copy_user_metadata(source: Path, target: Path) -> None:
    src = FLAC(source)
    dst = FLAC(target)
    dst.clear()
    if src.tags:
        for key, values in src.tags.items():
            dst[key] = list(values)
    dst.clear_pictures()
    for picture in src.pictures:
        dst.add_picture(picture)
    dst.save()
    _copy_application_blocks(source, target)


def compare_user_metadata(source: Path, target: Path) -> None:
'''
if old not in text:
    raise SystemExit('copy_user_metadata anchor not found')
text = text.replace(old, new, 1)

old = '''    if _picture_payloads(src) != _picture_payloads(dst):
        raise ConversionError("Embedded picture blocks differ after metadata copy")
'''
new = '''    if _picture_payloads(src) != _picture_payloads(dst):
        raise ConversionError("Embedded picture blocks differ after metadata copy")
    _compare_application_blocks(source, target)
'''
if old not in text:
    raise SystemExit('compare_user_metadata anchor not found')
text = text.replace(old, new, 1)

path.write_text(text)

# Add focused raw-block tests that do not depend on a valid audio frame stream.
test = Path('tests/test_application_metadata.py')
test.write_text('''from pathlib import Path\n\nfrom app.converter import (\n    APPLICATION,\n    PADDING,\n    STREAMINFO,\n    _application_payloads,\n    _copy_application_blocks,\n    _read_raw_flac_metadata,\n)\n\n\ndef _write_fake_flac(path: Path, blocks: list[tuple[int, bytes]], audio: bytes = b"AUDIO") -> None:\n    with path.open("wb") as handle:\n        handle.write(b"fLaC")\n        for index, (block_type, payload) in enumerate(blocks):\n            first = block_type | (0x80 if index == len(blocks) - 1 else 0)\n            handle.write(bytes((first,)))\n            handle.write(len(payload).to_bytes(3, "big"))\n            handle.write(payload)\n        handle.write(audio)\n\n\ndef test_application_blocks_copy_byte_for_byte(tmp_path: Path) -> None:\n    source = tmp_path / "source.flac"\n    target = tmp_path / "target.flac"\n    streaminfo = bytes(range(34))\n    app1 = b"abcd" + bytes(range(32))\n    app2 = b"wxyz" + b"opaque application payload"\n    _write_fake_flac(source, [(STREAMINFO, streaminfo), (APPLICATION, app1), (APPLICATION, app2)])\n    _write_fake_flac(target, [(STREAMINFO, streaminfo), (APPLICATION, b"old!payload"), (PADDING, b"\\0" * 16)], audio=b"TARGET-AUDIO")\n\n    _copy_application_blocks(source, target)\n\n    assert _application_payloads(target) == (app1, app2)\n    blocks, audio_offset = _read_raw_flac_metadata(target)\n    assert blocks[0] == (STREAMINFO, streaminfo)\n    assert [block_type for block_type, _ in blocks] == [STREAMINFO, APPLICATION, APPLICATION, PADDING]\n    assert target.read_bytes()[audio_offset:] == b"TARGET-AUDIO"\n\n\ndef test_no_application_blocks_removes_target_application(tmp_path: Path) -> None:\n    source = tmp_path / "source.flac"\n    target = tmp_path / "target.flac"\n    streaminfo = b"S" * 34\n    _write_fake_flac(source, [(STREAMINFO, streaminfo), (PADDING, b"\\0" * 8)])\n    _write_fake_flac(target, [(STREAMINFO, streaminfo), (APPLICATION, b"junkpayload"), (PADDING, b"\\0" * 8)])\n\n    _copy_application_blocks(source, target)\n\n    assert _application_payloads(target) == ()\n''')

assert 'safe preservation support is not implemented yet' not in text
assert '_copy_application_blocks(source, target)' in text
assert '_compare_application_blocks(source, target)' in text
print('APPLICATION metadata preservation patched successfully')
