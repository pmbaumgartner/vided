from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from vided import cli


def test_default_project_dir_is_derived_from_source_filename() -> None:
    assert cli._default_project_dir(Path("Meeting Recording (Final)_v2.mov")) == Path(
        "meeting-recording-final-v2"
    )


def test_init_uses_derived_project_dir_when_only_source_is_given(monkeypatch) -> None:
    calls = {}

    def fake_create_project(source: Path, root: Path, **kwargs) -> dict[str, str]:
        calls["source"] = source
        calls["root"] = root
        calls["kwargs"] = kwargs
        return {"original_path": "input/original.mp4"}

    monkeypatch.setattr(cli, "create_project", fake_create_project)

    assert cli.main(["init", "Meeting Recording.mov"]) == 0
    assert calls["source"] == Path("Meeting Recording.mov")
    assert calls["root"] == Path("meeting-recording")
    assert calls["kwargs"]["copy_input"] is True


def test_init_accepts_explicit_output_dir_option(monkeypatch) -> None:
    calls = {}

    def fake_create_project(source: Path, root: Path, **kwargs) -> dict[str, str]:
        calls["source"] = source
        calls["root"] = root
        calls["kwargs"] = kwargs
        return {"original_path": "input/original.mp4"}

    monkeypatch.setattr(cli, "create_project", fake_create_project)

    assert cli.main(["init", "input.mp4", "--output-dir", "custom-project"]) == 0
    assert calls["source"] == Path("input.mp4")
    assert calls["root"] == Path("custom-project")


def test_init_rejects_positional_project_and_output_dir(monkeypatch, capsys) -> None:
    def fake_create_project(*args, **kwargs) -> dict[str, str]:
        raise AssertionError("create_project should not be called")

    monkeypatch.setattr(cli, "create_project", fake_create_project)

    assert cli.main(["init", "input.mp4", "project-dir", "--output-dir", "other-dir"]) == 1
    assert "Use either the project argument or --output-dir" in capsys.readouterr().err


def test_doctor_checks_only_ffmpeg_and_ffprobe(monkeypatch, capsys) -> None:
    checked_tools: list[str] = []

    def fake_ensure_tool(tool: str) -> str:
        checked_tools.append(tool)
        return f"/usr/bin/{tool}"

    monkeypatch.setattr(cli, "ensure_tool", fake_ensure_tool)

    assert cli.cmd_doctor(argparse.Namespace()) == 0
    assert checked_tools == ["ffmpeg", "ffprobe"]
    assert "auto-editor" not in capsys.readouterr().out


def test_trim_passes_detector_and_vad_options(monkeypatch) -> None:
    calls = {}
    plan = object()

    def fake_plan_trim(project: Path, **kwargs):
        calls["project"] = project
        calls["kwargs"] = kwargs
        return plan

    def fake_run_trim_plan(trim_plan, **kwargs):
        calls["plan"] = trim_plan
        calls["run_kwargs"] = kwargs
        return SimpleNamespace(path=Path("project-dir/work/trimmed.mp4"))

    monkeypatch.setattr(cli, "plan_trim", fake_plan_trim)
    monkeypatch.setattr(cli, "run_trim_plan", fake_run_trim_plan)

    assert (
        cli.main(
            [
                "trim",
                "project-dir",
                "--detector",
                "silero-vad",
                "--vad-threshold",
                "0.4",
                "--vad-min-speech-ms",
                "200",
                "--vad-min-silence-ms",
                "350",
                "--vad-speech-pad-ms",
                "125",
                "--vad-merge-gap",
                "0.3",
                "--speed-indicator",
                "--speed-indicator-corner",
                "bottom-right",
                "--speed-indicator-style",
                "light",
                "--speed-indicator-min-seconds",
                "1.25",
            ]
        )
        == 0
    )
    assert calls["project"] == Path("project-dir")
    options = calls["kwargs"]["options"]
    assert options.detector == "silero-vad"
    assert options.vad.threshold == 0.4
    assert options.vad.min_speech_duration_ms == 200
    assert options.vad.min_silence_duration_ms == 350
    assert options.vad.speech_pad_ms == 125
    assert options.vad.merge_speech_gap_seconds == 0.3
    assert options.speed_indicator is True
    assert options.speed_indicator_corner == "bottom-right"
    assert options.speed_indicator_style == "light"
    assert options.speed_indicator_min_display_seconds == 1.25
    assert calls["kwargs"]["allow_vad_detection"] is True
    assert calls["plan"] is plan
    assert calls["run_kwargs"]["overwrite"] is False
    assert calls["run_kwargs"]["dry_run"] is False


def test_trim_command_passes_speed_indicator_options(monkeypatch, capsys) -> None:
    calls = {}
    plan = object()

    def fake_plan_trim(project: Path, **kwargs):
        calls["project"] = project
        calls["kwargs"] = kwargs
        return plan

    def fake_build_trim_command(trim_plan) -> list[str]:
        calls["plan"] = trim_plan
        return ["ffmpeg", "-i", "input.mp4", "output.mp4"]

    monkeypatch.setattr(cli, "plan_trim", fake_plan_trim)
    monkeypatch.setattr(cli, "build_trim_command", fake_build_trim_command)

    assert (
        cli.main(
            [
                "trim-command",
                "project-dir",
                "--speed-indicator",
                "--speed-indicator-corner",
                "top-left",
                "--speed-indicator-style",
                "dark",
                "--speed-indicator-min-seconds",
                "0.75",
            ]
        )
        == 0
    )
    assert calls["project"] == Path("project-dir")
    options = calls["kwargs"]["options"]
    assert options.speed_indicator is True
    assert options.speed_indicator_corner == "top-left"
    assert options.speed_indicator_style == "dark"
    assert options.speed_indicator_min_display_seconds == 0.75
    assert calls["kwargs"]["allow_vad_detection"] is False
    assert calls["plan"] is plan
    assert "ffmpeg -i input.mp4 output.mp4" in capsys.readouterr().out


def test_vad_command_passes_vad_options(monkeypatch) -> None:
    calls = {}

    def fake_run_vad_detection(project: Path, **kwargs) -> Path:
        calls["project"] = project
        calls["kwargs"] = kwargs
        return project / "work" / "vad_ranges.json"

    monkeypatch.setattr(cli, "run_vad_detection", fake_run_vad_detection)

    assert cli.main(["vad", "project-dir", "--vad-threshold", "0.45"]) == 0
    assert calls["project"] == Path("project-dir")
    assert calls["kwargs"]["threshold"] == 0.45
