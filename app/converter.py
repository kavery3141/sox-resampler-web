from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mutagen.flac import FLAC

from .force_stop import abort_requested as registered_abort_requested
from .force_stop import register_active, unregister_active
from .profiles import ResampleProfile
from .resource_control import CPU_LIMIT_MAX, CPU_LIMIT_MIN
from .transactions import ReplacementJournal, recover_journals


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


@dataclass(frozen=True)
class FilesystemMetadata:
    mode: int
    uid: int
    gid: int
    atime_ns: int
    mtime_ns: int
    xattrs: tuple[tuple[str, bytes], ...]


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


STREAMINFO = 0
PADDING = 1
APPLICATION = 2
SEEKTABLE = 3
VORBIS_COMMENT = 4
CUESHEET = 5
PICTURE = 6

AT_FDCWD = -100
RENAME_EXCHANGE = 2
CAP_CHOWN = 0
SOX_ULTRA_BIN = os.getenv("SOX_ULTRA_BIN", "/opt/sox-ultra/bin/sox")


def source_identity(path: Path) -> SourceIdentity:
    st = path.stat()
    return SourceIdentity(st.st_ino, st.st_dev, st.st_size, st.st_mtime_ns)


def filesystem_metadata(path: Path) -> FilesystemMetadata:
    st = path.stat(follow_symlinks=False)
    try:
        names = sorted(os.listxattr(path, follow_symlinks=False))
    except OSError as exc:
        raise ConversionError(f"Cannot read extended-attribute list for {path}") from exc
    values: list[tuple[str, bytes]] = []
    for name in names:
        try:
            values.append((name, os.getxattr(path, name, follow_symlinks=False)))
        except OSError as exc:
            raise ConversionError(f"Cannot read extended attribute {name!r} from {path}") from exc
    return FilesystemMetadata(
        mode=stat.S_IMODE(st.st_mode),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
        atime_ns=int(st.st_atime_ns),
        mtime_ns=int(st.st_mtime_ns),
        xattrs=tuple(values),
    )


def _verify_filesystem_metadata(path: Path, expected: FilesystemMetadata, label: str) -> None:
    actual = filesystem_metadata(path)
    if actual.mode != expected.mode:
        raise ConversionError(
            f"{label} mode mismatch: expected {expected.mode:o}, got {actual.mode:o}"
        )
    if (actual.uid, actual.gid) != (expected.uid, expected.gid):
        raise ConversionError(
            f"{label} owner/group mismatch: expected {expected.uid}:{expected.gid}, "
            f"got {actual.uid}:{actual.gid}"
        )
    if actual.mtime_ns != expected.mtime_ns:
        raise ConversionError(f"{label} modification timestamp mismatch")
    if actual.xattrs != expected.xattrs:
        expected_names = [name for name, _ in expected.xattrs]
        actual_names = [name for name, _ in actual.xattrs]
        raise ConversionError(
            f"{label} extended attributes differ: expected {expected_names}, got {actual_names}"
        )


def _apply_filesystem_metadata(target: Path, expected: FilesystemMetadata) -> None:
    try:
        os.chmod(target, expected.mode, follow_symlinks=False)
    except OSError as exc:
        raise ConversionError(f"Cannot preserve mode {expected.mode:o}") from exc

    target_st = target.stat(follow_symlinks=False)
    if (target_st.st_uid, target_st.st_gid) != (expected.uid, expected.gid):
        try:
            os.chown(target, expected.uid, expected.gid, follow_symlinks=False)
        except OSError as exc:
            raise ConversionError(
                f"Cannot preserve owner/group {expected.uid}:{expected.gid}; refusing replacement"
            ) from exc

    expected_xattrs = dict(expected.xattrs)
    try:
        current_names = set(os.listxattr(target, follow_symlinks=False))
    except OSError as exc:
        raise ConversionError("Cannot inspect output extended attributes") from exc

    for name in sorted(current_names - set(expected_xattrs)):
        try:
            os.removexattr(target, name, follow_symlinks=False)
        except OSError as exc:
            raise ConversionError(f"Cannot remove unexpected extended attribute {name!r}") from exc

    for name, value in expected.xattrs:
        try:
            os.setxattr(target, name, value, follow_symlinks=False)
        except OSError as exc:
            raise ConversionError(f"Cannot preserve extended attribute {name!r}") from exc

    try:
        os.utime(
            target,
            ns=(expected.atime_ns, expected.mtime_ns),
            follow_symlinks=False,
        )
    except OSError as exc:
        raise ConversionError("Cannot preserve modification timestamp") from exc

    _verify_filesystem_metadata(target, expected, "Generated output")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def flac_metadata_block_types(path: Path) -> list[int]:
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


