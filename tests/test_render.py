from __future__ import annotations

from pathlib import Path

from helpers import basic_project_at
from vided.render import copy_trimmed_to_final


def test_copy_trimmed_to_final_writes_default_final_output(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")

    output = copy_trimmed_to_final(project)

    assert output == project / "output" / "final.mp4"
    assert output.read_bytes() == b"trimmed video"


def test_copy_trimmed_to_final_respects_custom_output(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")

    output = copy_trimmed_to_final(project, output=Path("output/auto-edited.mp4"))

    assert output == project / "output" / "auto-edited.mp4"
    assert output.read_bytes() == b"trimmed video"


def test_copy_trimmed_to_final_refuses_existing_output_without_overwrite(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root
    trimmed = project / "work" / "trimmed.mp4"
    trimmed.write_bytes(b"trimmed video")
    output = project / "output" / "final.mp4"
    output.parent.mkdir()
    output.write_bytes(b"existing")

    try:
        copy_trimmed_to_final(project)
    except FileExistsError as exc:
        assert "Use --overwrite" in str(exc)
    else:
        raise AssertionError("existing final output should fail without overwrite")


def test_copy_trimmed_to_final_dry_run_does_not_require_trimmed_video(tmp_path) -> None:
    project = basic_project_at(tmp_path / "project").root

    output = copy_trimmed_to_final(project, dry_run=True)

    assert output == project / "output" / "final.mp4"
    assert not output.exists()
