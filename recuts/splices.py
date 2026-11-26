import sqlite3

from edit.placements import (
    Placement, clip_placement, copy_placement, move_placement, scene_extent,
)
from edit.splices import _choose_piece, _place
from media.slices import resolve_slice
from recuts.instructions import RecutInstruction
from recuts.layout import RecutLayout
from recuts.voices import voices_for_piece


class RecutConflict(Exception):
    pass


def apply_recut_instructions(db: sqlite3.Connection, layout: RecutLayout,
                             instructions: tuple[RecutInstruction, ...], restored: bool,
                             inherited: frozenset[int]) -> tuple[RecutLayout, bool]:
    placements = list(layout.placements)
    levels = dict(layout.levels)
    voices = dict(layout.voices)
    next_occurrence = layout.next_occurrence
    sample_rate = layout.sample_rate
    did_restore = False

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
                source_piece = placements[index]
                copied = copy_placement(source_piece, next_occurrence, fields['at'])
                _place(placements, copied)
                # Fix the dry sound selected at this step; copies keep it even if
                # the inherited replacement is restored later.
                voices[next_occurrence] = voices_for_piece(
                    voices.get(source_piece.occurrence_id, ()),
                    source_piece.source_start, source_piece.source_end,
                )
                next_occurrence += 1
            case 'move':
                index = _choose_piece(placements, fields['occurrence_id'], fields.get('piece_start'))
                _place(placements, move_placement(placements.pop(index), fields['at']))
            case 'remove':
                placements = _remove(placements, fields['track'], fields['start'], fields['end'])
            case 'level':
                levels[fields['track']] = fields['setting']
            case 'restore_dialogue':
                if restored or did_restore:
                    raise RecutConflict('the inherited dialogue replacement can only be restored once')
                for occurrence in inherited:
                    voices.pop(occurrence, None)
                did_restore = True
            case _:
                raise ValueError('unknown edit operation')

    placements.sort(key=lambda item: (item.track, item.start, item.occurrence_id))
    result = RecutLayout(
        sample_rate, tuple(placements), levels, next_occurrence,
        {key: value for key, value in voices.items() if value},
    )
    return result, restored or did_restore


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