def _effective_linux_capabilities() -> int:
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


def _rename_exchange(path_a: Path, path_b: Path) -> None:
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


def recover_pending_transactions(data_root: Path | None = None) -> list[dict[str, str]]:
    root = (data_root or Path(os.getenv("DATA_ROOT", "/data"))) / "transactions"
    return recover_journals(root, _rename_exchange)


def _stock_quality_args(profile: ResampleProfile) -> list[str]:
    quality = {
        "very-high": ["-v"],
        "high": ["-h"],
        "medium": ["-m"],
        "quick": ["-q"],
    }.get(profile.quality)
    if quality is None:
        raise ConversionError(f"Unsupported stock SoX quality mode: {profile.quality}")
    return quality


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
    if not -30.0 <= profile.headroom_db <= 0.0:
        raise ConversionError("Headroom must be between -30.0 dB and 0.0 dB")
    if not profile.implementation_ready:
        raise ProfileUnavailable(f"Profile backend is not ready: {profile.name}")

    ultra37 = profile.quality == "ultra-37"
    sox_binary = SOX_ULTRA_BIN if ultra37 else "sox"
    if ultra37 and not Path(sox_binary).is_file():
        raise ProfileUnavailable(f"Ultra 37 SoX backend is missing: {sox_binary}")

    command = [
        "nice",
        "-n",
        "10",
        "ionice",
        "-c",
        "2",
        "-n",
        "7",
        sox_binary,
        str(source),
        "-C",
        str(profile.flac_compression),
        "-b",
        str(target_bits),
        str(temp),
    ]
    if profile.headroom_db < 0:
        command += ["gain", str(profile.headroom_db)]

    if ultra37:
        command += [
            "rate",
            "-d",
            "37",
            "-B",
            f"{profile.passband_percent:g}",
            "-p",
            f"{profile.phase_percent:g}",
        ]
    else:
        command += ["rate"] + _stock_quality_args(profile)
        command += ["-b", f"{profile.passband_percent:g}", "-p", f"{profile.phase_percent:g}"]

    if profile.allow_aliasing:
        command += ["-a"]
    command += [str(profile.target_rate)]

    if target_bits < source_bits:
        if profile.dither in (None, "tpdf"):
            command += ["dither"]
        elif profile.dither == "shibata":
            command += ["dither", "-f", "shibata"]
        elif profile.dither != "none":
            raise ConversionError(f"Unsupported dither mode: {profile.dither}")
    return command


def validate_cpu_limit(cpu_limit_percent: int | None) -> int | None:
    """Validate an optional per-worker CPU ceiling without changing the SoX command.

    CPU throttling is applied by a separate controller attached to the exact spawned SoX PID. This
    lets the converter wait for SoX itself and preserves its real exit status instead of trusting a
    wrapper process to proxy it.
    """
    if cpu_limit_percent is None:
        return None
    try:
        limit = int(cpu_limit_percent)
    except (TypeError, ValueError) as exc:
        raise ConversionError("CPU limit must be an integer percentage") from exc
    if not CPU_LIMIT_MIN <= limit <= CPU_LIMIT_MAX:
        raise ConversionError(
            f"CPU limit must be between {CPU_LIMIT_MIN} and {CPU_LIMIT_MAX} percent per worker"
        )
    if shutil.which("cpulimit") is None:
        raise ProfileUnavailable(
            "A conversion CPU cap is configured but the cpulimit runtime is unavailable"
        )
    return limit


