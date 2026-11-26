import sqlite3
from dataclasses import dataclass

from media.catalog import get_asset
from media.repository import StoredAsset


@dataclass(frozen=True)
class AssetSlice:
    asset: StoredAsset
    start: int
    end: int


def resolve_slice(db: sqlite3.Connection, asset_id: int, start: int, end: int) -> AssetSlice:
    asset = get_asset(db, asset_id)
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(asset.frames):
        raise ValueError('asset slice is out of bounds')
    return AssetSlice(asset, start, end)


def slice_frames(source: AssetSlice) -> tuple[int, ...]:
    return source.asset.frames[source.start:source.end]
