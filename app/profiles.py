from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

SUPPORTED_QUALITIES = ("ultra-37", "very-high", "high", "medium", "quick")
SUPPORTED_DITHER = (None, "tpdf", "shibata", "none")
EDITABLE_PROFILE_FIELDS = {
    "target_rate",
    "bit_depth",
    "quality",
    "passband_percent",
    "phase_percent",
    "allow_aliasing",
    "flac_compression",
    "dither",
    "headroom_db",
}


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
    notes: str = ""

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


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("Preset name is required")
    if len(name) > 100:
        raise ValueError("Preset name must be 100 characters or fewer")
    return name


def _clean_text(value: Any, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise ValueError(f"{label} must be {maximum} characters or fewer")
    return text


def _validate_bit_depth(value: Any) -> str | int:
    if value == "preserve":
        return "preserve"
    try:
        bits = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bit depth must be 'preserve' or an integer from 8 through 32") from exc
    if not 8 <= bits <= 32:
        raise ValueError("Bit depth must be 'preserve' or an integer from 8 through 32")
    return bits


def profile_from_dict(
    payload: dict[str, Any],
    *,
    id_override: str | None = None,
    read_only_override: bool | None = None,
) -> ResampleProfile:
    """Build a validated profile from persisted/imported JSON-compatible values."""
    profile_id = str(id_override if id_override is not None else payload.get("id", "")).strip()
    if not profile_id:
        raise ValueError("Preset id is required")
    if len(profile_id) > 120:
        raise ValueError("Preset id is too long")

    name = _clean_name(payload.get("name"))
    description = _clean_text(payload.get("description", ""), "Preset description", 2000)
    notes = _clean_text(payload.get("notes", ""), "Preset notes", 4000)

    try:
        target_rate = int(payload.get("target_rate"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Target sample rate must be an integer") from exc
    if not 8000 <= target_rate <= 768000:
        raise ValueError("Target sample rate must be between 8,000 and 768,000 Hz")

    bit_depth = _validate_bit_depth(payload.get("bit_depth", "preserve"))
    quality = str(payload.get("quality", "")).strip().lower()
    if quality not in SUPPORTED_QUALITIES:
        raise ValueError(f"Unsupported quality mode: {quality or '<missing>'}")

    try:
        passband = float(payload.get("passband_percent"))
        phase = float(payload.get("phase_percent"))
        compression = int(payload.get("flac_compression"))
        headroom = float(payload.get("headroom_db", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Preset DSP numeric values are invalid") from exc
    if not 0 < passband <= 99.7:
        raise ValueError("Passband must be greater than 0 and no more than 99.7 percent")
    if not 0 <= phase <= 100:
        raise ValueError("Phase response must be between 0 and 100 percent")
    if not 0 <= compression <= 8:
        raise ValueError("FLAC compression level must be from 0 through 8")
    if not -30.0 <= headroom <= 0.0:
        raise ValueError("Headroom must be between -30.0 dB and 0.0 dB")

    aliasing = payload.get("allow_aliasing", False)
    if not isinstance(aliasing, bool):
        raise ValueError("Allow aliasing must be true or false")

    dither = payload.get("dither")
    if dither == "":
        dither = None
    if dither not in SUPPORTED_DITHER:
        raise ValueError("Dither must be automatic/TPDF, TPDF, Shibata noise-shaped, or disabled")

    read_only = bool(payload.get("read_only", False)) if read_only_override is None else bool(read_only_override)
    implementation_ready = bool(payload.get("implementation_ready", True))
    return ResampleProfile(
        id=profile_id,
        name=name,
        description=description,
        target_rate=target_rate,
        bit_depth=bit_depth,
        quality=quality,
        passband_percent=passband,
        phase_percent=phase,
        allow_aliasing=aliasing,
        flac_compression=compression,
        dither=dither,
        headroom_db=headroom,
        read_only=read_only,
        implementation_ready=implementation_ready,
        notes=notes,
    )


def apply_profile_override(profile: ResampleProfile, override: dict[str, Any] | None) -> ResampleProfile:
    if not override:
        return profile
    unknown = sorted(set(override) - EDITABLE_PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"Unsupported Advanced DSP field(s): {', '.join(unknown)}")
    payload = profile.to_dict()
    payload.update(override)
    # A batch override is a runtime snapshot, not a mutation of the selected stored preset.
    return profile_from_dict(payload, id_override=profile.id, read_only_override=profile.read_only)


def list_profiles() -> list[dict[str, Any]]:
    return [profile.to_dict() for profile in BUILTIN_PROFILES.values()]


def get_profile(profile_id: str) -> ResampleProfile:
    try:
        return BUILTIN_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown built-in profile: {profile_id}") from exc


def profile_with_identity(profile: ResampleProfile, *, profile_id: str, name: str, description: str, notes: str = "") -> ResampleProfile:
    return replace(
        profile,
        id=profile_id,
        name=_clean_name(name),
        description=_clean_text(description, "Preset description", 2000),
        notes=_clean_text(notes, "Preset notes", 4000),
        read_only=False,
    )
