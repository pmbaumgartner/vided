from __future__ import annotations

import array
from importlib import resources
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .ffmpeg import VideoInfo, ensure_tool, probe_media, run_command
from .project import load_project, paths, read_json, write_json
from .time_ranges import (
    TimeRange,
    complement_ranges,
    merge_close_ranges,
    sort_and_clamp_ranges,
    union_ranges,
)

VAD_AUDIO_FILE = "vad.wav"
VAD_RANGES_FILE = "vad_ranges.json"
VAD_MODEL_RESOURCE = "silero_vad_16k_op15.onnx"
VAD_SAMPLE_RATE = 16000
VAD_CHUNK_SAMPLES = 512
VAD_CONTEXT_SAMPLES = 64


@dataclass(frozen=True)
class VadSettings:
    threshold: float = 0.5
    min_speech_duration_ms: int = 250
    min_silence_duration_ms: int = 300
    speech_pad_ms: int = 150
    merge_speech_gap_seconds: float = 0.25
    manual_keep_ranges: tuple[TimeRange, ...] = ()

    def detector_settings_dict(self) -> dict[str, float | int]:
        return {
            "threshold": self.threshold,
            "min_speech_duration_ms": self.min_speech_duration_ms,
            "min_silence_duration_ms": self.min_silence_duration_ms,
            "speech_pad_ms": self.speech_pad_ms,
            "merge_speech_gap_seconds": self.merge_speech_gap_seconds,
        }


def normalize_detector(value: str | None) -> str:
    detector = (value or "audio").strip().lower()
    if detector in {"audio", "level", "levels"}:
        return "audio"
    if detector in {"silero", "vad", "silero-vad"}:
        return "silero"
    raise ValueError("trim detector must be one of: audio, silero")


def parse_manual_keep_ranges(raw: Any) -> tuple[TimeRange, ...]:
    if raw in (None, ""):
        return ()
    if not isinstance(raw, list):
        raise ValueError("manual_keep_ranges must be a list")

    ranges: list[TimeRange] = []
    for item in raw:
        if isinstance(item, dict):
            start = item.get("start")
            end = item.get("end")
        elif isinstance(item, list | tuple) and len(item) == 2:
            start, end = item
        else:
            raise ValueError("manual keep ranges must be objects with start/end or two-item lists")

        parsed = TimeRange(start=float(start), end=float(end))
        if parsed.end <= parsed.start:
            raise ValueError("manual keep range end must be greater than start")
        ranges.append(parsed)
    return tuple(ranges)


def vad_settings_from_trim_config(
    trim_cfg: dict[str, Any],
    *,
    threshold: float | None = None,
    min_speech_duration_ms: int | None = None,
    min_silence_duration_ms: int | None = None,
    speech_pad_ms: int | None = None,
    merge_speech_gap_seconds: float | None = None,
) -> VadSettings:
    vad_cfg: dict[str, Any] = {}
    if isinstance(trim_cfg.get("vad"), dict):
        vad_cfg.update(trim_cfg["vad"])
    if isinstance(trim_cfg.get("silero"), dict):
        vad_cfg.update(trim_cfg["silero"])

    settings = VadSettings(
        threshold=float(threshold if threshold is not None else vad_cfg.get("threshold", 0.5)),
        min_speech_duration_ms=int(
            min_speech_duration_ms
            if min_speech_duration_ms is not None
            else vad_cfg.get("min_speech_duration_ms", 250)
        ),
        min_silence_duration_ms=int(
            min_silence_duration_ms
            if min_silence_duration_ms is not None
            else vad_cfg.get("min_silence_duration_ms", 300)
        ),
        speech_pad_ms=int(
            speech_pad_ms if speech_pad_ms is not None else vad_cfg.get("speech_pad_ms", 150)
        ),
        merge_speech_gap_seconds=float(
            merge_speech_gap_seconds
            if merge_speech_gap_seconds is not None
            else vad_cfg.get("merge_speech_gap_seconds", 0.25)
        ),
        manual_keep_ranges=parse_manual_keep_ranges(vad_cfg.get("manual_keep_ranges", [])),
    )
    _validate_vad_settings(settings)
    return settings


