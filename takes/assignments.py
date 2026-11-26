import json
import sqlite3
from dataclasses import asdict, dataclass

from edit.placements import Placement
from edit.revisions import get_revision
from takes.windows import RecordingWindow, capture_recording_window


class TakeConflict(Exception):
    pass


@dataclass(frozen=True)
class Assignment:
    take_id: int
    window: RecordingWindow
    state: str
    master_id: int | None


def initialize_assignments(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS take_assignments (
            id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES revisions(id),
            recording_window TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('pending', 'received', 'adopted')),
            master_id INTEGER UNIQUE REFERENCES masters(id),
            CHECK ((state = 'adopted') = (master_id IS NOT NULL))
        )
    ''')


def issue_take(db: sqlite3.Connection, revision_id: int, start: int, end: int) -> Assignment:
    with db:
        db.execute('BEGIN IMMEDIATE')
        revision = get_revision(db, revision_id)
        window = capture_recording_window(revision, start, end)
        cursor = db.execute('''
            INSERT INTO take_assignments(revision_id, recording_window, state)
            VALUES (?, ?, 'pending')
        ''', (revision_id, json.dumps(asdict(window))))
        return Assignment(cursor.lastrowid, window, 'pending', None)


def get_assignment(db: sqlite3.Connection, take_id: int) -> Assignment:
    if type(take_id) is not int or take_id <= 0:
        raise ValueError('take_id must be a positive integer')
    row = db.execute('''
        SELECT recording_window, state, master_id FROM take_assignments WHERE id = ?
    ''', (str(take_id),)).fetchone()
    if row is None:
        raise KeyError(f'unknown take {take_id}')
    window_json, state, master_id = row
    saved = json.loads(window_json)
    saved['dialogue'] = tuple(Placement(**piece) for piece in saved['dialogue'])
    return Assignment(take_id, RecordingWindow(**saved), state, master_id)


def mark_received(db: sqlite3.Connection, take_id: int) -> None:
    result = db.execute('''
        UPDATE take_assignments SET state = 'received' WHERE id = ? AND state = 'pending'
    ''', (take_id,))
    if result.rowcount != 1:
        raise TakeConflict('take is no longer awaiting a return')


def record_adoption(db: sqlite3.Connection, take_id: int, master_id: int) -> None:
    result = db.execute('''
        UPDATE take_assignments SET state = 'adopted', master_id = ?
        WHERE id = ? AND state = 'received'
    ''', (master_id, take_id))
    if result.rowcount != 1:
        raise TakeConflict('take is no longer awaiting adoption')