def cpu_limiter_command(pid: int, limit: int) -> list[str]:
    if pid <= 0:
        raise ConversionError("CPU limiter requires a valid SoX process ID")
    return ["cpulimit", "-q", "-z", "-l", str(limit), "-p", str(pid)]


def preview(
    source: Path,
    profile: ResampleProfile,
    *,
    cpu_limit_percent: int | None = None,
) -> dict[str, Any]:
    audio = FLAC(source)
    source_bits = int(audio.info.bits_per_sample)
    temp = source.with_name(f".{source.name}.sox-resampler.tmp.flac")
    blockers = preservation_blockers(source)
    try:
        command = build_sox_command(source, temp, profile, source_bits)
        validate_cpu_limit(cpu_limit_percent)
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
    result = subprocess.run(
        ["flac", "-t", "--silent", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ConversionError(f"FLAC full decode verification failed: {(result.stderr or result.stdout).strip()}")


def _peak(path: Path) -> float | None:
    result = subprocess.run(
        ["sox", str(path), "-n", "stat"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = result.stderr or result.stdout
    match = re.search(r"Maximum amplitude:\s*([+-]?[0-9.]+)", text)
    return float(match.group(1)) if match else None


def _check_force_stop(abort_check: Callable[[], bool] | None) -> None:
    if abort_check is not None and bool(abort_check()):
        raise ConversionError("Force stop requested by user; original left untouched")


def _terminate_process_group(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def _stop_cpu_limiter(controller: subprocess.Popen[str] | None) -> None:
    if controller is None:
        return
    if controller.poll() is None:
        controller.terminate()
    try:
        controller.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        controller.kill()
        try:
            controller.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def _run_sox_command(
    command: list[str],
    abort_check: Callable[[], bool] | None,
    cpu_limit_percent: int | None = None,
) -> subprocess.CompletedProcess[str]:
    limit = validate_cpu_limit(cpu_limit_percent)
    if abort_check is not None:
        _check_force_stop(abort_check)

    # Always use Popen when a limiter is active so cpulimit can target the exact SoX process PID.
    # `nice` and `ionice` exec the next program, retaining this PID through to SoX.
    if limit is None and abort_check is None:
        return subprocess.run(command, capture_output=True, text=True, check=False)

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    controller: subprocess.Popen[str] | None = None
    try:
        if limit is not None:
            controller = subprocess.Popen(
                cpu_limiter_command(proc.pid, limit),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                # A very short SoX process can finish before cpulimit's process scan attaches. That
                # tiny burst is harmless; SoX's real result remains authoritative. For any longer
                # conversion, a limiter failure while SoX is still alive is treated as a hard file
                # failure so an explicitly configured cap is never silently ignored.
                return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if abort_check is not None and abort_check():
                    _terminate_process_group(proc)
                    try:
                        proc.communicate(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
                    raise ConversionError("Force stop requested by user; SoX terminated and original left untouched")
                if controller is not None:
                    controller_rc = controller.poll()
                    if controller_rc not in (None, 0) and proc.poll() is None:
                        _, limiter_stderr = controller.communicate(timeout=1.0)
                        _terminate_process_group(proc)
                        detail = (limiter_stderr or "cpulimit exited unexpectedly").strip()
                        raise ConversionError(f"CPU limiter failed while SoX was running: {detail}")
    except Exception:
        if proc.poll() is None:
            _terminate_process_group(proc)
        raise
    finally:
        _stop_cpu_limiter(controller)


def convert_file(
    source: Path,
    profile: ResampleProfile,
    journal_root: Path | None = None,
    *,
    cpu_limit_percent: int | None = None,
    abort_check: Callable[[], bool] | None = None,
) -> ConversionResult:
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
    fs_metadata = filesystem_metadata(source)
    if temp.exists():
        raise ConversionError(f"Temporary file already exists: {temp}")

    command = build_sox_command(source, temp, profile, src_bits)
    validate_cpu_limit(cpu_limit_percent)
    result = ConversionResult(
        source=str(source),
        status="running",
        command=command,
        source_rate=src_rate,
        target_rate=profile.target_rate,
        source_bits=src_bits,
        target_bits=target_bits,
    )
    exchanged = False
    completed = False
    journal_root = journal_root or Path(os.getenv("DATA_ROOT", "/data")) / "transactions"
    journal = ReplacementJournal(journal_root, source)
    journal_prepared = False
    active_token = register_active(source)

    def combined_abort_check() -> bool:
        external = bool(abort_check()) if abort_check is not None else False
        return external or registered_abort_requested(source, active_token)

    try:
        _check_force_stop(combined_abort_check)
        proc = _run_sox_command(
            command,
            combined_abort_check,
            cpu_limit_percent=cpu_limit_percent,
        )
        if proc.returncode != 0:
            raise ConversionError(f"SoX failed: {(proc.stderr or proc.stdout).strip()}")
        if re.search(r"\bclipped\b", proc.stderr or "", re.IGNORECASE):
            raise ConversionError(f"SoX reported clipping: {proc.stderr.strip()}")
        _check_force_stop(combined_abort_check)

        copy_user_metadata(source, temp)
        compare_user_metadata(source, temp)
        _check_force_stop(combined_abort_check)
        out = FLAC(temp)
        if int(out.info.sample_rate) != profile.target_rate:
            raise ConversionError("Output sample rate verification failed")
        if int(out.info.bits_per_sample) != target_bits:
            raise ConversionError("Output bit-depth verification failed")
        if int(out.info.channels) != src_channels:
            raise ConversionError("Output channel-count verification failed")
        tolerance = max(1.0 / profile.target_rate, 0.00005)
        if abs(float(out.info.length) - src_duration) > tolerance:
            raise ConversionError("Output duration verification failed")

        _full_decode_test(temp)
        _check_force_stop(combined_abort_check)
        peak = _peak(temp)
        if peak is not None and peak > 1.0:
            raise ConversionError(f"Output peak exceeds full scale: {peak:.9f}")

        _apply_filesystem_metadata(temp, fs_metadata)
        result.temp_sha256 = _sha256(temp)
        _check_force_stop(combined_abort_check)

        if source_identity(source) != identity:
            raise ConversionError("Source changed during conversion; refusing replacement")
        _verify_filesystem_metadata(source, fs_metadata, "Source before replacement")
        _check_force_stop(combined_abort_check)

        journal.prepare(source, temp, identity, result.temp_sha256)
        journal_prepared = True
        _check_force_stop(combined_abort_check)

        _rename_exchange(source, temp)
        exchanged = True
        journal.mark_exchanged()

        result.final_sha256 = _sha256(source)
        if result.final_sha256 != result.temp_sha256:
            raise ConversionError("Final checksum mismatch")
        _verify_filesystem_metadata(source, fs_metadata, "Final replacement")
        journal.mark_verified()

        temp.unlink()
        exchanged = False
        journal.clear()
        journal_prepared = False
        completed = True
        result.status = "completed"
        return result
    except Exception as exc:
        if exchanged:
            try:
                _rename_exchange(source, temp)
                exchanged = False
                journal.clear()
                journal_prepared = False
            except Exception as rollback_exc:
                result.error = f"{exc}; CRITICAL rollback failure: {rollback_exc}"
                result.status = "failed"
                return result
        elif journal_prepared:
            journal.clear()
            journal_prepared = False
        result.status = "failed"
        result.error = str(exc)
        return result
    finally:
        unregister_active(source, active_token)
        if not completed and not exchanged and temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
