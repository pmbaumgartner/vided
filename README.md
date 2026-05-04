# Vided

Vided is a small local tool for editing one screen recording at a time.

It can:

- cut short silent gaps
- speed up longer silent sections
- optionally mute sped-up silent sections
- generate thumbnails
- mark fixed rectangular blur regions in a browser UI
- render a debug preview with visible boxes
- render the final blurred video with `ffmpeg`

Everything is file-based and local. A project folder contains `project.json`,
`redactions.json`, generated thumbnails, generated filtergraphs, and rendered outputs.

## Best fit

Use Vided for mostly static screen recordings where the sensitive area stays in a
predictable part of the screen:

- email addresses
- account IDs
- tokens
- URL bars
- sidebars
- terminal panes

Vided is not a tracker. If the thing you need to hide moves, create multiple
redactions across smaller time ranges.

## Requirements

For video work:

- `ffmpeg`
- `ffprobe`

For local development and source installs:

- Python 3.11 or newer
- `uv`

Speech-based trimming with VAD is included in the core package.

## Run from this repo

Install dependencies and check the CLI:

```bash
uv sync
uv run vided --help
uv run vided --version
uv run vided doctor
```

Run the CLI module directly:

```bash
uv run python -m vided --help
```

Install from PyPI as a tool:

```bash
uv tool install vided
vided --help
```

For one-off use:

```bash
uvx vided --help
```

Install the packaged skill for a coding agent:

```bash
uvx vided install-skill --agent codex
uvx vided install-skill --agent claude
```

## Quick start

Create a project:

```bash
vided init /path/to/original-recording.mp4 --output-dir my-recording-project
```

If you omit `--output-dir`, `init` creates a folder from the input filename, such as
`original-recording`.

Trim silence:

```bash
vided trim my-recording-project
```

Open the annotation UI:

```bash
vided ui my-recording-project
```

If thumbnails are missing, `ui` generates them from `work/trimmed.mp4` before opening
the browser.

In the UI:

1. Click a thumbnail in the bottom filmstrip.
2. Click **Set start**.
3. Drag a rectangle in the large frame view.
4. Click the thumbnail where the blur should end.
5. Click **Add redaction**.
6. Wait for the save status in the top bar.

Render a debug preview first:

```bash
vided render my-recording-project --debug --overwrite
```

The debug output is:

```text
my-recording-project/output/debug-preview.mp4
```

Render the final blurred video:

```bash
vided render my-recording-project --overwrite
```

The final output is:

```text
my-recording-project/output/final.mp4
```

Render a contact sheet from the final video:

```bash
vided render my-recording-project --contact-sheet --overwrite
```

The contact sheet shows sampled frames from `output/final.mp4`. Frames that overlap
redactions get an accent border.

```text
my-recording-project/output/contact-sheet.jpg
```

## Trim behavior

The default trim mode is `hybrid`:

```text
detector: audio
short silent sections: cut
silent sections 1.5s or longer: speed:8,volume:0
normal sections: keep
margin: 0.2s
smooth: 0.2s,0.1s
audio threshold: 0.04
```

Short pauses disappear. Long waits are sped up and muted. Speech stays at normal speed.
The default detector uses ffmpeg-decoded audio levels.
Trimmed outputs contain only the rendered video and audio streams; subtitle and data
streams from the source are omitted so they cannot extend the reported duration.

To use VAD instead:

```bash
vided trim my-recording-project --detector vad --overwrite
```

This creates or refreshes `work/vad.wav` and `work/vad_ranges.json` as needed, then
runs the same ffmpeg trim renderer.

## Project layout

After the full flow, a project looks like this:

```text
my-recording-project/
  project.json
  redactions.json
  input/
    original.mp4
  work/
    trimmed.mp4
    vad.wav
    vad_ranges.json
    filtergraph.txt
    filtergraph.debug.txt
    frames/
      frame_000001.jpg
      frame_000002.jpg
      frames.json
  output/
    debug-preview.mp4
    final.mp4
    contact-sheet.jpg
```

