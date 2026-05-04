from __future__ import annotations

import pytest

from vided.audio_presets import audio_filter_for_preset, list_audio_presets, normalize_audio_preset
from vided.errors import ValidationError


def test_audio_presets_are_small_and_named() -> None:
    presets = list_audio_presets()

    assert [preset.name for preset in presets] == ["none", "level", "voice-safe"]
    assert audio_filter_for_preset("none") is None
    assert audio_filter_for_preset("level") == (
        "loudnorm=I=-18:LRA=11:TP=-2.0,alimiter=limit=0.95:attack=5:release=50"
    )
    voice_safe = str(audio_filter_for_preset("voice-safe"))
    assert "acompressor=" in voice_safe
    assert "makeup=1.0" in voice_safe
    assert "loudnorm=I=-18:LRA=11:TP=-2.0" in voice_safe


def test_audio_preset_names_normalize_and_validate() -> None:
    assert normalize_audio_preset(" VOICE-SAFE ") == "voice-safe"

    with pytest.raises(ValidationError, match="audio preset must be one of"):
        normalize_audio_preset("laptop-noisy")
