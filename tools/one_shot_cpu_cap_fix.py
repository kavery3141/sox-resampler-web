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
        '''def apply_cpu_limit(command: list[str], cpu_limit_percent: int | None) -> list[str]:
    """Wrap a SoX command with a per-worker CPU throttle when configured.

    ``cpulimit`` measures percentage relative to one logical CPU. Each conversion worker receives
    its own cap, so two workers may together consume up to roughly twice the configured value.
    The wrapper is operational only; it does not alter DSP settings or the resampling preset.
    """
    if cpu_limit_percent is None:
        return command
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
    # Keep cpulimit in the foreground so the job manager waits for the launched SoX
    # process. SIGTERM is forwarded to the child if the wrapper itself is stopped, which
    # keeps Force Stop semantics reliable with the extra supervisor process.
    return ["cpulimit", "-q", "-f", "-s", "SIGTERM", "-l", str(limit), "--", *command]
''',
        '''def validate_cpu_limit(cpu_limit_percent: int | None) -> int | None:
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
''',
        "replace wrapper with controller helpers",
    )

    replace_once(
        "app/converter.py",
        '''        command = build_sox_command(source, temp, profile, source_bits)
        command = apply_cpu_limit(command, cpu_limit_percent)
        profile_available = True
''',
        '''        command = build_sox_command(source, temp, profile, source_bits)
        validate_cpu_limit(cpu_limit_percent)
        profile_available = True
''',
        "preview validates without wrapping",
    )

    replace_once(
        "app/converter.py",
        '''def _run_sox_command(
    command: list[str],
    abort_check: Callable[[], bool] | None,
) -> subprocess.CompletedProcess[str]:
    if abort_check is None:
        return subprocess.run(command, capture_output=True, text=True, check=False)

    _check_force_stop(abort_check)
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if abort_check():
                    _terminate_process_group(proc)
                    try:
                        proc.communicate(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
                    raise ConversionError("Force stop requested by user; SoX terminated and original left untouched")
    except Exception:
        if proc.poll() is None:
            _terminate_process_group(proc)
        raise
''',
        '''def _stop_cpu_limiter(controller: subprocess.Popen[str] | None) -> None:
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
''',
        "run SoX with separate CPU controller",
    )

    replace_once(
        "app/converter.py",
        '''    command = build_sox_command(source, temp, profile, src_bits)
    command = apply_cpu_limit(command, cpu_limit_percent)
    result = ConversionResult(
''',
        '''    command = build_sox_command(source, temp, profile, src_bits)
    validate_cpu_limit(cpu_limit_percent)
    result = ConversionResult(
''',
        "conversion command stays SoX command",
    )

    replace_once(
        "app/converter.py",
        '''        proc = _run_sox_command(command, combined_abort_check)
''',
        '''        proc = _run_sox_command(
            command,
            combined_abort_check,
            cpu_limit_percent=cpu_limit_percent,
        )
''',
        "pass CPU cap to runtime controller",
    )


def patch_review() -> None:
    replace_once(
        "app/review.py",
        '''                        detail = preview(
                            resolved_source,
                            profile,
                            cpu_limit_percent=cpu_limit_percent,
                        )
''',
        '''                        if cpu_limit_percent is None:
                            # Keep the default uncapped preflight call compatible with ordinary
                            # preview consumers and mocks. CPU control is operational, not DSP.
                            detail = preview(resolved_source, profile)
                        else:
                            detail = preview(
                                resolved_source,
                                profile,
                                cpu_limit_percent=cpu_limit_percent,
                            )
''',
        "uncapped preview compatibility",
    )


def patch_tests() -> None:
    replace_once(
        "tests/test_cpu_limit.py",
        '''from app.converter import ConversionError, ProfileUnavailable, apply_cpu_limit
''',
        '''from app.converter import (
    ConversionError,
    ProfileUnavailable,
    cpu_limiter_command,
    validate_cpu_limit,
)
''',
        "CPU test imports",
    )
    replace_once(
        "tests/test_cpu_limit.py",
        '''    def test_disabled_limit_leaves_command_unchanged(self) -> None:
        command = ["nice", "-n", "10", "sox", "in.flac", "out.flac"]
        self.assertIs(apply_cpu_limit(command, None), command)

    def test_enabled_limit_wraps_complete_execution_command(self) -> None:
        command = ["nice", "-n", "10", "ionice", "-c", "2", "sox", "in.flac", "out.flac"]
        with patch("app.converter.shutil.which", return_value="/usr/bin/cpulimit"):
            wrapped = apply_cpu_limit(command, 55)
        self.assertEqual(
            wrapped[:9],
            ["cpulimit", "-q", "-f", "-s", "SIGTERM", "-l", "55", "--", "nice"],
        )
        self.assertEqual(wrapped[8:], command)

    def test_invalid_limit_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            apply_cpu_limit(["sox"], 9)
        with self.assertRaises(ConversionError):
            apply_cpu_limit(["sox"], 101)

    def test_missing_cpulimit_fails_before_conversion(self) -> None:
        with patch("app.converter.shutil.which", return_value=None):
            with self.assertRaises(ProfileUnavailable):
                apply_cpu_limit(["sox"], 50)
''',
        '''    def test_disabled_limit_requires_no_limiter(self) -> None:
        self.assertIsNone(validate_cpu_limit(None))

    def test_enabled_limit_validates_and_builds_pid_controller(self) -> None:
        with patch("app.converter.shutil.which", return_value="/usr/bin/cpulimit"):
            limit = validate_cpu_limit(55)
        self.assertEqual(limit, 55)
        self.assertEqual(
            cpu_limiter_command(1234, limit),
            ["cpulimit", "-q", "-z", "-l", "55", "-p", "1234"],
        )

    def test_invalid_limit_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            validate_cpu_limit(9)
        with self.assertRaises(ConversionError):
            validate_cpu_limit(101)
        with self.assertRaises(ConversionError):
            cpu_limiter_command(0, 50)

    def test_missing_cpulimit_fails_before_conversion(self) -> None:
        with patch("app.converter.shutil.which", return_value=None):
            with self.assertRaises(ProfileUnavailable):
                validate_cpu_limit(50)
''',
        "CPU tests for PID controller",
    )
    replace_once(
        "tests/test_converter_integration.py",
        '''            self.assertEqual(
                result.command[:8],
                ["cpulimit", "-q", "-f", "-s", "SIGTERM", "-l", "100", "--"],
            )
''',
        '''            self.assertEqual(result.command[0:4], ["nice", "-n", "10", "ionice"])
            self.assertNotIn("cpulimit", result.command)
''',
        "integration expects independent limiter controller",
    )


if __name__ == "__main__":
    patch_converter()
    patch_review()
    patch_tests()
