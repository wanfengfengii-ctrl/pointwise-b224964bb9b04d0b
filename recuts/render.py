import sqlite3
from dataclasses import dataclass

from media.provenance import describe_source
from media.slices import resolve_slice, slice_frames
from mix.levels import TrackLevel, finalize_sample, scale_contribution
from recuts.layout import RecutLayout
from recuts.voices import TakeVoice
from takes.returns import get_receipt


@dataclass(frozen=True)
class RecutRender:
    sample_rate: int | None
    frames: tuple[int, ...]
    sources: tuple[dict, ...]


def render_recut(db: sqlite3.Connection, layout: RecutLayout) -> RecutRender:
    length = max((placement.end for placement in layout.placements), default=0)
    totals = [0] * length
    sources: list[dict] = []
    take_cache: dict[int, tuple[int, ...]] = {}
    default_level = TrackLevel()

    for placement in layout.placements:
        level = layout.levels.get(placement.track, default_level)
        if not level.audible:
            continue
        cursor = placement.source_start
        for voice in layout.piece_voices(placement):
            if voice.asset_end <= cursor:
                continue
            if voice.asset_start > cursor:
                sources.append(_asset_span(db, placement, cursor, voice.asset_start, level, totals))
            _take_span(placement, voice, level, take_cache, db, totals, sources)
            cursor = voice.asset_end
        if cursor < placement.source_end:
            sources.append(_asset_span(db, placement, cursor, placement.source_end, level, totals))

    return RecutRender(layout.sample_rate, tuple(finalize_sample(total) for total in totals),
                       tuple(sources))


def _asset_span(db: sqlite3.Connection, placement, source_start, source_end,
                level: TrackLevel, totals: list[int]) -> dict:
    scene_start = placement.start + source_start - placement.source_start
    scene_end = placement.start + source_end - placement.source_start
    source = resolve_slice(db, placement.asset_id, source_start, source_end)
    offset = scene_start
    for frame in slice_frames(source):
        totals[offset] += scale_contribution(frame, level)
        offset += 1
    described = describe_source(source, placement.track, placement.occurrence_id, scene_start)
    return {
        'track': described.track, 'occurrence_id': described.occurrence_id,
        'kind': 'asset', 'asset_id': described.asset_id,
        'source_start': described.source_start, 'source_end': described.source_end,
        'start': described.start, 'end': described.end,
    }


def _take_span(placement, voice: TakeVoice, level: TrackLevel,
               take_cache: dict[int, tuple[int, ...]], db: sqlite3.Connection,
               totals: list[int], sources: list[dict]) -> None:
    frames = take_cache.get(voice.take_id)
    if frames is None:
        receipt = get_receipt(db, voice.take_id)
        if receipt is None:
            raise sqlite3.IntegrityError(f'take {voice.take_id} is missing its receipt')
        frames = receipt.frames
        take_cache[voice.take_id] = frames
    scene_start = placement.start + voice.asset_start - placement.source_start
    scene_end = placement.start + voice.asset_end - placement.source_start
    take_end = voice.take_start + voice.asset_end - voice.asset_start
    offset = scene_start
    for frame in frames[voice.take_start:take_end]:
        totals[offset] += scale_contribution(frame, level)
        offset += 1
    sources.append({
        'track': placement.track, 'occurrence_id': placement.occurrence_id,
        'kind': 'take', 'take_id': voice.take_id,
        'take_start': voice.take_start, 'take_end': take_end,
        'start': scene_start, 'end': scene_end,
    })
