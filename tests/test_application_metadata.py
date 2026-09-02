from pathlib import Path

from app.converter import (
    APPLICATION,
    PADDING,
    STREAMINFO,
    _application_payloads,
    _copy_application_blocks,
    _read_raw_flac_metadata,
)


def _write_fake_flac(path: Path, blocks: list[tuple[int, bytes]], audio: bytes = b"AUDIO") -> None:
    with path.open("wb") as handle:
        handle.write(b"fLaC")
        for index, (block_type, payload) in enumerate(blocks):
            first = block_type | (0x80 if index == len(blocks) - 1 else 0)
            handle.write(bytes((first,)))
            handle.write(len(payload).to_bytes(3, "big"))
            handle.write(payload)
        handle.write(audio)


def test_application_blocks_copy_byte_for_byte(tmp_path: Path) -> None:
    source = tmp_path / "source.flac"
    target = tmp_path / "target.flac"
    streaminfo = bytes(range(34))
    app1 = b"abcd" + bytes(range(32))
    app2 = b"wxyz" + b"opaque application payload"
    _write_fake_flac(source, [(STREAMINFO, streaminfo), (APPLICATION, app1), (APPLICATION, app2)])
    _write_fake_flac(target, [(STREAMINFO, streaminfo), (APPLICATION, b"old!payload"), (PADDING, b"\0" * 16)], audio=b"TARGET-AUDIO")

    _copy_application_blocks(source, target)

    assert _application_payloads(target) == (app1, app2)
    blocks, audio_offset = _read_raw_flac_metadata(target)
    assert blocks[0] == (STREAMINFO, streaminfo)
    assert [block_type for block_type, _ in blocks] == [STREAMINFO, APPLICATION, APPLICATION, PADDING]
    assert target.read_bytes()[audio_offset:] == b"TARGET-AUDIO"


def test_no_application_blocks_removes_target_application(tmp_path: Path) -> None:
    source = tmp_path / "source.flac"
    target = tmp_path / "target.flac"
    streaminfo = b"S" * 34
    _write_fake_flac(source, [(STREAMINFO, streaminfo), (PADDING, b"\0" * 8)])
    _write_fake_flac(target, [(STREAMINFO, streaminfo), (APPLICATION, b"junkpayload"), (PADDING, b"\0" * 8)])

    _copy_application_blocks(source, target)

    assert _application_payloads(target) == ()
