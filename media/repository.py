import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredAsset:
    asset_id: int
    source: str
    sample_rate: int
    frames: tuple[int, ...]


def initialize_assets(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            sample_rate TEXT NOT NULL,
            frames TEXT NOT NULL
        )
    ''')


def insert_asset(db: sqlite3.Connection, source: str, sample_rate: int,
                 frames: tuple[int, ...]) -> StoredAsset:
    cursor = db.execute(
        'INSERT INTO assets(source, sample_rate, frames) VALUES (?, ?, ?)',
        (source, str(sample_rate), json.dumps(frames)),
    )
    return StoredAsset(cursor.lastrowid, source, sample_rate, frames)


def read_asset(db: sqlite3.Connection, asset_id: int) -> StoredAsset:
    row = db.execute(
        'SELECT source, sample_rate, frames FROM assets WHERE id = ?',
        (str(asset_id),),
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown asset {asset_id}')
    source, sample_rate, frames = row
    return StoredAsset(asset_id, source, int(sample_rate), tuple(json.loads(frames)))
