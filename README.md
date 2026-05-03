# Vided

A small local tool for one-video screen-recording edits:

- cut short silent gaps and speed up longer silent sections
- optionally mute those sped-up silent sections
- generate one thumbnail every N seconds
- draw fixed rectangular blur regions in a browser UI
- render a debug preview with visible boxes
- render the final blurred video with `ffmpeg`

The design is intentionally file-based. Each project has a `project.json`, a `redactions.json`, generated thumbnails, generated filtergraphs, and rendered outputs.

## What this is best for

This is meant for mostly static screen recordings where the sensitive area stays in a predictable part of the screen, such as an email address, account ID, token, URL bar, sidebar, or terminal pane.

It is not a tracker. If the thing you need to hide moves around, create multiple redactions across smaller time ranges.

## Requirements

You need these available on your `PATH`:

- `ffmpeg`
- `ffprobe`
- `uv`

The project requires Python 3.11 or newer but does not pin a specific interpreter version.

Speech-based trimming is optional. To use the Silero VAD detector locally, install the
ONNX Runtime extra:

```bash
uv sync --extra vad
```

## Install

After the package is published to PyPI:

```bash
uv tool install vided
vided --help
```

For one-off use without installing:

```bash
uvx vided --help
```

For local development from this folder:

```bash
uv sync
uv run vided --help
uv run vided doctor
```

## End-to-end usage

Create a one-video project:

```bash
vided init /path/to/original-recording.mp4 --output-dir my-recording-project
```

If you omit the output directory, `init` creates one from the input filename, such as
`original-recording`.

Run the silence trim pass:

```bash
vided trim my-recording-project
```

The default trim behavior is:

```text
short silent sections: cut
silent sections 1.5s or longer: speed:8,volume:0
normal sections: nil
margin: 0.2s
smooth: 0.2s,0.1s
audio threshold: 0.04
```

So short pauses between speaking sections disappear, long waiting periods are sped up,
and sped-up silent audio is muted. Speech sections stay at normal speed.
The speech/silence map is built from ffmpeg-decoded audio levels, then the final
trimmed video is rendered with ffmpeg.

For speech-only activity detection, run Silero VAD first or let `trim` create its
range file on demand:

```bash
vided vad my-recording-project
vided trim my-recording-project --detector silero --overwrite
```

This writes `work/vad.wav` and `work/vad_ranges.json`, then uses a bundled 16 kHz
Silero ONNX model with the same ffmpeg trim renderer as the default audio-level detector.

Generate thumbnails from the trimmed video:

```bash
vided frames my-recording-project
```

Open the annotation UI:

```bash
vided ui my-recording-project
```

In the UI:

1. Click a thumbnail in the bottom filmstrip.
2. Click **Set start**.
3. Drag a rectangle in the large frame view.
4. Click the thumbnail where the blur should end.
5. Click **Add redaction**.
6. Watch the save status in the top bar; failed autosaves show a retry button.

Render a debug preview first:

```bash
vided render my-recording-project --debug --overwrite
```

The debug output goes here:

```text
my-recording-project/output/debug-preview.mp4
```

Render the final blurred video:

```bash
vided render my-recording-project --overwrite
```

The final output goes here:

```text
my-recording-project/output/final.mp4
```

## Project folder layout

After running the full flow, a project looks like this:

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
```

## Technical design

The core pipeline keeps every step file-based and local:

```text
original video
  -> audio-level or optional Silero VAD activity detection
  -> ffmpeg-backed speed/mute trim pass
  -> work/trimmed.mp4
  -> ffmpeg thumbnail generation
  -> browser rectangle annotations
  -> redactions.json
  -> ffmpeg debug preview
  -> ffmpeg final blurred render
