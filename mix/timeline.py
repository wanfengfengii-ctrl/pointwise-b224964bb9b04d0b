from collections.abc import Iterator
from dataclasses import dataclass

from edit.placements import Placement, clip_placement
from edit.revisions import Revision


@dataclass(frozen=True)
class TimelineWindow:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def validate_listen_window(revision: Revision, start: int, end: int) -> TimelineWindow:
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= revision.length:
        raise ValueError('window must be a non-empty interval within the scene')
    return TimelineWindow(start, end)


def iter_window_placements(revision: Revision, window: TimelineWindow) -> Iterator[Placement]:
    for placement in revision.layout.placements:
        piece = clip_placement(placement, window.start, window.end)
        if piece is not None:
            yield piece
