from __future__ import annotations

import builtins
import json
import types
import wave
from pathlib import Path

import pytest

from vided import trimmer, vad
from vided.ffmpeg import VideoInfo
from vided.project import write_json
from vided.time_ranges import TimeRange


def _video_info(path: Path, *, duration: float = 8.0, has_audio: bool = True) -> VideoInfo:
    return VideoInfo(
        path=path,
        width=1920,
        height=1080,
        duration=duration,
        fps=30.0,
        video_codec="h264",
        audio_codec="aac" if has_audio else None,
        has_audio=has_audio,
        audio_sample_rate=48000 if has_audio else None,
        audio_channels=2 if has_audio else None,
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    (project / "work").mkdir()
    (project / "input" / "original.mp4").write_bytes(b"")
    write_json(
        project / "project.json",
        {
            "original_path": "input/original.mp4",
            "trimmed_path": "work/trimmed.mp4",
            "trim": {
                "detector": "audio",
                "mode": "hybrid",
                "margin": "0.2s",
                "smooth": "0.2s,0.1s",
                "audio_threshold": 0.04,
                "long_silence_min_seconds": 1.5,
                "silent_speed": 8.0,
                "mute_silent_audio": True,
                "silero": {
                    "threshold": 0.5,
                    "min_speech_duration_ms": 250,
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 150,
                    "merge_speech_gap_seconds": 0.25,
                    "manual_keep_ranges": [{"start": 5.0, "end": 6.0}],
                },
            },
            "render": {
                "video_codec": "libx264",
                "crf": 16,
                "preset": "medium",
                "pixel_format": "yuv420p",
                "audio_bitrate": "192k",
            },
        },
    )
    return project


def test_build_vad_report_merges_speech_and_manual_keep_ranges(tmp_path) -> None:
    project = tmp_path / "project"
    source = project / "input" / "original.mp4"
    audio = project / "work" / "vad.wav"
    settings = vad.VadSettings(
        merge_speech_gap_seconds=0.25,
        manual_keep_ranges=(TimeRange(start=5.0, end=6.0),),
    )

    report = vad.build_vad_report(
        project_root=project,
        source_video=source,
        audio_source=audio,
        media_info=_video_info(source),
        settings=settings,
        speech_ranges=[
            TimeRange(start=1.0, end=2.0),
            TimeRange(start=2.1, end=3.0),
        ],
    )

    assert report["speech_ranges"] == [{"start": 1.0, "end": 3.0}]
    assert report["normal_speed_ranges"] == [
        {"start": 1.0, "end": 3.0},
        {"start": 5.0, "end": 6.0},
    ]
    assert report["non_speech_ranges"] == [
        {"start": 0.0, "end": 1.0},
        {"start": 3.0, "end": 5.0},
        {"start": 6.0, "end": 8.0},
    ]


def test_build_vad_report_keeps_full_video_when_no_speech_is_detected(tmp_path) -> None:
    project = tmp_path / "project"
    source = project / "input" / "original.mp4"

    report = vad.build_vad_report(
        project_root=project,
        source_video=source,
        audio_source=None,
        media_info=_video_info(source),
        settings=vad.VadSettings(),
        speech_ranges=[],
    )

    assert report["speech_ranges"] == []
    assert report["normal_speed_ranges"] == [{"start": 0.0, "end": 8.0}]
    assert report["non_speech_ranges"] == []


def test_activity_ranges_from_vad_report_covers_normal_and_non_speech() -> None:
    report = {
        "normal_speed_ranges": [
            {"start": 1.0, "end": 3.0},
            {"start": 5.0, "end": 6.0},
        ]
    }

    assert vad.activity_ranges_from_vad_report(report, duration=8.0) == [
        (0.0, 1.0, False),
        (1.0, 3.0, True),
        (3.0, 5.0, False),
        (5.0, 6.0, True),
        (6.0, 8.0, False),
    ]


def test_detect_speech_ranges_reports_missing_optional_dependency(monkeypatch, tmp_path) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "onnxruntime":
            raise ImportError("missing onnxruntime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ValueError, match="uv sync --extra vad"):
        vad.detect_speech_ranges(tmp_path / "vad.wav", vad.VadSettings())


def test_read_wav_16k_mono_float32_reads_ffmpeg_wav(tmp_path) -> None:
    audio = tmp_path / "vad.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00\x00@")

    fake_np = types.SimpleNamespace(
        float32="float32",
        asarray=lambda values, dtype: {"values": values, "dtype": dtype},
    )

    samples = vad.read_wav_16k_mono_float32(audio, np_module=fake_np)

    assert samples["dtype"] == "float32"
    assert samples["values"] == [0.0, 0.5]


def test_speech_ranges_from_probabilities_uses_thresholds() -> None:
    class FakeModel:
        def __init__(self) -> None:
            self._probs = iter([0.8, 0.8, 0.1])
            self._np = None
            self.reset_count = 0

        def reset_states(self) -> None:
            self.reset_count += 1

        def __call__(self, chunk) -> float:
            return next(self._probs)

    model = FakeModel()

    ranges = vad.speech_ranges_from_probabilities(
        [0.0] * (vad.VAD_CHUNK_SAMPLES * 3),
        model=model,
        settings=vad.VadSettings(
            threshold=0.5,
            min_speech_duration_ms=1,
            min_silence_duration_ms=0,
            speech_pad_ms=0,
        ),
    )

    assert model.reset_count == 1
    assert ranges == [TimeRange(start=0.0, end=1024 / 16000)]


def test_vad_command_writes_vad_files_but_not_trimmed_video(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    source = project / "input" / "original.mp4"

    monkeypatch.setattr(vad, "probe_media", lambda path: _video_info(path))

    def fake_extract(_: Path, output: Path) -> Path:
        output.write_bytes(b"wav")
        return output

    monkeypatch.setattr(vad, "extract_vad_audio", fake_extract)
    monkeypatch.setattr(
        vad,
        "detect_speech_ranges",
        lambda path, settings: [TimeRange(start=1.0, end=2.0)],
    )

    output = vad.run_vad_detection(project)

    assert output == project / "work" / "vad_ranges.json"
    assert (project / "work" / "vad.wav").read_bytes() == b"wav"
    assert not (project / "work" / "trimmed.mp4").exists()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["source_video"] == "input/original.mp4"
    assert report["audio_source"] == "work/vad.wav"
    assert source.exists()


def test_silero_trim_command_uses_vad_activity_ranges(tmp_path, monkeypatch) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr(trimmer, "probe_media", lambda path: _video_info(path, duration=10.0))
    monkeypatch.setattr(
        trimmer,
        "load_or_create_vad_report",
        lambda *args, **kwargs: {
            "normal_speed_ranges": [{"start": 0.0, "end": 2.0}],
            "speech_ranges": [{"start": 0.0, "end": 2.0}],
        },
    )

    cmd = trimmer.build_ffmpeg_trim_command(project, detector="silero")
    graph = cmd[cmd.index("-filter_complex") + 1]

    assert "trim=start=0:end=2,setpts=(PTS-STARTPTS)/1[v0]" in graph
    assert "trim=start=2:end=10,setpts=(PTS-STARTPTS)/8[v1]" in graph
    assert "atempo=2,atempo=2,atempo=2,volume=0[a1]" in graph
