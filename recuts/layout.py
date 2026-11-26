from dataclasses import dataclass, field

from edit.placements import Placement
from mix.levels import TrackLevel
from recuts.voices import TakeVoice, voices_for_piece


@dataclass(frozen=True)
class RecutLayout:
    """Paper timeline of a recut draft version.

    ``voices`` maps an occurrence to the take excerpts fixed for it at open or
    copy time. Restoring dialogue drops the inherited entries; copies keep the
    dry sound (asset or take excerpts) captured when the copy was made.
    """

    sample_rate: int | None
    placements: tuple[Placement, ...]
    levels: dict[str, TrackLevel]
    next_occurrence: int
    voices: dict[int, tuple[TakeVoice, ...]] = field(default_factory=dict)

    def piece_voices(self, placement: Placement) -> tuple[TakeVoice, ...]:
        return voices_for_piece(self.voices.get(placement.occurrence_id, ()),
                                placement.source_start, placement.source_end)


def scene_length(layout: RecutLayout) -> int:
    return max((placement.end for placement in layout.placements), default=0)
