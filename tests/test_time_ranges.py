from __future__ import annotations

from vided.time_ranges import (
    TimeRange,
    complement_ranges,
    drop_short_ranges,
    merge_close_ranges,
    sort_and_clamp_ranges,
    union_ranges,
)


def test_sort_and_clamp_ranges_drops_empty_and_out_of_bounds_ranges() -> None:
    ranges = [
        TimeRange(start=4.0, end=7.0),
        TimeRange(start=-1.0, end=1.0),
        TimeRange(start=3.0, end=3.0),
        TimeRange(start=9.0, end=12.0),
    ]

    assert sort_and_clamp_ranges(ranges, duration=10.0) == [
        TimeRange(start=0.0, end=1.0),
        TimeRange(start=4.0, end=7.0),
        TimeRange(start=9.0, end=10.0),
    ]


def test_merge_close_ranges_merges_overlaps_and_tiny_gaps() -> None:
    ranges = [
        TimeRange(start=0.0, end=1.0),
        TimeRange(start=1.1, end=2.0),
        TimeRange(start=3.0, end=4.0),
        TimeRange(start=3.5, end=5.0),
    ]

    assert merge_close_ranges(ranges, max_gap=0.25) == [
        TimeRange(start=0.0, end=2.0),
        TimeRange(start=3.0, end=5.0),
    ]


def test_union_and_complement_ranges() -> None:
    normal = union_ranges(
        [TimeRange(start=1.0, end=2.0), TimeRange(start=4.0, end=5.0)],
        [TimeRange(start=1.5, end=3.0)],
    )

    assert normal == [
        TimeRange(start=1.0, end=3.0),
        TimeRange(start=4.0, end=5.0),
    ]
    assert complement_ranges(normal, duration=6.0) == [
        TimeRange(start=0.0, end=1.0),
        TimeRange(start=3.0, end=4.0),
        TimeRange(start=5.0, end=6.0),
    ]


def test_drop_short_ranges() -> None:
    assert drop_short_ranges(
        [
            TimeRange(start=0.0, end=0.5),
            TimeRange(start=1.0, end=2.0),
        ],
        min_duration=0.75,
    ) == [TimeRange(start=1.0, end=2.0)]
