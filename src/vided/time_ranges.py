from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeRange:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict[str, float]:
        return {"start": round(self.start, 6), "end": round(self.end, 6)}


def sort_and_clamp_ranges(
    ranges: list[TimeRange] | tuple[TimeRange, ...], duration: float
) -> list[TimeRange]:
    if duration <= 0:
        return []

    clamped: list[TimeRange] = []
    for item in ranges:
        start = max(0.0, min(float(item.start), duration))
        end = max(0.0, min(float(item.end), duration))
        if end > start:
            clamped.append(TimeRange(start=start, end=end))
    return sorted(clamped, key=lambda item: (item.start, item.end))


def merge_close_ranges(
    ranges: list[TimeRange] | tuple[TimeRange, ...], max_gap: float
) -> list[TimeRange]:
    if max_gap < 0:
        raise ValueError("max_gap must be greater than or equal to 0")

    sorted_ranges = sorted(
        (item for item in ranges if item.end > item.start),
        key=lambda item: (item.start, item.end),
    )
    if not sorted_ranges:
        return []

    merged: list[TimeRange] = [sorted_ranges[0]]
    for item in sorted_ranges[1:]:
        previous = merged[-1]
        if item.start <= previous.end + max_gap:
            merged[-1] = TimeRange(start=previous.start, end=max(previous.end, item.end))
        else:
            merged.append(item)
    return merged


def union_ranges(
    left: list[TimeRange] | tuple[TimeRange, ...],
    right: list[TimeRange] | tuple[TimeRange, ...],
) -> list[TimeRange]:
    return merge_close_ranges([*left, *right], 0.0)


def complement_ranges(
    ranges: list[TimeRange] | tuple[TimeRange, ...], duration: float
) -> list[TimeRange]:
    if duration <= 0:
        return []

    output: list[TimeRange] = []
    cursor = 0.0
    for item in sort_and_clamp_ranges(merge_close_ranges(ranges, 0.0), duration):
        if item.start > cursor:
            output.append(TimeRange(start=cursor, end=item.start))
        cursor = max(cursor, item.end)
    if cursor < duration:
        output.append(TimeRange(start=cursor, end=duration))
    return output


def drop_short_ranges(
    ranges: list[TimeRange] | tuple[TimeRange, ...],
    min_duration: float,
) -> list[TimeRange]:
    if min_duration <= 0:
        return list(ranges)
    return [item for item in ranges if item.duration >= min_duration]
