from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen.flac import FLAC

from .profiles import ResampleProfile


class ConversionError(RuntimeError):
    pass


class ProfileUnavailable(ConversionError):
    pass


@dataclass(frozen=True)
class SourceIdentity:
    inode: int
    device: int
    size: int
    mtime_ns: int


@dataclass
class ConversionResult:
    source: str
    status: str
    command: list[str]
    temp_sha256: str | None = None
    final_sha256: str | None = None
    source_rate: int | None = None
    target_rate: int | None = None
    source_bits: int | None = None
    target_bits: int | None = None
    error: str | None = None


# FLAC metadata block types that are audio-layout dependent and cannot simply be copied.
STREAMINFO = 0
PADDING = 1
APPLICATION = 2
SEEKTABLE = 3
VORBIS_COMMENT = 4
CUESHEET = 5
PICTURE = 6

AT_FDCWD = -100
RENAME_EXCHANGE = 2


def source_identity(path: Path) -> SourceIdentity:
    st = path.stat()
    return SourceIdentity(st.st_ino, st.st_dev, st.st_size, st.st_mtime_ns)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def flac_metadata_block_types(path: Path) -> list[int]:
    """Return FLAC metadata block type IDs without decoding audio."""
    result: list[int] = []
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
            result.append(block_type)
            handle.seek(length, os.SEEK_CUR)
    return result


def preservation_blockers(path: Path) -> list[str]:
    blocks = flac_metadata_block_types(path)
    blockers: list[str] = []
    if APPLICATION in blocks:
        blockers.append("FLAC APPLICATION metadata block present; safe preservation support is not implemented yet")
    if CUESHEET in blocks:
        blockers.append("Embedded FLAC CUESHEET present; offsets require sample-rate-aware rewriting")
    return blockers


def _normalize_tags(audio: FLAC) -> dict[str, tuple[str, ...]]:
    if not audio.tags:
        return {}
    return {str(k).lower(): tuple(str(v) for v in values) for k, values in audio.tags.items()}


def _picture_payloads(audio: FLAC) -> list[bytes]:
    return [picture.write() for picture in audio.pictures]


def copy_user_metadata(source: Path, target: Path) -> None:
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
    src = FLAC(source)
    dst = FLAC(target)
    if _normalize_tags(src) != _normalize_tags(dst):
        raise ConversionError("Vorbis comments/tags differ after metadata copy")
    if _picture_payloads(src) != _picture_payloads(dst):
        raise ConversionError("Embedded picture blocks differ after metadata copy")


def _copy_filesystem_metadata(source: Path, target: Path) -> None:
    st = source.stat(follow_symlinks=False)
    os.chmod(target, stat.S_IMODE(st.st_mode), follow_symlinks=False)

    target_st = target.stat(follow_symlinks=False)
    if (target_st.st_uid, target_st.st_gid) != (st.st_uid, st.st_gid):
        try:
            os.chown(target, st.st_uid, st.st_gid, follow_symlinks=False)
        except PermissionError as exc:
            raise ConversionError(
                f"Cannot preserve owner/group {st.st_uid}:{st.st_gid}; refusing replacement"
            ) from exc

    try:
        names = os.listxattr(source, follow_symlinks=False)
    except OSError:
        names = []
    for name in names:
        try:
            value = os.getxattr(source, name, follow_symlinks=False)
            os.setxattr(target, name, value, follow_symlinks=False)
        except OSError as exc:
            raise ConversionError(f"Cannot preserve extended attribute {name!r}") from exc

    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns), follow_symlinks=False)


def _rename_exchange(path_a: Path, path_b: Path) -> None:
    """Atomically exchange two same-filesystem paths, retaining rollback capability."""
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise ConversionError("renameat2(RENAME_EXCHANGE) unavailable; safe no-backup replacement disabled")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    rc = fn(AT_FDCWD, os.fsencode(path_a), AT_FDCWD, os.fsencode(path_b), RENAME_EXCHANGE)
    if rc != 0:
        err = ctypes.get_errno()
        raise ConversionError(f"Atomic exchange failed: {os.strerror(err)}")


def _quality_args(profile: ResampleProfile) -> list[str]:
    if profile.quality == "ultra-37":
        if not profile.exact_foobar_match:
            raise ProfileUnavailable(
                "Foobar Ultra 37 exact backend is not integrated yet; refusing to substitute stock SoX -v"
            )
        raise ProfileUnavailable("Ultra 37 backend declaration is incomplete")
    if profile.quality == "very-high":
        return ["-v"]
    if profile.quality == "high":
        return ["-h"]
    if profile.quality == "medium":
        return ["-m"]
    if profile.quality == "quick":
        return ["-q"]
    raise ConversionError(f"Unsupported quality mode: {profile.quality}")


def build_sox_command(source: Path, temp: Path, profile: ResampleProfile, source_bits: int) -> list[str]:
    target_bits = source_bits if profile.bit_depth == "preserve" else int(profile.bit_depth)
    if not 8 <= target_bits <= 32:
        raise ConversionError("Invalid target bit depth")
    if not 8000 <= profile.target_rate <= 768000:
        raise ConversionError("Invalid target sample rate")
    if not 0 < profile.passband_percent <= 99.7:
        raise ConversionError("Passband must be between 0 and 99.7 percent")
    if not 0 <= profile.phase_percent <= 100:
        raise ConversionError("Phase must be between 0 and 100 percent")
    if not 0 <= profile.flac_compression <= 8:
        raise ConversionError("FLAC compression must be 0 through 8")

    command = [
        "nice", "-n", "10",
        "ionice", "-c", "2", "-n", "7",
        "sox", str(source),
        "-C", str(profile.flac_compression),
        "-b", str(target_bits), str(temp),
    ]
    if profile.headroom_db < 0:
        command += ["gain", str(profile.headroom_db)]

    command += ["rate"] + _quality_args(profile)
    command += ["-b", f"{profile.passband_percent:g}", "-p", f"{profile.phase_percent:g}"]
    if profile.allow_aliasing:
        command += ["-a"]
    command += [str(profile.target_rate)]

    if target_bits < source_bits:
        if profile.dither in (None, "tpdf"):
            command += ["dither"]
        elif profile.dither == "none":
            pass
        else:
            raise ConversionError(f"Unsupported dither mode: {profile.dither}")
    return command


