from collections.abc import Iterable
from dataclasses import dataclass, replace

from media.slices import AssetSlice


@dataclass(frozen=True)
class Placement:
    occurrence_id: int
    track: str
    asset_id: int
    source_start: int
    source_end: int
    start: int

    @property
    def end(self) -> int:
        return self.start + self.source_end - self.source_start

    @classmethod
    def from_slice(cls, occurrence_id: int, track: str, source: AssetSlice,
                   start: int) -> 'Placement':
        return cls(occurrence_id, track, source.asset.asset_id, source.start, source.end, start)


def clip_placement(placement: Placement, start: int, end: int) -> Placement | None:
    clipped_start = max(start, placement.start)
    clipped_end = min(end, placement.end)
    if clipped_start >= clipped_end:
        return None
    return replace(
        placement,
        start=clipped_start,
        source_start=placement.source_start + clipped_start - placement.start,
        source_end=placement.source_start + clipped_end - placement.start,
    )


def move_placement(placement: Placement, start: int) -> Placement:
    return replace(placement, start=start)


def copy_placement(placement: Placement, occurrence_id: int, start: int) -> Placement:
    return replace(placement, occurrence_id=occurrence_id, start=start)


def scene_extent(placements: Iterable[Placement]) -> int:
    return max((placement.end for placement in placements), default=0)