```

The main simplification is that redactions are created against the trimmed video. That keeps all redaction timestamps in the same timeline as the debug and final renders.

The default `audio` detector classifies activity from ffmpeg-decoded audio levels. The optional `silero` detector uses the bundled 16 kHz Silero ONNX model through ONNX Runtime and writes `work/vad_ranges.json` for inspection. Both detectors feed the same ffmpeg trim renderer.

The annotation UI has a horizontally scrolling filmstrip and a larger canvas view. The saved rectangle is converted to real video pixels before writing `redactions.json`.

Debug rendering uses the same redaction timing and coordinates as final rendering, but draws visible boxes instead of blur so you can review placement before producing `output/final.mp4`.

## CLI commands

Check dependencies:

```bash
vided doctor
```

Create a project:

```bash
vided init input.mp4
```

This creates a folder named from the input video, such as `input`.

Choose a project folder name:

```bash
vided init input.mp4 project-dir
vided init input.mp4 --output-dir project-dir
```

Symlink the original instead of copying it:

```bash
vided init input.mp4 project-dir --symlink
```

Speed silent sections at a different rate:

```bash
vided trim project-dir --silent-speed 12 --overwrite
```

Show a small speed label on sped-up silent sections:

```bash
vided trim project-dir --speed-indicator --speed-indicator-corner top-right --overwrite
```

The badge includes a fast-forward icon, scales with the video resolution, and appears
only when the sped-up section lasts at least one second in the output. To show it on
shorter sped-up sections:

```bash
vided trim project-dir --speed-indicator --speed-indicator-min-seconds 0.5 --overwrite
```

Keep silent-section audio instead of muting it:

```bash
vided trim project-dir --no-mute-silent-audio --overwrite
```

Cut silence instead of speeding it up:

```bash
vided trim project-dir --mode cut --overwrite
```

Use the older behavior where every silent section is sped up:

```bash
vided trim project-dir --mode speed --overwrite
```

Use Silero VAD instead of audio levels:

```bash
vided trim project-dir --detector silero --overwrite
```

Inspect or refresh Silero VAD ranges without trimming:

```bash
vided vad project-dir
```

Tune trim smoothing:

```bash
vided trim project-dir --smooth 0.2s,0.1s --overwrite
```

Generate denser thumbnails:

```bash
vided frames project-dir --interval 0.5 --overwrite
```

Use larger thumbnails for more precise rectangle placement:

```bash
vided frames project-dir --thumbnail-width 960 --overwrite
```

Print the trim command that would be run:

```bash
vided trim-command project-dir
```

Validate `redactions.json`:

```bash
vided validate project-dir
```

Render to a custom path:

```bash
vided render project-dir --output output/my-final.mp4 --overwrite
```

## Redaction data model

The browser writes `redactions.json`. Each redaction has selected times, effective times, a video-pixel rectangle, and a style.

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

The rectangle is stored in real video pixels, not thumbnail pixels. The UI converts from the displayed thumbnail coordinates to video coordinates.

## Rendering approach

For each blur redaction, the renderer generates an ffmpeg filtergraph that:

1. splits the video stream
2. crops the target rectangle from a copy
3. applies `boxblur` to the crop
4. overlays the blurred crop back onto the base video during the redaction time range

The generated filtergraph is written to:

```text
work/filtergraph.txt
```

The debug graph is written to:

```text
work/filtergraph.debug.txt
```

This makes ffmpeg failures much easier to inspect.

## Output quality

The final render must re-encode the video because blur is a video filter. The default render settings are intentionally high quality:

```json
{
  "video_codec": "libx264",
  "crf": 16,
  "preset": "medium",
  "pixel_format": "yuv420p",
  "audio_codec": "copy"
}
```

Lower CRF means higher quality and larger files. For very high quality, edit `project.json` and try CRF `12` or `14`. For smaller files, try CRF `18` to `23`.

Audio is stream-copied during the redaction render. The silence-speeding and silent-section muting happen during the trim pass.

## Current limitations

Fixed rectangles only. There are no keyframed rectangles and no object tracking.

Annotations happen on the trimmed video. This avoids timestamp-mapping complexity, but it means changing the trim settings later requires regenerating thumbnails and reviewing redactions.

The UI does not include a video preview. It uses frame thumbnails plus debug render.

The frame times are approximate based on the configured thumbnail interval. This is fine for broad redactions with buffers, but not frame-perfect editing.

Rotation metadata and unusual pixel aspect ratios are not normalized in this skeleton. For normal screen recordings this is usually fine.

Blur is implemented. Solid black redaction is partially supported by the renderer if you hand-edit `style.type` to `solid`, but the UI only creates blur redactions.

The local UI server is intentionally simple and binds to `127.0.0.1` by default. Do not expose it to the public internet.

Open future improvements include keyframed rectangles for moving targets, a video scrubber preview, frame-accurate thumbnail timestamp metadata, solid-fill redactions from the UI, better handling for rotated videos and non-standard pixel aspect ratios, and optional audio redaction ranges.

## Development

Run tests:

```bash
uv run pytest
```

Run linting:

```bash
uv run ruff check
```

### Realistic media fixture

The repo includes `tests/fixtures/media/realistic-speech-gaps.mp4`, a 90-second clip derived from NASA's public-domain `Universe (1976).webm`. It is tracked with Git LFS and has source/license notes in `tests/fixtures/media/realistic-speech-gaps.LICENSE.md`.

Use this fixture for realistic trim, VAD, frame generation, render, and UI smoke tests. It has real narration plus pauses, so it is more useful than synthetic audio for checking editing behavior.

For faster e2e tests, use `tests/fixtures/media/realistic-speech-gaps-short.mp4`, a 20-second excerpt from the same source with several speech ranges and pauses. Its source/license note is `tests/fixtures/media/realistic-speech-gaps-short.LICENSE.md`.

Run the fixture e2e tests explicitly:

```bash
uv run --extra vad pytest --run-e2e -m e2e
```

Install the Playwright browser once before running browser e2e tests:

```bash
uv run playwright install chromium
uv run --extra vad pytest --run-e2e -m browser --browser chromium
```

Run the CLI directly from source:

```bash
uv run python -m vided --help
```