def build_vad_audio_command(source: Path, output: Path) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        str(VAD_SAMPLE_RATE),
        "-f",
        "wav",
        str(output),
    ]


def extract_vad_audio(source: Path, output: Path) -> Path:
    ensure_tool("ffmpeg")
    output.parent.mkdir(parents=True, exist_ok=True)
    run_command(build_vad_audio_command(source, output))
    return output


def detect_speech_ranges(audio_path: Path, settings: VadSettings) -> list[TimeRange]:
    try:
        import numpy as np
        import onnxruntime
    except ImportError as exc:
        raise ValueError(
            "Silero VAD ONNX support is not installed. Install it with `uv sync --extra vad`."
        ) from exc

    samples = read_wav_16k_mono_float32(audio_path, np_module=np)
    model = SileroOnnxVadModel(
        model_path=default_onnx_model_path(),
        onnxruntime_module=onnxruntime,
        np_module=np,
    )
    return speech_ranges_from_probabilities(samples, model=model, settings=settings)


def default_onnx_model_path() -> Path:
    return Path(str(resources.files("vided.data").joinpath(VAD_MODEL_RESOURCE)))


class SileroOnnxVadModel:
    def __init__(self, *, model_path: Path, onnxruntime_module, np_module) -> None:
        self._np = np_module
        options = onnxruntime_module.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        available = onnxruntime_module.get_available_providers()
        self._session = onnxruntime_module.InferenceSession(
            str(model_path),
            providers=providers if "CPUExecutionProvider" in available else None,
            sess_options=options,
        )
        self.reset_states()

    def reset_states(self) -> None:
        self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)
        self._context = self._np.zeros((1, VAD_CONTEXT_SAMPLES), dtype=self._np.float32)

    def __call__(self, chunk) -> float:
        if chunk.shape[-1] != VAD_CHUNK_SAMPLES:
            raise ValueError(f"Expected {VAD_CHUNK_SAMPLES} samples, got {chunk.shape[-1]}")

        chunk = chunk.reshape(1, -1).astype(self._np.float32, copy=False)
        model_input = self._np.concatenate([self._context, chunk], axis=1)
        output, state = self._session.run(
            None,
            {
                "input": model_input,
                "state": self._state,
                "sr": self._np.array(VAD_SAMPLE_RATE, dtype=self._np.int64),
            },
        )
        self._state = state
        self._context = model_input[:, -VAD_CONTEXT_SAMPLES:]
        return float(output.reshape(-1)[0])


class VadProbabilityModel(Protocol):
    _np: Any

    def reset_states(self) -> None: ...

    def __call__(self, chunk: Any) -> float: ...


def read_wav_16k_mono_float32(audio_path: Path, *, np_module):
    with wave.open(str(audio_path), "rb") as audio:
        channels = audio.getnchannels()
        sample_width = audio.getsampwidth()
        sample_rate = audio.getframerate()
        frame_count = audio.getnframes()
        raw = audio.readframes(frame_count)

    if sample_rate != VAD_SAMPLE_RATE:
        raise ValueError(f"Expected {VAD_SAMPLE_RATE} Hz VAD audio, got {sample_rate}")
    if channels != 1:
        raise ValueError(f"Expected mono VAD audio, got {channels} channels")
    if sample_width != 2:
        raise ValueError(f"Expected 16-bit PCM VAD audio, got {sample_width * 8}-bit samples")

    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if sys.byteorder != "little":
        samples.byteswap()
    values = [max(-32768, min(32767, sample)) / 32768.0 for sample in samples]
    return np_module.asarray(values, dtype=np_module.float32)


