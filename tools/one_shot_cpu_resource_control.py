from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "app/converter.py",
        '    return ["cpulimit", "-q", "-l", str(limit), "--", *command]\n',
        '    # Keep cpulimit in the foreground so the job manager waits for the launched SoX\n'
        '    # process. SIGTERM is forwarded to the child if the wrapper itself is stopped, which\n'
        '    # keeps Force Stop semantics reliable with the extra supervisor process.\n'
        '    return ["cpulimit", "-q", "-f", "-s", "SIGTERM", "-l", str(limit), "--", *command]\n',
        "foreground cpulimit wrapper",
    )

    replace_once(
        "tests/test_cpu_limit.py",
        '''        self.assertEqual(wrapped[:6], ["cpulimit", "-q", "-l", "55", "--", "nice"])
        self.assertEqual(wrapped[5:], command)
''',
        '''        self.assertEqual(
            wrapped[:9],
            ["cpulimit", "-q", "-f", "-s", "SIGTERM", "-l", "55", "--", "nice"],
        )
        self.assertEqual(wrapped[8:], command)
''',
        "CPU wrapper unit expectation",
    )

    replace_once(
        "tests/test_converter_integration.py",
        '''            self.assertEqual(result.temp_sha256, result.final_sha256)


if __name__ == "__main__":
''',
        '''            self.assertEqual(result.temp_sha256, result.final_sha256)

    def test_verified_in_place_conversion_with_cpu_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "02 - CPU Capped.flac"
            subprocess.run(
                [
                    "sox", "-n", "-r", "96000", "-b", "24", "-c", "2",
                    str(source), "synth", "0.20", "sine", "997", "vol", "0.1",
                ],
                check=True,
                capture_output=True,
            )
            audio = FLAC(source)
            audio["ALBUMARTIST"] = ["Test Artist"]
            audio["ALBUM"] = ["CPU Cap Test"]
            audio["RELEASETYPE"] = ["album"]
            audio["MUSICBRAINZ_ALBUMID"] = ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
            audio.save()

            result = convert_file(source, FACTORY_DEFAULTS, cpu_limit_percent=100)
            self.assertEqual(result.status, "completed", result.error)
            self.assertEqual(FLAC(source).info.sample_rate, 48000)
            self.assertTrue(result.command)
            self.assertEqual(
                result.command[:8],
                ["cpulimit", "-q", "-f", "-s", "SIGTERM", "-l", "100", "--"],
            )
            self.assertFalse(source.with_name(f".{source.name}.sox-resampler.tmp.flac").exists())


if __name__ == "__main__":
''',
        "CPU cap converter integration test",
    )


if __name__ == "__main__":
    main()
