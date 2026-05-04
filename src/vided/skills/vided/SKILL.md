---
name: vided
description: Use when working with vided, a local CLI for speeding up silent video sections, annotating rectangular blur redactions, rendering final videos, audio preset previews, and producing contact sheets.
---

# Vided

Vided is a local command-line tool for turning one source video into a project folder, speeding up
silent sections, adding rectangular blur redactions through a browser UI, and rendering final
output with optional audio presets. Use `uvx` so the tool can run without a project-local install.

Start with command help when options matter:

```bash
uvx vided --help
uvx vided <command> --help
```

## Standard Workflow

1. Check local dependencies when diagnosing setup or ffmpeg problems:

```bash
uvx vided doctor
```

2. Create a project from the original video. Use an explicit output directory when the user names
   one; otherwise vided derives a project folder from the input filename.

```bash
uvx vided init /path/to/input.mp4 --output-dir project-dir
```

3. Trim silence. Use `--overwrite` when rerunning trim so stale `work/trimmed.mp4` is
   replaced. Trimmed outputs contain only rendered video and audio streams, with source
   subtitle streams, data streams, and chapters omitted.

```bash
uvx vided trim project-dir --overwrite
```

4. Open the annotation UI to review frames and draw rectangular redaction regions. If thumbnails are
   missing, the UI command generates them from the trimmed video.

```bash
uvx vided ui project-dir
```

5. Render the final video after trimming and redactions are ready.

```bash
uvx vided render project-dir --overwrite
```

6. Use a debug preview or contact sheet when reviewing redaction placement.

```bash
uvx vided render project-dir --debug --overwrite
uvx vided render project-dir --contact-sheet --overwrite
```

## Useful Variations

Use VAD-based trimming when simple audio-level trimming is not good enough:

```bash
uvx vided trim project-dir --detector vad --overwrite
```

When the user only needs automatic edits and does not need redactions or the UI, publish the trimmed
video directly as the final artifact:

```bash
uvx vided trim project-dir --final --overwrite
```

Tune UI frame generation when the user needs denser or wider thumbnails:

```bash
uvx vided ui project-dir --frame-interval 0.5 --thumbnail-width 960 --regenerate-frames
```

Render to a specific output path when the user asks for a named artifact:

```bash
uvx vided render project-dir --output output/custom-final.mp4 --overwrite
```

Preview a small audio preset before rendering. Without `--start`, vided chooses the longest
normal-speed unmuted segment from the trim timeline and previews up to 15 seconds:

```bash
uvx vided audio-preview project-dir --audio-preset voice-safe --overwrite
uvx vided audio-preview project-dir --audio-preset level --start 60 --duration 15 --overwrite
```

Available presets are intentionally small: `none` copies audio unchanged, `level` normalizes speech
to a conservative target, and `voice-safe` adds gentle voice cleanup before the same loudness target.
Use `uvx vided audio-presets` for the current list.

Render with an audio preset only after previewing when audio quality matters:

```bash
uvx vided render project-dir --audio-preset voice-safe --overwrite
```

## Agent Guidance

- Prefer the README and `uvx vided <command> --help` over guessing flags or file layout.
- Do not edit generated media by hand. Use vided commands to create projects, trim, review, and
  render.
- Preserve the project directory as the source of truth: input media, work files, redaction JSON,
  final video, and contact sheets are all organized under that project.
- When reporting next steps to a user, include exact commands and paths.