def speech_ranges_from_probabilities(
    samples, *, model: VadProbabilityModel, settings: VadSettings
) -> list[TimeRange]:
    sample_count = len(samples)
    if sample_count == 0:
        return []

    model.reset_states()
    speech_probs: list[float] = []
    for start in range(0, sample_count, VAD_CHUNK_SAMPLES):
        chunk = samples[start : start + VAD_CHUNK_SAMPLES]
        if len(chunk) < VAD_CHUNK_SAMPLES:
            chunk = _pad_chunk(chunk, VAD_CHUNK_SAMPLES, np_module=model._np)
        speech_probs.append(model(chunk))

    min_speech_samples = VAD_SAMPLE_RATE * settings.min_speech_duration_ms / 1000.0
    min_silence_samples = VAD_SAMPLE_RATE * settings.min_silence_duration_ms / 1000.0
    speech_pad_samples = int(VAD_SAMPLE_RATE * settings.speech_pad_ms / 1000.0)
    negative_threshold = max(settings.threshold - 0.15, 0.01)

    ranges: list[tuple[int, int]] = []
    triggered = False
    speech_start = 0
    pending_end = 0

    for idx, probability in enumerate(speech_probs):
        current_sample = idx * VAD_CHUNK_SAMPLES
        if probability >= settings.threshold:
            if pending_end:
                pending_end = 0
            if not triggered:
                triggered = True
                speech_start = current_sample
            continue

        if probability < negative_threshold and triggered:
            if not pending_end:
                pending_end = current_sample
            if current_sample - pending_end >= min_silence_samples:
                if pending_end - speech_start > min_speech_samples:
                    ranges.append((speech_start, pending_end))
                triggered = False
                pending_end = 0

    if triggered and sample_count - speech_start > min_speech_samples:
        ranges.append((speech_start, sample_count))

    return [
        TimeRange(
            start=max(0.0, (start - speech_pad_samples) / VAD_SAMPLE_RATE),
            end=min(sample_count / VAD_SAMPLE_RATE, (end + speech_pad_samples) / VAD_SAMPLE_RATE),
        )
        for start, end in ranges
        if end > start
    ]


def _pad_chunk(chunk, size: int, *, np_module):
    if len(chunk) >= size:
        return chunk
    output = np_module.zeros(size, dtype=np_module.float32)
    output[: len(chunk)] = chunk
    return output


def build_vad_report(
    *,
    project_root: Path,
    source_video: Path,
    audio_source: Path | None,
    media_info: VideoInfo,
    settings: VadSettings,
    speech_ranges: list[TimeRange] | tuple[TimeRange, ...],
) -> dict[str, Any]:
    duration = max(0.0, float(media_info.duration))
    raw_speech = sort_and_clamp_ranges(speech_ranges, duration)
    speech = merge_close_ranges(raw_speech, settings.merge_speech_gap_seconds)
    manual_keep = sort_and_clamp_ranges(settings.manual_keep_ranges, duration)
    normal_speed = sort_and_clamp_ranges(union_ranges(speech, manual_keep), duration)
    if duration > 0 and not normal_speed:
        normal_speed = [TimeRange(start=0.0, end=duration)]
    non_speech = complement_ranges(normal_speed, duration)

    p = paths(project_root)
    return {
        "schema_version": 1,
        "detector": "silero-vad",
        "source_video": _project_relative(source_video, p.root),
        "audio_source": _project_relative(audio_source, p.root) if audio_source else None,
        "video_duration_seconds": round(duration, 6),
        "settings": settings.detector_settings_dict(),
        "speech_ranges": _ranges_to_dicts(speech),
        "manual_keep_ranges": _ranges_to_dicts(manual_keep),
        "normal_speed_ranges": _ranges_to_dicts(normal_speed),
        "non_speech_ranges": _ranges_to_dicts(non_speech),
        "speed_muted_ranges": _ranges_to_dicts(non_speech),
    }


def run_vad_detection(
    project_root: Path,
    *,
    threshold: float | None = None,
    min_speech_duration_ms: int | None = None,
    min_silence_duration_ms: int | None = None,
    speech_pad_ms: int | None = None,
    merge_speech_gap_seconds: float | None = None,
) -> Path:
    cfg = load_project(project_root)
    trim_cfg: dict[str, Any] = cfg.get("trim", {})
    settings = vad_settings_from_trim_config(
        trim_cfg,
        threshold=threshold,
        min_speech_duration_ms=min_speech_duration_ms,
        min_silence_duration_ms=min_silence_duration_ms,
        speech_pad_ms=speech_pad_ms,
        merge_speech_gap_seconds=merge_speech_gap_seconds,
    )
    p = paths(project_root)
    source = p.root / cfg.get("original_path", "input/original.mp4")
    media_info = probe_media(source)
    report = create_vad_report(
        project_root,
        source=source,
        media_info=media_info,
        settings=settings,
    )
    write_json(p.work_dir / VAD_RANGES_FILE, report)
    return p.work_dir / VAD_RANGES_FILE


