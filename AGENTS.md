This project is in active development, do not be concerned with backwards compatibility or migrations.

## Linting

- `ty check <files>`
- `ruff format <files>`
- `ruff check <files>`

## Test Fixtures

- `tests/fixtures/media/realistic-speech-gaps.mp4` is a Git LFS-tracked 90-second public-domain NASA clip derived from `Universe (1976).webm`.
- Use it for realistic trim, VAD, frame generation, render, and UI smoke tests. It has real narration plus pauses.
- Source and license notes live in `tests/fixtures/media/realistic-speech-gaps.LICENSE.md`.