`vad.wav` and `vad_ranges.json` exist only after using VAD.

## Commands

The quick start above is the normal workflow. For other knobs, use command help:

```text
Usage: vided COMMAND

Simple local video silence speeder and rectangular blur redactor.

Commands:
  init: Create a one-video project folder.
  trim: Run the trim renderer on the source video.
  ui: Start the local annotation UI, generating frames if needed.
  render: Render final or debug preview video.
  doctor: Check external tool availability.
  install-skill: Install the packaged agent skill.
  --help, -h: Display this message and exit.
  --version, -v: Display application version.
```

### `vided init --help`

```text
Usage: vided init [OPTIONS] SOURCE

Create a one-video project folder.

Arguments:
  SOURCE: [required]

Parameters:
  --output-dir, -o: Project folder to create. Defaults to a name based on the
  input video.
  --frame-interval: Default thumbnail interval. [default: 1.0]
  --symlink: Symlink instead of copying input video. [default: False]
  --overwrite: Allow reusing a non-empty folder. [default: False]
```

### `vided trim --help`

```text
Usage: vided trim [OPTIONS] PROJECT

Run the trim renderer on the source video.

Arguments:
  PROJECT: [required]

Parameters:
  --detector, --engine: [choices: audio, vad]
  --mode: [choices: hybrid, speed, cut, keep]
  --margin
  --smooth
  --silent-speed
  --mute-silent-audio, --no-mute-silent-audio
  --vad-threshold
  --vad-min-speech-ms
  --vad-min-silence-ms
  --vad-speech-pad-ms
  --vad-merge-gap
  --speed-indicator, --no-speed-indicator
  --speed-indicator-corner: [choices: top-left, top-right, bottom-left,
  bottom-right]
  --speed-indicator-style: [choices: dark, light]
  --speed-indicator-min-seconds
  --overwrite: [default: False]
  --dry-run: [default: False]
```

### `vided ui --help`

```text
Usage: vided ui [OPTIONS] PROJECT

Start the local annotation UI, generating frames if needed.

Arguments:
  PROJECT: [required]

Parameters:
  --host: [default: 127.0.0.1]
  --port: [default: 8765]
  --no-open: Do not open the browser automatically. [default: False]
  --frame-interval: Seconds between thumbnails.
  --thumbnail-width
  --regenerate-frames: Regenerate thumbnails before opening the UI. [default:
  False]
```

### `vided render --help`

```text
Usage: vided render [OPTIONS] PROJECT

Render final or debug preview video.

Arguments:
  PROJECT: [required]

Parameters:
  --debug: Render visible rectangles instead of blur. [default: False]
  --contact-sheet: Render a contact sheet from the final video. [default: False]
  --final-video: Final video to sample when rendering a contact sheet.
  --output
  --overwrite: [default: False]
  --dry-run: [default: False]
```

### `vided doctor --help`

```text
Usage: vided doctor

Check external tool availability.
```

### `vided install-skill --help`

```text
Usage: vided install-skill --agent LITERAL[CODEX, CLAUDE] [OPTIONS]

Install the packaged agent skill.

Parameters:
  --agent: Personal skill directory to install into. [choices: codex, claude]
  [required]
  --overwrite: [default: False]
  --dry-run: [default: False]
```

## Technical design

The pipeline is:

```text
original video
  -> audio-level or VAD activity detection
  -> ffmpeg-backed speed/mute trim pass
  -> work/trimmed.mp4
  -> ffmpeg thumbnail generation
  -> browser rectangle annotations
  -> redactions.json
  -> ffmpeg debug preview
  -> ffmpeg final blurred render
```

Redactions are created against the trimmed video. That keeps all redaction timestamps
in the same timeline as the debug and final renders.

The UI stores rectangles in real video pixels, not thumbnail pixels.

## Redaction data

The browser writes `redactions.json`. Each redaction stores selected times, buffered
effective times, a video-pixel rectangle, and a style:

