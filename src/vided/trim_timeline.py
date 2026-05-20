from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .errors import ValidationError
from .trimmer import TrimSegment

_TIMELINE_TOLERANCE = 0.00001


@dataclass(frozen=True)
class TrimTimelineSegment:
    source_start: float
    source_end: float
    output_start: float
    output_end: float
    speed: float = 1.0
    mute_audio: bool = False

    @property
    def source_duration(self) -> float:
        return max(0.0, self.source_end - self.source_start)

    @property
    def output_duration(self) -> float:
        return max(0.0, self.output_end - self.output_start)

    def to_trim_segment(self) -> TrimSegment:
        return TrimSegment(
            start=self.source_start,
            end=self.source_end,
            speed=self.speed,
            mute_audio=self.mute_audio,
        )


def parse_trim_timeline_segments(raw: Any) -> list[TrimTimelineSegment]:
    if not isinstance(raw, list):
        raise ValidationError("trim_timeline segments must be a list")
    if not raw:
        raise ValidationError("trim_timeline has no segments")

    segments: list[TrimTimelineSegment] = []
    expected_output_start = 0.0
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValidationError(f"trim_timeline segment {index} must be an object")
        segment_data = cast(Mapping[str, Any], item)

        segment = TrimTimelineSegment(
            source_start=_float_field(segment_data, "source_start", index),
            source_end=_float_field(segment_data, "source_end", index),
            output_start=_float_field(segment_data, "output_start", index),
            output_end=_float_field(segment_data, "output_end", index),
            speed=_float_field(segment_data, "speed", index, default=1.0),
            mute_audio=_bool_field(segment_data, "mute_audio", index, default=False),
        )
        _validate_segment(segment, index, expected_output_start)
        segments.append(segment)
        expected_output_start = segment.output_end

    return segments


def timeline_segments_to_trim_segments(
    segments: list[TrimTimelineSegment],
) -> list[TrimSegment]:
    return [segment.to_trim_segment() for segment in segments]


def _float_field(
    item: Mapping[str, Any],
    name: str,
    index: int,
    *,
    default: float | None = None,
) -> float:
    if name not in item:
        if default is not None:
            return default
        raise ValidationError(f"trim_timeline segment {index} is missing {name}")

    value = item[name]
    if isinstance(value, bool):
        raise ValidationError(f"trim_timeline segment {index} {name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"trim_timeline segment {index} {name} must be a number") from exc


def _bool_field(
    item: Mapping[str, Any],
    name: str,
    index: int,
    *,
    default: bool,
) -> bool:
    if name not in item:
        return default
    value = item[name]
    if not isinstance(value, bool):
        raise ValidationError(f"trim_timeline segment {index} {name} must be a boolean")
    return value


def _validate_segment(
    segment: TrimTimelineSegment,
    index: int,
    expected_output_start: float,
) -> None:
    if segment.source_start < 0:
        raise ValidationError(f"trim_timeline segment {index} source_start must be non-negative")
    if segment.output_start < 0:
        raise ValidationError(f"trim_timeline segment {index} output_start must be non-negative")
    if segment.source_end <= segment.source_start:
        raise ValidationError(
            f"trim_timeline segment {index} source_end must be after source_start"
        )
    if segment.output_end <= segment.output_start:
        raise ValidationError(
            f"trim_timeline segment {index} output_end must be after output_start"
        )
    if segment.speed <= 0:
        raise ValidationError(f"trim_timeline segment {index} speed must be greater than zero")
    if abs(segment.output_start - expected_output_start) > _TIMELINE_TOLERANCE:
        raise ValidationError(
            f"trim_timeline segment {index} output_start must continue the previous segment"
        )

    expected_duration = segment.source_duration / segment.speed
    if abs(segment.output_duration - expected_duration) > _TIMELINE_TOLERANCE:
        raise ValidationError(
            f"trim_timeline segment {index} output duration does not match source duration"
        )
