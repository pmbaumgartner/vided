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

Speech-based trimming with VAD is optional. Install the ONNX Runtime extra when you
need it:

```bash
uv sync --extra vad
```

## Run from this repo

Install dependencies and check the CLI:

```bash
uv sync
uv run vided --help
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
usage: vided [-h] command ...

Simple local video silence speeder and rectangular blur redactor.

positional arguments:
  command
    init      Create a one-video project folder.
    trim      Run the trim renderer on the source video.
    ui        Start the local annotation UI, generating frames if needed.
    render    Render final or debug preview video.
    doctor    Check external tool availability.

options:
  -h, --help  show this help message and exit
```

### `vided init --help`

```text
usage: vided init [-h] [-o OUTPUT_DIR] [--frame-interval FRAME_INTERVAL]
                  [--symlink] [--overwrite]
                  source [project]

positional arguments:
  source                Input video path.
  project               Project folder to create. Defaults to a folder name
                        based on the input video.

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Project folder to create when using the input video
                        shorthand.
  --frame-interval FRAME_INTERVAL
                        Default thumbnail interval.
  --symlink             Symlink instead of copying input video.
  --overwrite           Allow reusing a non-empty folder.
```

### `vided trim --help`

```text
usage: vided trim [-h] [--detector {audio,vad}]
                  [--vad-threshold VAD_THRESHOLD]
                  [--vad-min-speech-ms VAD_MIN_SPEECH_MS]
                  [--vad-min-silence-ms VAD_MIN_SILENCE_MS]
                  [--vad-speech-pad-ms VAD_SPEECH_PAD_MS]
                  [--vad-merge-gap VAD_MERGE_GAP]
                  [--mode {hybrid,speed,cut,keep}] [--margin MARGIN]
                  [--smooth SMOOTH] [--silent-speed SILENT_SPEED]
                  [--mute-silent-audio | --no-mute-silent-audio]
                  [--speed-indicator | --no-speed-indicator]
                  [--speed-indicator-corner {top-left,top-right,bottom-left,bottom-right}]
                  [--speed-indicator-style {dark,light}]
                  [--speed-indicator-min-seconds SPEED_INDICATOR_MIN_SECONDS]
                  [--overwrite] [--dry-run]
                  project

positional arguments:
  project

options:
  -h, --help            show this help message and exit
  --detector {audio,vad}, --engine {audio,vad}
                        Detector used to classify normal-speed sections.
  --vad-threshold VAD_THRESHOLD
  --vad-min-speech-ms VAD_MIN_SPEECH_MS
  --vad-min-silence-ms VAD_MIN_SILENCE_MS
  --vad-speech-pad-ms VAD_SPEECH_PAD_MS
  --vad-merge-gap VAD_MERGE_GAP
  --mode {hybrid,speed,cut,keep}
  --margin MARGIN       Trim margin, e.g. 0.2s or 0.3s,1.0s
  --smooth SMOOTH       Trim smoothing pair, e.g. 0.2s,0.1s
  --silent-speed SILENT_SPEED
                        Speed for silent sections.
  --mute-silent-audio, --no-mute-silent-audio
                        When speed mode is used, chain volume:0 onto silent
                        sections.
  --speed-indicator, --no-speed-indicator
                        Show a small speed label on sped-up silent sections.
  --speed-indicator-corner {top-left,top-right,bottom-left,bottom-right}
  --speed-indicator-style {dark,light}
  --speed-indicator-min-seconds SPEED_INDICATOR_MIN_SECONDS
                        Only show the badge when the sped-up section lasts at
                        least this long after speedup.
  --overwrite
  --dry-run
```

### `vided ui --help`

```text
usage: vided ui [-h] [--host HOST] [--port PORT] [--no-open]
                [--frame-interval FRAME_INTERVAL]
                [--thumbnail-width THUMBNAIL_WIDTH] [--regenerate-frames]
                project

positional arguments:
  project

options:
  -h, --help            show this help message and exit
  --host HOST
  --port PORT
  --no-open             Do not open the browser automatically.
  --frame-interval FRAME_INTERVAL
                        Seconds between thumbnails.
  --thumbnail-width THUMBNAIL_WIDTH
  --regenerate-frames   Regenerate thumbnails before opening the UI.
```

### `vided render --help`

```text
usage: vided render [-h] [--debug] [--contact-sheet]
                    [--final-video FINAL_VIDEO] [--output OUTPUT]
                    [--overwrite] [--dry-run]
                    project

positional arguments:
  project

options:
  -h, --help            show this help message and exit
  --debug               Render visible rectangles instead of blur.
  --contact-sheet       Render a contact sheet from the final video.
  --final-video FINAL_VIDEO
                        Final video to sample when rendering a contact sheet.
  --output OUTPUT
  --overwrite
  --dry-run
```

### `vided doctor --help`

```text
usage: vided doctor [-h]

options:
  -h, --help  show this help message and exit
```

## Technical design

The pipeline is:

```text
original video
  -> audio-level or optional VAD activity detection
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

Install the pre-commit hook:

```bash
uv run pre-commit install
```

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
uv run --extra vad pytest --run-e2e -m e2e
```

Install the Playwright browser once before browser e2e tests:

```bash
uv run playwright install chromium
uv run --extra vad pytest --run-e2e -m browser --browser chromium
```
