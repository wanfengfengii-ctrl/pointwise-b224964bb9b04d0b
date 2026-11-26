import json
import sqlite3
from dataclasses import dataclass

from masters.manifest import MasterManifest, decode_manifest, encode_manifest


@dataclass(frozen=True)
class StoredMaster:
    master_id: int
    manifest: MasterManifest
    frames: tuple[int, ...]


def initialize_masters(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS masters (
            id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES revisions(id),
            manifest TEXT NOT NULL,
            frames TEXT NOT NULL
        )
    ''')


def insert_master(db: sqlite3.Connection, manifest: MasterManifest,
                  frames: tuple[int, ...]) -> StoredMaster:
    cursor = db.execute('''
        INSERT INTO masters(revision_id, manifest, frames) VALUES (?, ?, ?)
    ''', (manifest.revision_id, encode_manifest(manifest), json.dumps(frames)))
    return StoredMaster(cursor.lastrowid, manifest, frames)


def get_master(db: sqlite3.Connection, master_id: int) -> StoredMaster:
    if type(master_id) is not int or master_id <= 0:
        raise ValueError('master_id must be a positive integer')
    row = db.execute('SELECT manifest, frames FROM masters WHERE id = ?', (str(master_id),)).fetchone()
    if row is None:
        raise KeyError(f'unknown master {master_id}')
    return StoredMaster(master_id, decode_manifest(row[0]), tuple(json.loads(row[1])))


def list_master_ids(db: sqlite3.Connection) -> list[int]:
    return [row[0] for row in db.execute('SELECT id FROM masters ORDER BY id')]