def preview(source: Path, profile: ResampleProfile) -> dict[str, Any]:
    audio = FLAC(source)
    source_bits = int(audio.info.bits_per_sample)
    temp = source.with_name(f".{source.name}.sox-resampler.tmp.flac")
    blockers = preservation_blockers(source)
    try:
        command = build_sox_command(source, temp, profile, source_bits)
        profile_available = True
        profile_error = None
    except ProfileUnavailable as exc:
        command = []
        profile_available = False
        profile_error = str(exc)
    return {
        "path": str(source),
        "sample_rate": int(audio.info.sample_rate),
        "bits_per_sample": source_bits,
        "channels": int(audio.info.channels),
        "duration": float(audio.info.length),
        "size_bytes": source.stat().st_size,
        "metadata_block_types": flac_metadata_block_types(source),
        "preservation_blockers": blockers,
        "profile_available": profile_available,
        "profile_error": profile_error,
        "command": command,
    }


def _full_decode_test(path: Path) -> None:
    result = subprocess.run(["flac", "-t", "--silent", str(path)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ConversionError(f"FLAC full decode verification failed: {(result.stderr or result.stdout).strip()}")


def _peak(path: Path) -> float | None:
    result = subprocess.run(["sox", str(path), "-n", "stat"], capture_output=True, text=True, check=False)
    text = result.stderr or result.stdout
    match = re.search(r"Maximum amplitude:\s*([+-]?[0-9.]+)", text)
    return float(match.group(1)) if match else None


def convert_file(source: Path, profile: ResampleProfile) -> ConversionResult:
    source = source.resolve(strict=True)
    if source.suffix.lower() != ".flac":
        raise ConversionError("Only FLAC files may be converted")
    blockers = preservation_blockers(source)
    if blockers:
        raise ConversionError("; ".join(blockers))

    src_audio = FLAC(source)
    src_rate = int(src_audio.info.sample_rate)
    src_bits = int(src_audio.info.bits_per_sample)
    src_channels = int(src_audio.info.channels)
    src_duration = float(src_audio.info.length)
    target_bits = src_bits if profile.bit_depth == "preserve" else int(profile.bit_depth)
    temp = source.with_name(f".{source.name}.sox-resampler.tmp.flac")
    identity = source_identity(source)

    if temp.exists():
        raise ConversionError(f"Temporary file already exists: {temp}")

    command = build_sox_command(source, temp, profile, src_bits)
    result = ConversionResult(
        source=str(source), status="running", command=command, source_rate=src_rate,
        target_rate=profile.target_rate, source_bits=src_bits, target_bits=target_bits,
    )

    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise ConversionError(f"SoX failed: {(proc.stderr or proc.stdout).strip()}")
        if re.search(r"\bclipped\b", proc.stderr or "", re.IGNORECASE):
            raise ConversionError(f"SoX reported clipping: {proc.stderr.strip()}")

        copy_user_metadata(source, temp)
        compare_user_metadata(source, temp)

        out = FLAC(temp)
        if int(out.info.sample_rate) != profile.target_rate:
            raise ConversionError("Output sample rate verification failed")
        if int(out.info.bits_per_sample) != target_bits:
            raise ConversionError("Output bit-depth verification failed")
        if int(out.info.channels) != src_channels:
            raise ConversionError("Output channel-count verification failed")
        # One output-sample tolerance plus a tiny decoder timing margin.
        tolerance = max(1.0 / profile.target_rate, 0.00005)
        if abs(float(out.info.length) - src_duration) > tolerance:
            raise ConversionError("Output duration verification failed")

        _full_decode_test(temp)
        peak = _peak(temp)
        if peak is not None and peak > 1.0:
            raise ConversionError(f"Output peak exceeds full scale: {peak:.9f}")

        _copy_filesystem_metadata(source, temp)
        result.temp_sha256 = _sha256(temp)

        if source_identity(source) != identity:
            raise ConversionError("Source changed during conversion; refusing replacement")

        # Exchange instead of blind replace: after this operation the verified new file is at
        # the original path and the original file is retained at temp until final checksum passes.
        _rename_exchange(source, temp)
        try:
            result.final_sha256 = _sha256(source)
            if result.final_sha256 != result.temp_sha256:
                _rename_exchange(source, temp)
                raise ConversionError("Final checksum mismatch; atomic exchange rolled back")
        except Exception:
            # If a verification exception occurs while the old original still exists at temp,
            # make a best-effort rollback unless it already happened above.
            try:
                if temp.exists() and _sha256(source) != result.temp_sha256:
                    _rename_exchange(source, temp)
            except Exception:
                pass
            raise

        # temp now contains the original; remove only after final file verification succeeds.
        temp.unlink()
        result.status = "completed"
        return result
    except Exception as exc:
        if temp.exists():
            try:
                # Never delete the only remaining source. The temp name may contain the old original
                # only after a successful exchange; successful exchange paths return above.
                if source.exists():
                    temp.unlink()
            except OSError:
                pass
        result.status = "failed"
        result.error = str(exc)
        return result
