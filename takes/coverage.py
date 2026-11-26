from collections import defaultdict
from dataclasses import dataclass

from edit.placements import Placement
from edit.revisions import Revision
from takes.assignments import TakeConflict
from takes.windows import RecordingWindow


@dataclass(frozen=True)
class CoverageSpan:
    occurrence_id: int
    asset_id: int
    source_start: int
    source_end: int
    start: int
    end: int
    take_start: int
    take_end: int


@dataclass(frozen=True)
class WindowCoverage:
    spans: tuple[CoverageSpan, ...]

    @property
    def intervals(self) -> tuple[tuple[int, int], ...]:
        intervals: list[tuple[int, int]] = []
        for span in self.spans:
            if intervals and intervals[-1][1] == span.start:
                start, _ = intervals[-1]
                intervals[-1] = (start, span.end)
            else:
                intervals.append((span.start, span.end))
        return tuple(intervals)


def resolve_window_coverage(window: RecordingWindow, revision: Revision) -> WindowCoverage:
    if window.scene != revision.scene or window.sample_rate != revision.layout.sample_rate:
        raise TakeConflict('recording window belongs to a different scene or sample rate')

    original: dict[tuple[int, int], list[Placement]] = defaultdict(list)
    for piece in window.dialogue:
        original[piece.occurrence_id, piece.asset_id].append(piece)

    spans = []
    for current in revision.layout.placements:
        if current.track != 'dialogue':
            continue
        for issued in original.get((current.occurrence_id, current.asset_id), ()):
            source_start = max(issued.source_start, current.source_start)
            source_end = min(issued.source_end, current.source_end)
            if source_start >= source_end:
                continue
            length = source_end - source_start
            start = current.start + source_start - current.source_start
            take_start = issued.start - window.start + source_start - issued.source_start
            spans.append(CoverageSpan(
                current.occurrence_id, current.asset_id, source_start, source_end,
                start, start + length, take_start, take_start + length,
            ))

    if not spans:
        raise TakeConflict('no original dialogue survives in the current revision')
    spans.sort(key=lambda span: span.start)
    return WindowCoverage(tuple(spans))
