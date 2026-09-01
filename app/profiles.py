from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ResampleProfile:
    id: str
    name: str
    description: str
    target_rate: int
    bit_depth: str | int
    quality: str
    passband_percent: float
    phase_percent: float
    allow_aliasing: bool
    flac_compression: int
    dither: str | None = None
    headroom_db: float = 0.0
    read_only: bool = True
    implementation_ready: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FACTORY_DEFAULTS = ResampleProfile(
    id="factory-defaults",
    name="Factory Defaults",
    description="Conservative stock SoX very-high-quality baseline.",
    target_rate=48000,
    bit_depth="preserve",
    quality="very-high",
    passband_percent=95.0,
    phase_percent=50.0,
    allow_aliasing=False,
    flac_compression=4,
)

FOOBAR_ULTRA_37 = ResampleProfile(
    id="foobar-ultra-37-48k",
    name="Foobar Ultra 37 - 48 kHz",
    description=(
        "Closest technically accurate Linux implementation of the user's foobar2000 SoX Resampler "
        "0.8.9 profile: 48 kHz, 37-bit rate-filter accuracy (~222.8 dB), 95% 0 dB passband, "
        "50% linear phase, and aliasing disabled. It uses the same SoX rate engine with a guarded "
        "double-precision extension beyond stock SoX's 33-bit CLI limit; it is not claimed to be "
        "bit-for-bit identical to foobar's component wrapper/track-edge behavior."
    ),
    target_rate=48000,
    bit_depth="preserve",
    quality="ultra-37",
    passband_percent=95.0,
    phase_percent=50.0,
    allow_aliasing=False,
    flac_compression=4,
    implementation_ready=True,
)

BUILTIN_PROFILES: dict[str, ResampleProfile] = {
    FACTORY_DEFAULTS.id: FACTORY_DEFAULTS,
    FOOBAR_ULTRA_37.id: FOOBAR_ULTRA_37,
}


def list_profiles() -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in BUILTIN_PROFILES.values()]


def get_profile(profile_id: str) -> ResampleProfile:
    try:
        return BUILTIN_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown profile: {profile_id}") from exc
