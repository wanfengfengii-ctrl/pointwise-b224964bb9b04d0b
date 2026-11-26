import sqlite3

from media.repository import StoredAsset, insert_asset, read_asset
from media.samples import normalize_samples, validate_sample_rate


def register_asset(db: sqlite3.Connection, source: str, sample_rate: int,
                   frames: list[int]) -> StoredAsset:
    if not isinstance(source, str) or not source.strip():
        raise ValueError('source must be a non-empty string')
    rate = validate_sample_rate(sample_rate)
    samples = normalize_samples(frames)
    with db:
        return insert_asset(db, source, rate, samples)


def get_asset(db: sqlite3.Connection, asset_id: int) -> StoredAsset:
    if type(asset_id) is not int or asset_id <= 0:
        raise ValueError('asset_id must be a positive integer')
    return read_asset(db, asset_id)
