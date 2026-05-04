from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from vided import cli
from vided._version import get_version
from vided.skill_installer import SkillInstallResult


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


def test_init_rejects_positional_project(monkeypatch, capsys) -> None:
    def fake_create_project(*args, **kwargs) -> dict[str, str]:
        raise AssertionError("create_project should not be called")

    monkeypatch.setattr(cli, "create_project", fake_create_project)

    assert cli.main(["init", "input.mp4", "project-dir"]) == 2
    assert "Unused Tokens" in capsys.readouterr().err


def test_doctor_checks_only_ffmpeg_and_ffprobe(monkeypatch, capsys) -> None:
    checked_tools: list[str] = []

    def fake_ensure_tool(tool: str) -> str:
        checked_tools.append(tool)
        return f"/usr/bin/{tool}"

    monkeypatch.setattr(cli, "ensure_tool", fake_ensure_tool)

    assert cli.doctor() == 0
    assert checked_tools == ["ffmpeg", "ffprobe"]
    assert "auto-editor" not in capsys.readouterr().out


def test_top_level_help_lists_public_commands_and_version_flags() -> None:
    help_text = cli.help_text()

    assert "frames:" not in help_text
    assert "ui:" in help_text
    assert "install-skill:" in help_text
    assert "validate:" not in help_text
    assert "--version" in help_text
    assert "-v" in help_text


def test_version_flags_print_current_version(capsys) -> None:
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == get_version()

    assert cli.main(["-v"]) == 0
    assert capsys.readouterr().out.strip() == get_version()


def test_ui_passes_frame_generation_options(monkeypatch) -> None:
    calls = {}

    def fake_run_ui(project: Path, **kwargs) -> None:
        calls["project"] = project
        calls["kwargs"] = kwargs

    monkeypatch.setattr("vided.ui_server.run_ui", fake_run_ui)

    assert (
        cli.main(
            [
                "ui",
                "project-dir",
                "--no-open",
                "--frame-interval",
                "0.5",
                "--thumbnail-width",
                "960",
                "--regenerate-frames",
            ]
        )
        == 0
    )
    assert calls == {
        "project": Path("project-dir"),
        "kwargs": {
            "host": "127.0.0.1",
            "port": 8765,
            "open_browser": False,
            "frame_interval": 0.5,
            "thumbnail_width": 960,
            "regenerate_frames": True,
        },
    }


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
                "vad",
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
    assert options.detector == "vad"
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


def test_trim_can_publish_final_video(monkeypatch, capsys) -> None:
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

    def fake_copy_trimmed_to_final(project: Path, **kwargs) -> Path:
        calls["final_project"] = project
        calls["final_kwargs"] = kwargs
        return Path("project-dir/output/auto-edited.mp4")

    monkeypatch.setattr(cli, "plan_trim", fake_plan_trim)
    monkeypatch.setattr(cli, "run_trim_plan", fake_run_trim_plan)
    monkeypatch.setattr(cli, "copy_trimmed_to_final", fake_copy_trimmed_to_final)

    assert (
        cli.main(
            [
                "trim",
                "project-dir",
                "--final-output",
                "output/auto-edited.mp4",
                "--overwrite",
                "--dry-run",
            ]
        )
        == 0
    )
    assert calls["project"] == Path("project-dir")
    assert calls["kwargs"]["allow_vad_detection"] is False
    assert calls["plan"] is plan
    assert calls["run_kwargs"] == {"overwrite": True, "dry_run": True}
    assert calls["final_project"] == Path("project-dir")
    assert calls["final_kwargs"] == {
        "source": Path("project-dir/work/trimmed.mp4"),
        "output": Path("output/auto-edited.mp4"),
        "overwrite": True,
        "dry_run": True,
    }
    assert "Final video: project-dir/output/auto-edited.mp4" in capsys.readouterr().out


def test_render_contact_sheet_passes_options(monkeypatch) -> None:
    calls = {}

    def fake_render_contact_sheet(project: Path, **kwargs) -> Path:
        calls["project"] = project
        calls["kwargs"] = kwargs
        return project / "output" / "sheet.png"

    monkeypatch.setattr(cli, "render_contact_sheet", fake_render_contact_sheet)

    assert (
        cli.main(
            [
                "render",
                "project-dir",
                "--contact-sheet",
                "--final-video",
                "output/custom-final.mp4",
                "--output",
                "output/sheet.png",
                "--overwrite",
                "--dry-run",
            ]
        )
        == 0
    )
    assert calls["project"] == Path("project-dir")
    assert calls["kwargs"] == {
        "final_video": Path("output/custom-final.mp4"),
        "output": Path("output/sheet.png"),
        "overwrite": True,
        "dry_run": True,
    }


def test_render_contact_sheet_rejects_debug(monkeypatch, capsys) -> None:
    def fake_render_contact_sheet(*args, **kwargs) -> Path:
        raise AssertionError("render_contact_sheet should not be called")

    monkeypatch.setattr(cli, "render_contact_sheet", fake_render_contact_sheet)

    assert cli.main(["render", "project-dir", "--debug", "--contact-sheet"]) == 1
    assert "Use either --debug or --contact-sheet" in capsys.readouterr().err


def test_final_video_requires_contact_sheet(monkeypatch, capsys) -> None:
    def fake_render_project(*args, **kwargs) -> Path:
        raise AssertionError("render_project should not be called")

    monkeypatch.setattr(cli, "render_project", fake_render_project)

    assert cli.main(["render", "project-dir", "--final-video", "output/final.mp4"]) == 1
    assert "--final-video can only be used with --contact-sheet" in capsys.readouterr().err


def test_install_skill_passes_options(monkeypatch, capsys) -> None:
    calls = {}

    def fake_install_skill(agent: str, **kwargs: object) -> SkillInstallResult:
        calls["agent"] = agent
        calls["kwargs"] = kwargs
        return SkillInstallResult(
            path=Path("/tmp/home/.codex/skills/vided/SKILL.md"),
            wrote=False,
            dry_run=True,
        )

    monkeypatch.setattr(cli, "install_skill", fake_install_skill)

    assert cli.main(["install-skill", "--agent", "codex", "--overwrite", "--dry-run"]) == 0
    assert calls == {"agent": "codex", "kwargs": {"overwrite": True, "dry_run": True}}
    assert "Would install codex skill:" in capsys.readouterr().out


def test_install_skill_rejects_invalid_agent() -> None:
    assert cli.main(["install-skill", "--agent", "other"]) == 2