def load_or_create_vad_report(
    project_root: Path,
    *,
    source: Path,
    media_info: VideoInfo,
    settings: VadSettings,
    allow_detection: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    p = paths(project_root)
    report_path = p.work_dir / VAD_RANGES_FILE
    if report_path.exists() and not force:
        report = read_json(report_path)
        if _report_matches(
            report, root=p.root, source=source, media_info=media_info, settings=settings
        ):
            return report

    if not allow_detection:
        raise ValueError(f"VAD ranges not found or stale. Run `vided vad {project_root}` first.")

    report = create_vad_report(
        project_root, source=source, media_info=media_info, settings=settings
    )
    write_json(report_path, report)
    return report


def create_vad_report(
    project_root: Path,
    *,
    source: Path,
    media_info: VideoInfo,
    settings: VadSettings,
) -> dict[str, Any]:
    audio_source: Path | None = None
    speech: list[TimeRange] = []
    if media_info.has_audio:
        audio_source = paths(project_root).work_dir / VAD_AUDIO_FILE
        extract_vad_audio(source, audio_source)
        speech = detect_speech_ranges(audio_source, settings)

    return build_vad_report(
        project_root=project_root,
        source_video=source,
        audio_source=audio_source,
        media_info=media_info,
        settings=settings,
        speech_ranges=speech,
    )


def activity_ranges_from_vad_report(
    report: dict[str, Any],
    *,
    duration: float,
) -> list[tuple[float, float, bool]]:
    normal_speed = sort_and_clamp_ranges(
        _ranges_from_dicts(report.get("normal_speed_ranges", [])), duration
    )
    if duration > 0 and not normal_speed and not report.get("speech_ranges"):
        normal_speed = [TimeRange(start=0.0, end=duration)]

    inactive = complement_ranges(normal_speed, duration)
    combined: list[tuple[float, float, bool]] = []
    combined.extend((item.start, item.end, True) for item in normal_speed)
    combined.extend((item.start, item.end, False) for item in inactive)
    return sorted(combined, key=lambda item: (item[0], item[1], not item[2]))


def _validate_vad_settings(settings: VadSettings) -> None:
    if not 0 <= settings.threshold <= 1:
        raise ValueError("vad threshold must be between 0 and 1")
    if settings.min_speech_duration_ms < 0:
        raise ValueError("vad min speech duration must be greater than or equal to 0")
    if settings.min_silence_duration_ms < 0:
        raise ValueError("vad min silence duration must be greater than or equal to 0")
    if settings.speech_pad_ms < 0:
        raise ValueError("vad speech pad must be greater than or equal to 0")
    if settings.merge_speech_gap_seconds < 0:
        raise ValueError("vad merge speech gap must be greater than or equal to 0")


def _ranges_to_dicts(ranges: list[TimeRange] | tuple[TimeRange, ...]) -> list[dict[str, float]]:
    return [item.as_dict() for item in ranges]


def _ranges_from_dicts(raw: Any) -> list[TimeRange]:
    if not isinstance(raw, list):
        return []
    ranges: list[TimeRange] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            ranges.append(TimeRange(start=float(item["start"]), end=float(item["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    return ranges


def _project_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _report_matches(
    report: dict[str, Any],
    *,
    root: Path,
    source: Path,
    media_info: VideoInfo,
    settings: VadSettings,
) -> bool:
    if report.get("detector") != "silero-vad":
        return False
    if report.get("source_video") != _project_relative(source, root):
        return False
    if abs(float(report.get("video_duration_seconds", -1.0)) - float(media_info.duration)) > 0.001:
        return False
    if report.get("settings") != settings.detector_settings_dict():
        return False
    return report.get("manual_keep_ranges", []) == _ranges_to_dicts(settings.manual_keep_ranges)
