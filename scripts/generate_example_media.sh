#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
upload=false

if [[ "${1:-}" == "--upload" ]]; then
  upload=true
  shift
fi

fixture="${1:-"$repo_root/tests/fixtures/media/realistic-speech-gaps.mp4"}"
output_dir="${2:-"$repo_root/.scratch/example-media"}"
presets=(none level voice-safe)
release_tag="${VIDED_EXAMPLE_RELEASE_TAG:-examples}"

export UV_CACHE_DIR="${UV_CACHE_DIR:-"$repo_root/.scratch/uv-cache"}"

if [[ ! -f "$fixture" ]]; then
  echo "Fixture not found: $fixture" >&2
  exit 1
fi

mkdir -p "$output_dir/projects"

input_output="$output_dir/realistic-speech-gaps-input.mp4"
audio_project="$output_dir/projects/audio-trim"
vad_project="$output_dir/projects/vad-trim"

cp -f "$fixture" "$input_output"

uv run vided init "$fixture" --output-dir "$audio_project" --symlink --overwrite
uv run vided trim "$audio_project" --detector audio --overwrite
cp -f "$audio_project/work/trimmed.mp4" "$output_dir/realistic-speech-gaps-trim-audio.mp4"

uv run vided init "$fixture" --output-dir "$vad_project" --symlink --overwrite
uv run vided trim "$vad_project" --detector vad --overwrite
cp -f "$vad_project/work/trimmed.mp4" "$output_dir/realistic-speech-gaps-trim-vad.mp4"

for preset in "${presets[@]}"; do
  uv run vided audio-preview \
    "$vad_project" \
    --audio-preset "$preset" \
    --output "$output_dir/realistic-speech-gaps-preview-$preset.mp4" \
    --overwrite
done

echo "Generated example media:"
find "$output_dir" -maxdepth 1 -type f -name 'realistic-speech-gaps-*.mp4' -print | sort

if [[ "$upload" == true ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI is required for --upload." >&2
    exit 1
  fi

  if ! gh release view "$release_tag" >/dev/null 2>&1; then
    gh release create "$release_tag" \
      --title "Example media" \
      --notes "Generated example media for README comparisons." \
      --latest=false
  fi

  gh release upload "$release_tag" "$output_dir"/realistic-speech-gaps-*.mp4 --clobber
fi
