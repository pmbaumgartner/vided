# Vided

Vided is a small local tool for making screen recordings shorter and safer to
share.

It trims dead air, speeds up longer pauses, and lets you blur fixed rectangular
areas like emails, account IDs, tokens, URL bars, sidebars, or terminal panes. It
runs locally with `ffmpeg`; your video does not leave your machine.

## Example

This is the 90-second public-domain NASA fixture in this repo. VAD trim keeps
speech at normal speed and removes or speeds up the gaps, producing a
61.1-second output.

**Input, 90.0s**

https://github.com/user-attachments/assets/24b476e4-72d3-4bad-843a-3c801cc3adcb

**VAD trim, 61.1s**

https://github.com/user-attachments/assets/c0ccba07-e2be-45b0-a6a9-d4a7d57f3f28

## Install

Requirements:

- `ffmpeg`
- `ffprobe`
- Python 3.11 or newer

Run once with `uvx`:

```bash
uvx vided --help
```

Or install as a tool:

```bash
uv tool install vided
vided doctor
```

From this repo:

```bash
uv sync
uv run vided doctor
```

## Quick Start

Create a project:

```bash
vided init /path/to/recording.mp4 --output-dir my-video
```

Trim silence and write the result directly to `output/final.mp4`:

```bash
vided trim my-video --detector vad --final --overwrite
```

For redaction, open the local browser UI:

```bash
vided ui my-video
```

In the UI:

1. Click a thumbnail where the redaction starts.
2. Click **Set start**.
3. Draw the rectangle to blur.
4. Click a thumbnail where it ends.
5. Click **Add redaction**.

Render a visible-box debug preview:

```bash
vided render my-video --debug --overwrite
```

Render the final blurred video:

```bash
vided render my-video --overwrite
```

## Common Tasks

Trim with the default audio-level detector:

```bash
vided trim my-video --final --overwrite
```

Trim with speech-aware VAD:

```bash
vided trim my-video --detector vad --final --overwrite
```

Preview an audio preset on the longest detected speech/sound segment:

```bash
vided audio-preview my-video --audio-preset voice-safe --overwrite
```

Render with an audio preset:

```bash
vided render my-video --audio-preset voice-safe --overwrite
```

Render a contact sheet from the final video:

```bash
vided render my-video --contact-sheet --overwrite
```

Install the packaged coding-agent skill:

```bash
vided install-skill --agent codex
vided install-skill --agent claude
```

## Audio Presets

Audio presets are opt-in. By default, Vided copies audio without filtering.

```text
none        copy audio unchanged
level       normalize speech to a conservative -18 LUFS target
voice-safe  gentle voice cleanup plus the same conservative loudness target
```

List the current presets:

```bash
vided audio-presets
```

Choose your own preview snippet:

```bash
vided audio-preview my-video --audio-preset level --start 60 --duration 15 --overwrite
```

## More Examples

These examples use `tests/fixtures/media/realistic-speech-gaps.mp4`. The `none`
audio preset preview is omitted because it is unchanged audio.

Regenerate them locally:

```bash
scripts/generate_example_media.sh
```

Regenerate and upload release assets:

```bash
scripts/generate_example_media.sh --upload
```

Release assets are stored at
https://github.com/pmbaumgartner/vided/releases/tag/examples.

**Audio detector trim, 83.1s**

https://github.com/user-attachments/assets/b3fa0e0c-a767-4ca6-a7eb-49278230bea1

**Audio preset preview: level, 12.5s**

https://github.com/user-attachments/assets/965bb188-f499-4c42-924c-1755b85d1a81

**Audio preset preview: voice-safe, 12.5s**

https://github.com/user-attachments/assets/388c075f-d94b-4cf2-bab8-cff070fc38b1

## How Trim Works

The default trim mode is `hybrid`:

- short silent sections are cut
- silent sections 1.5 seconds or longer are sped up 8x and muted
- speech/sound stays at normal speed
- default margin is 0.2 seconds

The default detector uses ffmpeg-decoded audio levels. Use VAD for more
speech-aware trimming:

```bash
vided trim my-video --detector vad --overwrite
```

Trimmed outputs contain only rendered video and audio streams. Subtitle streams,
data streams, and chapters are omitted so they cannot extend the reported
duration.

## Project Files

Vided is file-based. A project keeps the original input, trim output, generated
frames, redaction data, and rendered outputs together:

```text
my-video/
  project.json
  redactions.json
  input/original.mp4
  work/trimmed.mp4
  work/frames/
  output/debug-preview.mp4
  output/final.mp4
  output/contact-sheet.jpg
```

With VAD, Vided also writes `work/vad.wav` and `work/vad_ranges.json`.

Redactions are created against the trimmed video, so redaction timestamps match
debug and final renders.

## Commands

Use command help for details:

```bash
vided --help
vided init --help
vided trim --help
vided ui --help
vided render --help
vided audio-preview --help
```

Main commands:

```text
init            create a one-video project
trim            remove or speed up silence
ui              open the local redaction UI
render          render debug, final, or contact sheet output
audio-presets   list audio presets
audio-preview   render a short audio preset preview
doctor          check ffmpeg/ffprobe availability
install-skill   install the packaged coding-agent skill
```

## Limitations

- Rectangles are fixed. There is no object tracking.
- Changing trim settings after redacting means regenerating thumbnails and
  reviewing redactions.
- The UI uses frame thumbnails plus debug render. It is not a full video editor.
- Frame times follow the thumbnail interval, so this is not for frame-perfect cuts.
- Rotation metadata and unusual pixel aspect ratios are not normalized.
- The local UI server binds to `127.0.0.1` by default. Do not expose it publicly.

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

Install and run pre-commit hooks:

```bash
uv run prek install
uv run prek run --stage pre-commit
```

Run fixture e2e tests:

```bash
uv run pytest --run-e2e -m e2e
```

Install the Playwright browser before browser e2e tests:

```bash
uv run playwright install chromium
uv run pytest --run-e2e -m browser --browser chromium
```

The repo includes two Git LFS-tracked public-domain NASA fixtures:

- `tests/fixtures/media/realistic-speech-gaps.mp4`
- `tests/fixtures/media/realistic-speech-gaps-short.mp4`

Source and license notes live beside each fixture as `*.LICENSE.md`.

## Release Notes

Every commit with package source or release metadata changes must bump the
package version with zerover. Tests, workflows, docs, scripts, dev dependencies,
and `uv.lock`-only changes do not require a bump.

```bash
uv version --bump patch
git add pyproject.toml uv.lock
```

After committing, add the matching tag:

```bash
version="$(uv version --short)"
git tag -a "v$version" -m "v$version"
git push origin HEAD --tags
```

Publishing runs from `.github/workflows/publish.yml` when a `v*` tag is pushed.
