import sqlite3
from dataclasses import dataclass

from edit.instructions import EditInstruction
from edit.placements import (
    Placement, clip_placement, copy_placement, move_placement, scene_extent,
)
from media.slices import resolve_slice
from mix.levels import TrackLevel


@dataclass(frozen=True)
class SceneLayout:
    sample_rate: int | None
    placements: tuple[Placement, ...]
    levels: dict[str, TrackLevel]
    next_occurrence: int


def apply_instructions(db: sqlite3.Connection, layout: SceneLayout,
                       instructions: tuple[EditInstruction, ...]) -> SceneLayout:
    placements = list(layout.placements)
    levels = dict(layout.levels)
    next_occurrence = layout.next_occurrence
    sample_rate = layout.sample_rate

    for instruction in instructions:
        fields = instruction.fields
        match instruction.operation:
            case 'insert':
                source = resolve_slice(db, fields['asset_id'], fields['source_start'], fields['source_end'])
                if sample_rate is None:
                    sample_rate = source.asset.sample_rate
                elif source.asset.sample_rate != sample_rate:
                    raise ValueError('asset sample rate does not match the scene')
                placement = Placement.from_slice(next_occurrence, fields['track'], source, fields['at'])
                _place(placements, placement)
                next_occurrence += 1
            case 'copy':
                index = _choose_piece(placements, fields['occurrence_id'], fields.get('piece_start'))
                _place(placements, copy_placement(placements[index], next_occurrence, fields['at']))
                next_occurrence += 1
            case 'move':
                index = _choose_piece(placements, fields['occurrence_id'], fields.get('piece_start'))
                _place(placements, move_placement(placements.pop(index), fields['at']))
            case 'remove':
                placements = _remove(placements, fields['track'], fields['start'], fields['end'])
            case 'level':
                levels[fields['track']] = fields['setting']
            case _:
                raise ValueError('unknown edit operation')

    placements.sort(key=lambda item: (item.track, item.start, item.occurrence_id))
    return SceneLayout(sample_rate, tuple(placements), levels, next_occurrence)


def _place(placements: list[Placement], candidate: Placement) -> None:
    if any(
        item.track == candidate.track and item.start < candidate.end and candidate.start < item.end
        for item in placements
    ):
        raise ValueError('placements on the same track cannot overlap')
    placements.append(candidate)


def _choose_piece(placements: list[Placement], occurrence_id: int, piece_start: int | None) -> int:
    matches = [
        index for index, item in enumerate(placements)
        if item.occurrence_id == occurrence_id and (piece_start is None or item.start == piece_start)
    ]
    if not matches:
        raise ValueError('the selected occurrence piece is absent')
    if len(matches) != 1:
        raise ValueError('piece_start is required to select one remaining piece')
    return matches[0]


def _remove(placements: list[Placement], track: str, start: int, end: int) -> list[Placement]:
    if not 0 <= start < end <= scene_extent(placements):
        raise ValueError('removal is out of scene bounds')
    retained = []
    removed = False
    for item in placements:
        if item.track != track or item.end <= start or end <= item.start:
            retained.append(item)
            continue
        removed = True
        for piece in (clip_placement(item, item.start, start), clip_placement(item, end, item.end)):
            if piece is not None:
                retained.append(piece)
    if not removed:
        raise ValueError('removal must intersect a placement on the selected track')
    return retained
