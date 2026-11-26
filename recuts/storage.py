import json
import sqlite3
from dataclasses import dataclass

from edit.placements import Placement
from masters.catalog import get_master
from mix.levels import TrackLevel
from recuts.layout import RecutLayout
from recuts.splices import RecutConflict
from recuts.voices import TakeVoice


@dataclass(frozen=True)
class RecutDraft:
    recut_id: int
    original_master_id: int
    head_version_id: int
    restored: bool
    inherited: frozenset[int]


@dataclass(frozen=True)
class RecutVersion:
    version_id: int
    recut_id: int
    parent_version_id: int | None
    layout: RecutLayout
    restored: bool


def initialize_recuts(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS recut_drafts (
            id INTEGER PRIMARY KEY,
            original_master_id INTEGER NOT NULL REFERENCES masters(id),
            head_version_id INTEGER NOT NULL,
            restored INTEGER NOT NULL CHECK (restored IN (0, 1)),
            inherited TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS recut_versions (
            id INTEGER PRIMARY KEY,
            recut_id INTEGER NOT NULL REFERENCES recut_drafts(id),
            parent_id INTEGER REFERENCES recut_versions(id),
            snapshot TEXT NOT NULL,
            restored INTEGER NOT NULL CHECK (restored IN (0, 1))
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS recut_publications (
            master_id INTEGER PRIMARY KEY REFERENCES masters(id),
            recut_id INTEGER NOT NULL REFERENCES recut_drafts(id),
            version_id INTEGER NOT NULL REFERENCES recut_versions(id),
            sample_rate TEXT NOT NULL,
            frames TEXT NOT NULL,
            sources TEXT NOT NULL,
            original_master_id INTEGER NOT NULL REFERENCES masters(id)
        )
    ''')


def insert_draft(db: sqlite3.Connection, original_master_id: int,
                 layout: RecutLayout, inherited: frozenset[int]) -> tuple[RecutDraft, RecutVersion]:
    cursor = db.execute(
        'INSERT INTO recut_drafts(original_master_id, head_version_id, restored, inherited)'
        ' VALUES (?, 0, 0, ?)',
        (original_master_id, json.dumps(sorted(inherited))),
    )
    recut_id = cursor.lastrowid
    version_cursor = db.execute(
        'INSERT INTO recut_versions(recut_id, parent_id, snapshot, restored) VALUES (?, ?, ?, 0)',
        (recut_id, None, json.dumps(encode_layout(layout))),
    )
    head_id = version_cursor.lastrowid
    db.execute('UPDATE recut_drafts SET head_version_id = ? WHERE id = ?', (head_id, recut_id))
    draft = RecutDraft(recut_id, original_master_id, head_id, False, inherited)
    return draft, RecutVersion(head_id, recut_id, None, layout, False)


def get_draft(db: sqlite3.Connection, recut_id: int) -> RecutDraft:
    _validate_id(recut_id)
    row = db.execute(
        'SELECT original_master_id, head_version_id, restored, inherited FROM recut_drafts WHERE id = ?',
        (str(recut_id),),
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown recut {recut_id}')
    original_master_id, head_version_id, restored, inherited = row
    return RecutDraft(
        recut_id, original_master_id, head_version_id, bool(restored),
        frozenset(json.loads(inherited)),
    )


def update_head(db: sqlite3.Connection, draft: RecutDraft, head_version_id: int,
                restored: bool) -> None:
    db.execute(
        'UPDATE recut_drafts SET head_version_id = ?, restored = ? WHERE id = ?',
        (head_version_id, int(restored), draft.recut_id),
    )


def insert_version(db: sqlite3.Connection, draft: RecutDraft, parent_version_id: int,
                   layout: RecutLayout, restored: bool) -> RecutVersion:
    cursor = db.execute(
        'INSERT INTO recut_versions(recut_id, parent_id, snapshot, restored) VALUES (?, ?, ?, ?)',
        (draft.recut_id, parent_version_id, json.dumps(encode_layout(layout)), int(restored)),
    )
    return RecutVersion(cursor.lastrowid, draft.recut_id, parent_version_id, layout, restored)


def get_version(db: sqlite3.Connection, version_id: int) -> RecutVersion:
    _validate_id(version_id)
    row = db.execute(
        'SELECT recut_id, parent_id, snapshot, restored FROM recut_versions WHERE id = ?',
        (str(version_id),),
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown recut version {version_id}')
    recut_id, parent_id, snapshot, restored = row
    return RecutVersion(version_id, recut_id, parent_id, decode_layout(json.loads(snapshot)),
                        bool(restored))


def insert_publication(db: sqlite3.Connection, master_id: int, draft: RecutDraft,
                       version: RecutVersion, sample_rate: int, frames: tuple[int, ...],
                       sources: tuple[dict, ...]) -> None:
    db.execute('''
        INSERT INTO recut_publications(
            master_id, recut_id, version_id, sample_rate, frames, sources, original_master_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        master_id, draft.recut_id, version.version_id, str(sample_rate),
        json.dumps(frames), json.dumps(sources), draft.original_master_id,
    ))


def get_publication(db: sqlite3.Connection, master_id: int) -> dict | None:
    row = db.execute('''
        SELECT recut_id, version_id, sample_rate, frames, sources, original_master_id
        FROM recut_publications WHERE master_id = ?
    ''', (str(master_id),)).fetchone()
    if row is None:
        return None
    recut_id, version_id, sample_rate, frames, sources, original_master_id = row
    return {
        'master_id': master_id, 'recut_id': recut_id, 'version_id': version_id,
        'original_master_id': original_master_id, 'sample_rate': int(sample_rate),
        'frames': json.loads(frames), 'sources': json.loads(sources),
    }


def require_original_master(db: sqlite3.Connection, master_id: int) -> None:
    _validate_id(master_id)
    row = db.execute(
        'SELECT 1 FROM recut_publications WHERE master_id = ?', (str(master_id),),
    ).fetchone()
    if row is not None:
        raise RecutConflict('a recut master cannot open another recut')
    get_master(db, master_id)


def encode_layout(layout: RecutLayout) -> dict:
    return {
        'sample_rate': layout.sample_rate,
        'placements': [
            {
                'occurrence_id': item.occurrence_id, 'track': item.track,
                'asset_id': item.asset_id, 'source_start': item.source_start,
                'source_end': item.source_end, 'start': item.start,
            }
            for item in layout.placements
        ],
        'levels': {track: {'percent': level.percent, 'muted': level.muted}
                   for track, level in layout.levels.items()},
        'next_occurrence': layout.next_occurrence,
        'voices': {
            str(occurrence): [
                {
                    'asset_start': voice.asset_start, 'asset_end': voice.asset_end,
                    'take_id': voice.take_id, 'take_start': voice.take_start,
                }
                for voice in excerpt
            ]
            for occurrence, excerpt in layout.voices.items()
        },
    }


def decode_layout(saved: dict) -> RecutLayout:
    voices = {
        int(occurrence): tuple(TakeVoice(**item) for item in excerpt)
        for occurrence, excerpt in saved['voices'].items()
    }
    return RecutLayout(
        saved['sample_rate'],
        tuple(Placement(**item) for item in saved['placements']),
        {track: TrackLevel(**level) for track, level in saved['levels'].items()},
        saved['next_occurrence'],
        voices,
    )


def _validate_id(identifier: int) -> None:
    if type(identifier) is not int or identifier <= 0:
        raise ValueError('identifier must be a positive integer')
