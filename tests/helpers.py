from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from vided.ffmpeg import VideoInfo
from vided.project import write_json
from vided.trimmer import TrimOptions, build_trim_command, plan_trim


def video_info(
    path: Path,
    *,
    duration: float = 10.0,
    fps: float | None = 60.0,
    has_audio: bool = True,
    width: int = 1920,
    height: int = 1080,
    video_codec: str | None = "h264",
    audio_codec: str | None = None,
    audio_sample_rate: int | None = 48000,
    audio_channels: int | None = 2,
) -> VideoInfo:
    return VideoInfo(
        path=path,
        width=width,
        height=height,
        duration=duration,
        fps=fps,
        video_codec=video_codec,
        audio_codec=(audio_codec or "aac") if has_audio else None,
        has_audio=has_audio,
        audio_sample_rate=audio_sample_rate if has_audio else None,
        audio_channels=audio_channels if has_audio else None,
    )


def write_basic_project(
    project: Path,
    *,
    trim_overrides: Mapping[str, Any] | None = None,
    render_overrides: Mapping[str, Any] | None = None,
) -> Path:
    (project / "input").mkdir(parents=True)
    (project / "work").mkdir()
    (project / "input" / "original.mp4").write_bytes(b"")

    trim = _merged(
        {
            "detector": "audio",
            "mode": "hybrid",
            "margin": "0.2s",
            "smooth": "0.2s,0.1s",
            "audio_threshold": 0.04,
            "long_silence_min_seconds": 1.5,
            "silent_speed": 8.0,
            "mute_silent_audio": True,
            "speed_indicator": {
                "enabled": False,
                "corner": "top-right",
                "style": "dark",
                "min_display_seconds": 1.0,
            },
            "vad": {
                "threshold": 0.5,
                "min_speech_duration_ms": 250,
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 150,
                "merge_speech_gap_seconds": 0.25,
                "manual_keep_ranges": [],
            },
        },
        trim_overrides,
    )
    render = _merged(
        {
            "video_codec": "libx264",
            "crf": 16,
            "preset": "medium",
            "pixel_format": "yuv420p",
            "audio_bitrate": "192k",
        },
        render_overrides,
    )
    write_json(
        project / "project.json",
        {
            "original_path": "input/original.mp4",
            "trimmed_path": "work/trimmed.mp4",
            "trim": trim,
            "render": render,
        },
    )
    return project


def patch_probe_media(monkeypatch, module, **video_info_kwargs: Any) -> None:
    monkeypatch.setattr(
        module,
        "probe_media",
        lambda path: video_info(path, **video_info_kwargs),
    )


def filtergraph_from(cmd: Sequence[str]) -> str:
    assert "-filter_complex" in cmd
    return cmd[cmd.index("-filter_complex") + 1]


def build_trim_command_for_test(
    project: Path,
    *,
    options: TrimOptions | None = None,
    allow_vad_detection: bool = False,
) -> list[str]:
    plan = plan_trim(project, options=options, allow_vad_detection=allow_vad_detection)
    return build_trim_command(plan)


def _merged(base: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(dict(base))
    if overrides is None:
        return result
    _deep_update(result, overrides)
    return result


def _deep_update(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _deep_update(existing, value)
        else:
            target[key] = value