```json
{
  "id": "redaction_001",
  "selected_start_seconds": 10.0,
  "selected_end_seconds": 15.0,
  "buffer_pre_seconds": 0.5,
  "buffer_post_seconds": 0.5,
  "effective_start_seconds": 9.5,
  "effective_end_seconds": 15.5,
  "rect": {
    "x": 1000,
    "y": 42,
    "w": 420,
    "h": 90
  },
  "style": {
    "type": "blur",
    "filter": "boxblur",
    "luma_radius": 18,
    "luma_power": 3
  }
}
```

## Rendering

For each blur redaction, the renderer generates an ffmpeg filtergraph that:

1. splits the video stream
2. crops the target rectangle from a copy
3. applies `boxblur` to the crop
4. overlays the blurred crop back onto the base video during the redaction time range

Generated filtergraphs are written to:

```text
work/filtergraph.txt
work/filtergraph.debug.txt
```

The final render must re-encode video because blur is a video filter. Defaults:

```json
{
  "video_codec": "libx264",
  "crf": 16,
  "preset": "medium",
  "pixel_format": "yuv420p",
  "audio_codec": "copy"
}
```

Lower CRF means higher quality and larger files. Try CRF `12` or `14` for very high
quality, or `18` to `23` for smaller files.

Audio is stream-copied during the redaction render. Silence speeding and muting happen
during the trim pass.

## Limitations

- Fixed rectangles only. There are no keyframed rectangles or object tracking.
- Annotations happen on the trimmed video. Changing trim settings later means
  regenerating thumbnails and reviewing redactions.
- The UI uses frame thumbnails plus debug render. It does not include a video preview.
- Frame times are based on the thumbnail interval. This is fine for broad redactions
  with buffers, but not frame-perfect editing.
- Rotation metadata and unusual pixel aspect ratios are not normalized.
- Blur is implemented in the UI. Solid redaction is partially supported by the renderer
  if you hand-edit `style.type` to `solid`.
- The local UI server binds to `127.0.0.1` by default. Do not expose it to the public
  internet.

## Development

Run tests:

```bash
uv run pytest
```

Format, lint, and type-check:

```bash
uv run ruff format src tests
uv run ruff check src tests
uv run ty check src tests
```

Install the `prek`-managed pre-commit hook:

```bash
uv run prek install
```

Verify the configured hooks:

```bash
uv run prek run --stage pre-commit --dry-run
uv run prek run --stage pre-commit
```

The hooks run Ruff formatting, Ruff lint checks, and the release-version bump guard.

Every commit with package source or release metadata changes must bump the package
version with zerover. This includes staged changes under `src/` and published package
metadata in `pyproject.toml`, such as runtime dependencies, entry points, Python
version support, or build configuration. Tests, workflows, docs, scripts, dev
dependencies, and `uv.lock`-only changes do not require a bump.

```bash
uv version --bump patch
# or, for larger changes while still staying on major zero:
uv version --bump minor
git add pyproject.toml uv.lock
```

After committing, add the matching tag:

```bash
version="$(uv version --short)"
git tag -a "v$version" -m "v$version"
git push origin HEAD --tags
```

Publishing runs from `.github/workflows/publish.yml` when a `v*` tag is pushed. In
PyPI, configure a trusted publisher for:

- owner: `pmbaumgartner`
- repository: `vided`
- workflow: `publish.yml`
- environment: `pypi`

### Realistic media fixtures

The repo includes two Git LFS-tracked public-domain NASA fixtures:

- `tests/fixtures/media/realistic-speech-gaps.mp4`
- `tests/fixtures/media/realistic-speech-gaps-short.mp4`

Use them for realistic trim, VAD, frame generation, render, and UI smoke tests. Source
and license notes live beside each fixture as `*.LICENSE.md`.

Run fixture e2e tests:

```bash
uv run pytest --run-e2e -m e2e
```

Install the Playwright browser once before browser e2e tests:

```bash
uv run playwright install chromium
uv run pytest --run-e2e -m browser --browser chromium
```
