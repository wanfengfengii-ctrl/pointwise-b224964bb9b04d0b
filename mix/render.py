import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from edit.placements import Placement
from edit.revisions import Revision
from media.provenance import SourceSpan, describe_source
from media.slices import resolve_slice, slice_frames
from mix.levels import TrackLevel, finalize_sample, scale_contribution
from mix.timeline import TimelineWindow, iter_window_placements


@dataclass(frozen=True)
class VoiceReplacement:
    occurrence_id: int
    start: int
    frames: tuple[int, ...]

    @property
    def end(self) -> int:
        return self.start + len(self.frames)


@dataclass(frozen=True)
class RenderedMix:
    revision_id: int
    start: int
    end: int
    frames: tuple[int, ...]
    sources: tuple[SourceSpan, ...]
    replacements: tuple[tuple[int, int, int], ...]


def render_mix(db: sqlite3.Connection, revision: Revision, window: TimelineWindow,
               replacements: tuple[VoiceReplacement, ...] = ()) -> RenderedMix:
    pending: dict[int, list[VoiceReplacement]] = defaultdict(list)
    for replacement in sorted(replacements, key=lambda item: item.start):
        pending[replacement.occurrence_id].append(replacement)
    totals = [0] * window.length
    sources = []
    applied = []
    default_level = TrackLevel()

    for placement in iter_window_placements(revision, window):
        level = revision.layout.levels.get(placement.track, default_level)
        cursor = placement.start
        voice = pending.get(placement.occurrence_id, ()) if placement.track == 'dialogue' else ()
        for replacement in voice:
            start = max(placement.start, replacement.start)
            end = min(placement.end, replacement.end)
            if start >= end:
                continue
            if start < cursor:
                raise ValueError('replacement excerpts cannot overlap')
            if level.audible:
                if cursor < start:
                    sources.append(_mix_original(db, placement, cursor, start, level, window, totals))
                excerpt = replacement.frames[start - replacement.start:end - replacement.start]
                _add_samples(totals, start - window.start, excerpt, level)
            applied.append((placement.occurrence_id, start, end))
            cursor = end
        if level.audible and cursor < placement.end:
            sources.append(_mix_original(db, placement, cursor, placement.end, level, window, totals))

    return RenderedMix(
        revision.revision_id, window.start, window.end,
        tuple(finalize_sample(total) for total in totals), tuple(sources), tuple(applied),
    )


def _mix_original(db: sqlite3.Connection, placement: Placement, start: int, end: int,
                  level: TrackLevel, window: TimelineWindow, totals: list[int]) -> SourceSpan:
    source_start = placement.source_start + start - placement.start
    source = resolve_slice(db, placement.asset_id, source_start, source_start + end - start)
    _add_samples(totals, start - window.start, slice_frames(source), level)
    return describe_source(source, placement.track, placement.occurrence_id, start)


def _add_samples(totals: list[int], offset: int, frames: tuple[int, ...], level: TrackLevel) -> None:
    for index, frame in enumerate(frames, offset):
        totals[index] += scale_contribution(frame, level)
