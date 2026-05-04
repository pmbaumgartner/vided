from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .errors import ValidationError

AudioPresetName = Literal["none", "level", "voice-safe"]


@dataclass(frozen=True)
class AudioPreset:
    name: AudioPresetName
    description: str
    filter_chain: str | None


_PRESETS: dict[str, AudioPreset] = {
    "none": AudioPreset(
        name="none",
        description="Leave audio unchanged.",
        filter_chain=None,
    ),
    "level": AudioPreset(
        name="level",
        description="Normalize loudness and prevent clipping.",
        filter_chain="loudnorm=I=-18:LRA=11:TP=-2.0,alimiter=limit=0.95:attack=5:release=50",
    ),
    "voice-safe": AudioPreset(
        name="voice-safe",
        description="Apply conservative voice cleanup and loudness normalization.",
        filter_chain=(
            "highpass=f=90,"
            "equalizer=f=250:t=q:w=1:g=-1,"
            "equalizer=f=3500:t=q:w=1:g=1,"
            "acompressor=threshold=0.125:ratio=2.5:attack=8:release=120:makeup=1.0,"
            "loudnorm=I=-18:LRA=11:TP=-2.0,"
            "alimiter=limit=0.95:attack=5:release=50"
        ),
    ),
}


def normalize_audio_preset(value: str | None) -> AudioPresetName:
    raw = (value or "none").strip().lower()
    preset = _PRESETS.get(raw)
    if preset is None:
        names = ", ".join(_PRESETS)
        raise ValidationError(f"audio preset must be one of: {names}")
    return preset.name


def get_audio_preset(value: str | None) -> AudioPreset:
    return _PRESETS[normalize_audio_preset(value)]


def audio_filter_for_preset(value: str | None) -> str | None:
    return get_audio_preset(value).filter_chain


def list_audio_presets() -> list[AudioPreset]:
    return list(_PRESETS.values())
