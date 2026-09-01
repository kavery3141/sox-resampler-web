from __future__ import annotations

import unittest
from pathlib import Path

from app.converter import build_sox_command
from app.profiles import profile_from_dict


class AdvancedDspCommandTests(unittest.TestCase):
    def _profile(self, **overrides):
        payload = {
            "id": "test",
            "name": "Test",
            "description": "",
            "target_rate": 48000,
            "bit_depth": "preserve",
            "quality": "very-high",
            "passband_percent": 95.0,
            "phase_percent": 50.0,
            "allow_aliasing": False,
            "flac_compression": 4,
            "dither": None,
            "headroom_db": 0.0,
            "read_only": False,
            "implementation_ready": True,
        }
        payload.update(overrides)
        return profile_from_dict(payload)

    def test_shibata_noise_shaping_is_used_only_on_bit_depth_reduction(self) -> None:
        profile = self._profile(bit_depth=16, dither="shibata")
        command = build_sox_command(Path("source.flac"), Path("temp.flac"), profile, 24)
        self.assertIn("dither", command)
        index = command.index("dither")
        self.assertEqual(command[index:index + 3], ["dither", "-f", "shibata"])

    def test_disabled_dither_adds_no_dither_effect(self) -> None:
        profile = self._profile(bit_depth=16, dither="none")
        command = build_sox_command(Path("source.flac"), Path("temp.flac"), profile, 24)
        self.assertNotIn("dither", command)

    def test_headroom_precedes_rate_effect(self) -> None:
        profile = self._profile(headroom_db=-1.5)
        command = build_sox_command(Path("source.flac"), Path("temp.flac"), profile, 24)
        self.assertLess(command.index("gain"), command.index("rate"))
        self.assertEqual(command[command.index("gain") + 1], "-1.5")


if __name__ == "__main__":
    unittest.main()
