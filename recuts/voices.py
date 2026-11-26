from dataclasses import dataclass


@dataclass(frozen=True)
class TakeVoice:
    """A take (re-recording) excerpt backing a source interval of an occurrence.

    Coordinates refer to the originating asset's source range. At render time the
    segment is mapped onto whatever placement piece still covers that range, so a
    moved or clipped placement keeps drawing the replacement from the original
    take offset.
    """

    asset_start: int
    asset_end: int
    take_id: int
    take_start: int

    def clipped(self, source_start: int, source_end: int) -> 'TakeVoice | None':
        start = max(self.asset_start, source_start)
        end = min(self.asset_end, source_end)
        if start >= end:
            return None
        return TakeVoice(start, end, self.take_id, self.take_start + start - self.asset_start)


def voices_for_piece(voices: tuple[TakeVoice, ...], source_start: int,
                     source_end: int) -> tuple[TakeVoice, ...]:
    selected = [piece for voice in voices if (piece := voice.clipped(source_start, source_end)) is not None]
    selected.sort(key=lambda voice: voice.asset_start)
    return tuple(selected)
