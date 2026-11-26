from dataclasses import dataclass

from media.slices import AssetSlice


@dataclass(frozen=True)
class SourceSpan:
    track: str
    occurrence_id: int
    asset_id: int
    source: str
    source_start: int
    source_end: int
    start: int
    end: int


def describe_source(source: AssetSlice, track: str, occurrence_id: int, start: int) -> SourceSpan:
    return SourceSpan(
        track=track,
        occurrence_id=occurrence_id,
        asset_id=source.asset.asset_id,
        source=source.asset.source,
        source_start=source.start,
        source_end=source.end,
        start=start,
        end=start + source.end - source.start,
    )
