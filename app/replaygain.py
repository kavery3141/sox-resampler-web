from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mutagen.flac import FLAC

from .converter import (
    ConversionError,
    _apply_filesystem_metadata,
    _picture_payloads,
    _rename_exchange,
    _sha256,
    filesystem_metadata,
)
from .transactions import ReplacementJournal, identity

RSGAIN_BIN = os.getenv("RSGAIN_BIN", "rsgain")
REFERENCE_LOUDNESS = "-18.00 LUFS"
TABLE_HEADER = (
    "filename",
    "loudness",
    "gain",
    "peak",
    "peak_db",
    "peak_type",
    "clipping_adjustment",
)
RG_KEYS = {
    "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
    "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
    "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
    "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
    "replaygain_reference_loudness": "REPLAYGAIN_REFERENCE_LOUDNESS",
}


class ReplayGainError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayGainValues:
    track_gain: str
    track_peak: str
    album_gain: str
    album_peak: str
    reference_loudness: str = REFERENCE_LOUDNESS


def _parse_row(line: str) -> dict[str, str]:
    columns = line.split("\t")
    if len(columns) != len(TABLE_HEADER):
        raise ReplayGainError(f"Unexpected rsgain output row: {line!r}")
    return dict(zip(TABLE_HEADER, columns, strict=True))


def scan_album(paths: list[Path], rsgain_bin: str = RSGAIN_BIN) -> dict[Path, ReplayGainValues]:
    if not paths:
        return {}
    command = [
        rsgain_bin,
        "custom",
        "-O",
        "-s",
        "s",
        "-a",
        "-t",
        "-l",
        "-18",
        "-c",
        "a",
        "-m",
        "0",
        *[str(path) for path in paths],
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ReplayGainError(f"Unable to start rsgain: {exc}") from exc
    if completed.returncode != 0:
        output = completed.stdout.strip()
        raise ReplayGainError(
            f"rsgain returned exit code {completed.returncode}: {output or 'no diagnostic output'}"
        )
    lines = completed.stdout.splitlines()
    expected = 1 + len(paths) + 1
    if len(lines) != expected:
        raise ReplayGainError(f"Unexpected rsgain output: expected {expected} rows, got {len(lines)}")
    track_rows = [_parse_row(line) for line in lines[1:-1]]
    album_row = _parse_row(lines[-1])
    return {
        path: ReplayGainValues(
            track_gain=f"{track['gain']} dB",
            track_peak=track["peak"],
            album_gain=f"{album_row['gain']} dB",
            album_peak=album_row["peak"],
        )
        for path, track in zip(paths, track_rows, strict=True)
    }


def _tags_without_managed_replaygain(audio: FLAC) -> dict[str, tuple[str, ...]]:
    if not audio.tags:
        return {}
    return {
        str(key).lower(): tuple(str(value) for value in values)
        for key, values in audio.tags.items()
        if str(key).lower() not in RG_KEYS
    }


def _actual_tag_names(audio: FLAC) -> dict[str, str]:
    if not audio.tags:
        return {}
    return {str(key).lower(): str(key) for key in audio.tags.keys()}


def _write_values(path: Path, values: ReplayGainValues) -> None:
    audio = FLAC(path)
    names = _actual_tag_names(audio)
    replacements = {
        "replaygain_track_gain": values.track_gain,
        "replaygain_track_peak": values.track_peak,
        "replaygain_album_gain": values.album_gain,
        "replaygain_album_peak": values.album_peak,
        "replaygain_reference_loudness": values.reference_loudness,
    }
    for normalized, value in replacements.items():
        actual = names.get(normalized, RG_KEYS[normalized])
        audio[actual] = [value]
    audio.save()


def _verify_metadata_only(source: Path, target: Path, values: ReplayGainValues) -> None:
    before = FLAC(source)
    after = FLAC(target)
    if _tags_without_managed_replaygain(before) != _tags_without_managed_replaygain(after):
        raise ReplayGainError("Non-ReplayGain Vorbis comments changed during ReplayGain update")
    if _picture_payloads(before) != _picture_payloads(after):
        raise ReplayGainError("Embedded artwork changed during ReplayGain update")
    expected = {
        "replaygain_track_gain": values.track_gain,
        "replaygain_track_peak": values.track_peak,
        "replaygain_album_gain": values.album_gain,
        "replaygain_album_peak": values.album_peak,
        "replaygain_reference_loudness": values.reference_loudness,
    }
    normalized = {str(k).lower(): tuple(str(v) for v in vals) for k, vals in (after.tags or {}).items()}
    for key, value in expected.items():
        if normalized.get(key) != (value,):
            raise ReplayGainError(f"ReplayGain verification failed for {key}")
    for attr in ("sample_rate", "bits_per_sample", "channels", "total_samples"):
        if getattr(before.info, attr, None) != getattr(after.info, attr, None):
            raise ReplayGainError(f"Audio stream property changed during ReplayGain update: {attr}")


def apply_replaygain_transaction(
    source: Path,
    values: ReplayGainValues,
    data_root: Path,
) -> str:
    source = source.resolve()
    temp = source.with_name(f".{source.name}.sox-resampler.rg.tmp.flac")
    if temp.exists():
        raise ReplayGainError(f"ReplayGain temp already exists: {temp}")
    fs_meta = filesystem_metadata(source)
    original_identity = identity(source)
    journal = ReplacementJournal(data_root / "transactions", source)
    exchanged = False

    def rollback_after_exchange(reason: str) -> None:
        nonlocal exchanged
        if not exchanged:
            return
        _rename_exchange(source, temp)
        exchanged = False
        if identity(source) != original_identity:
            raise ReplayGainError(
                f"{reason}; rollback did not restore the original source identity; recovery journal retained"
            )
        try:
            temp.unlink()
        except OSError as exc:
            raise ReplayGainError(
                f"{reason}; original restored but generated ReplayGain temp could not be removed: {exc}"
            ) from exc
        journal.clear()

    try:
        shutil.copyfile(source, temp)
        _write_values(temp, values)
        _verify_metadata_only(source, temp, values)
        _apply_filesystem_metadata(temp, fs_meta)
        try:
            subprocess.run(["flac", "-t", "--silent", str(temp)], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ReplayGainError("FLAC verification failed after ReplayGain update") from exc
        new_sha = _sha256(temp)
        journal.prepare(source, temp, original_identity, new_sha)
        _rename_exchange(source, temp)
        exchanged = True
        journal.mark_exchanged()
        if _sha256(source) != new_sha:
            rollback_after_exchange("ReplayGain replacement checksum verification failed")
            raise ReplayGainError("ReplayGain replacement checksum verification failed; rolled back")
        try:
            _verify_metadata_only(temp, source, values)
        except Exception as exc:
            rollback_after_exchange("ReplayGain post-exchange metadata verification failed")
            raise ReplayGainError(
                f"ReplayGain post-exchange metadata verification failed; rolled back: {exc}"
            ) from exc
        journal.mark_verified()
        temp.unlink()
        exchanged = False
        journal.clear()
        return new_sha
    except (ReplayGainError, ConversionError):
        raise
    except Exception as exc:
        raise ReplayGainError(str(exc)) from exc
    finally:
        if temp.exists() and not journal.path.exists():
            try:
                temp.unlink()
            except OSError:
                pass
