This project is in active development, do not be concerned with backwards compatibility or migrations.

## Linting

- `ty check <files>`
- `ruff format <files>`
- `ruff check <files>`

## Documentation

Ensure `README.md` is updated when there are any core functionality changes if the change is relevanat to examples there. Keep this brief.

Ensure the skill at `src/vided/skills/vided/SKILL.md` is updated when there are core functionality changes.

## Test Fixtures

- `tests/fixtures/media/realistic-speech-gaps.mp4` is a Git LFS-tracked 90-second public-domain NASA clip derived from `Universe (1976).webm`.
- `tests/fixtures/media/realistic-speech-gaps-short.mp4` is a 20-second excerpt for faster e2e tests.
- Use it for realistic trim, VAD, frame generation, render, and UI smoke tests. It has real narration plus pauses.
- Source and license notes live beside each fixture as `*.LICENSE.md`.
