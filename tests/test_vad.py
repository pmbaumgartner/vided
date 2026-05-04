from __future__ import annotations

import json
import types
import wave
from pathlib import Path

import pytest

from helpers import (
    build_trim_command_for_test,
    filtergraph_from,
    patch_probe_media,
    video_info,
    write_basic_project,
)
from vided import trimmer, vad
from vided.time_ranges import TimeRange


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
        media_info=video_info(source, duration=8.0, fps=30.0),
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
        media_info=video_info(source, duration=8.0, fps=30.0),
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
    project = write_basic_project(
        tmp_path / "project",
        trim_overrides={
            "vad": {"manual_keep_ranges": [{"start": 5.0, "end": 6.0}]},
        },
    )
    source = project / "input" / "original.mp4"

    patch_probe_media(monkeypatch, vad, duration=8.0, fps=30.0)

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


def test_vad_trim_command_uses_vad_activity_ranges(tmp_path, monkeypatch) -> None:
    project = write_basic_project(
        tmp_path / "project",
        trim_overrides={
            "vad": {"manual_keep_ranges": [{"start": 5.0, "end": 6.0}]},
        },
    )
    patch_probe_media(monkeypatch, trimmer, duration=10.0, fps=30.0)
    monkeypatch.setattr(
        trimmer,
        "load_or_create_vad_report",
        lambda *args, **kwargs: {
            "normal_speed_ranges": [{"start": 0.0, "end": 2.0}],
            "speech_ranges": [{"start": 0.0, "end": 2.0}],
        },
    )

    cmd = build_trim_command_for_test(
        project,
        options=trimmer.TrimOptions(detector="vad"),
    )
    graph = filtergraph_from(cmd)

    assert "trim=start=0:end=2,setpts=(PTS-STARTPTS)/1[v0]" in graph
    assert "trim=start=2:end=10,setpts=(PTS-STARTPTS)/8[v1]" in graph
    assert "atempo=2,atempo=2,atempo=2,volume=0[a1]" in graph


def test_vad_trim_command_preview_does_not_create_vad_report(tmp_path, monkeypatch) -> None:
    project = write_basic_project(tmp_path / "project")
    patch_probe_media(monkeypatch, trimmer, duration=10.0, fps=30.0)

    with pytest.raises(vad.ProjectError, match="VAD ranges not found or stale"):
        build_trim_command_for_test(
            project,
            options=trimmer.TrimOptions(detector="vad"),
        )

    assert not (project / "work" / "vad_ranges.json").exists()
    assert not (project / "work" / "vad.wav").exists()
