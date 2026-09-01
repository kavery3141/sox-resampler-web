from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC

from app.converter import convert_file
from app.profiles import FACTORY_DEFAULTS


class ConverterIntegrationTest(unittest.TestCase):
    def test_verified_in_place_96_to_48(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "01 - Test.flac"
            subprocess.run(
                [
                    "sox", "-n", "-r", "96000", "-b", "24", "-c", "2",
                    str(source), "synth", "0.25", "sine", "440", "vol", "0.25",
                ],
                check=True,
                capture_output=True,
            )
            audio = FLAC(source)
            audio["ALBUMARTIST"] = ["Test Artist"]
            audio["ALBUM"] = ["Test Album"]
            audio["RELEASETYPE"] = ["album"]
            audio["MUSICBRAINZ_ALBUMID"] = ["11111111-2222-3333-4444-555555555555"]
            audio["REPLAYGAIN_TRACK_GAIN"] = ["-1.23 dB"]
            audio["REPLAYGAIN_TRACK_PEAK"] = ["0.500000"]
            audio["REPLAYGAIN_ALBUM_GAIN"] = ["-1.00 dB"]
            audio["REPLAYGAIN_ALBUM_PEAK"] = ["0.600000"]
            audio.save()

            original_tags = {k.lower(): tuple(v) for k, v in FLAC(source).tags.items()}
            old_mtime_ns = 1_600_000_000_123_456_789
            os.chmod(source, 0o664)
            os.setxattr(source, "user.sox-resampler-test", b"preserve-me")
            os.utime(source, ns=(old_mtime_ns, old_mtime_ns))

            expected_source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
            result = convert_file(source, FACTORY_DEFAULTS, source_pre_hash=True)
            self.assertEqual(result.status, "completed", result.error)
            self.assertTrue(source.exists())
            self.assertFalse(source.with_name(f".{source.name}.sox-resampler.tmp.flac").exists())

            output = FLAC(source)
            self.assertEqual(output.info.sample_rate, 48000)
            self.assertEqual(output.info.bits_per_sample, 24)
            self.assertEqual(output.info.channels, 2)
            self.assertEqual({k.lower(): tuple(v) for k, v in output.tags.items()}, original_tags)
            self.assertEqual(source.stat().st_mtime_ns, old_mtime_ns)
            self.assertEqual(source.stat().st_mode & 0o777, 0o664)
            self.assertEqual(os.getxattr(source, "user.sox-resampler-test"), b"preserve-me")
            self.assertEqual(result.source_sha256, expected_source_sha256)
            self.assertIsNotNone(result.temp_sha256)
            self.assertEqual(result.temp_sha256, result.final_sha256)

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
            self.assertEqual(result.command[0:4], ["nice", "-n", "10", "ionice"])
            self.assertNotIn("cpulimit", result.command)
            self.assertFalse(source.with_name(f".{source.name}.sox-resampler.tmp.flac").exists())


if __name__ == "__main__":
    unittest.main()
