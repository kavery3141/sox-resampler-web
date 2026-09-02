from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen.flac import FLAC

from app.replaygain import ReplayGainValues, scan_album, _write_values


class Completed:
    returncode = 0
    stdout = (
        "Filename\tLoudness\tGain\tPeak\tPeak dB\tPeak Type\tClipping Adjustment\n"
        "one.flac\t-12.00\t-6.00\t0.900000\t-0.92\tTrue\t0.00\n"
        "two.flac\t-14.00\t-4.00\t0.800000\t-1.94\tTrue\t0.00\n"
        "Album\t-13.00\t-5.00\t0.950000\t-0.45\tTrue\t0.00\n"
    )


class ReplayGainTests(unittest.TestCase):
    @patch("app.replaygain.subprocess.run", return_value=Completed())
    def test_scan_album_uses_picard_style_true_peak_settings(self, run):
        paths = [Path("/music/one.flac"), Path("/music/two.flac")]
        result = scan_album(paths)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["rsgain", "custom", "-O"])
        for token in ("-a", "-t", "-18", "a", "0"):
            self.assertIn(token, command)
        self.assertEqual(result[paths[0]].track_gain, "-6.00 dB")
        self.assertEqual(result[paths[0]].track_peak, "0.900000")
        self.assertEqual(result[paths[0]].album_gain, "-5.00 dB")
        self.assertEqual(result[paths[0]].album_peak, "0.950000")
        self.assertEqual(result[paths[0]].reference_loudness, "-18.00 LUFS")

    def test_write_values_preserves_existing_tag_casing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.flac"
            # Create a tiny valid FLAC with SoX, available in the container test image.
            import subprocess
            subprocess.run(["sox", "-n", "-r", "48000", "-b", "16", str(path), "synth", "0.01", "sine", "440"], check=True)
            audio = FLAC(path)
            audio["replaygain_track_gain"] = ["-1.00 dB"]
            audio["REPLAYGAIN_TRACK_PEAK"] = ["0.5"]
            audio["TITLE"] = ["Keep Me"]
            audio.save()
            _write_values(path, ReplayGainValues("-2.00 dB", "0.8", "-3.00 dB", "0.9"))
            updated = FLAC(path)
            keys = list(updated.tags.keys())
            self.assertTrue(any(k.lower() == "replaygain_track_gain" for k in keys))
            self.assertEqual(updated["replaygain_track_gain"], ["-2.00 dB"])
            self.assertEqual(updated["REPLAYGAIN_TRACK_PEAK"], ["0.8"])
            self.assertEqual(updated["REPLAYGAIN_ALBUM_GAIN"], ["-3.00 dB"])
            self.assertEqual(updated["REPLAYGAIN_ALBUM_PEAK"], ["0.9"])
            self.assertEqual(updated["REPLAYGAIN_REFERENCE_LOUDNESS"], ["-18.00 LUFS"])
            self.assertEqual(updated["TITLE"], ["Keep Me"])


if __name__ == "__main__":
    unittest.main()
