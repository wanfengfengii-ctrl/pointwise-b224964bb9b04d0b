import json
import sqlite3
from dataclasses import dataclass

from media.samples import normalize_samples
from takes.assignments import TakeConflict, get_assignment, mark_received


@dataclass(frozen=True)
class TakeReceipt:
    take_id: int
    frames: tuple[int, ...]


def initialize_receipts(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS take_receipts (
            take_id INTEGER PRIMARY KEY REFERENCES take_assignments(id),
            frames TEXT NOT NULL
        )
    ''')


def accept_return(db: sqlite3.Connection, take_id: int, frames: list[int]) -> TakeReceipt:
    with db:
        db.execute('BEGIN IMMEDIATE')
        assignment = get_assignment(db, take_id)
        if assignment.state != 'pending':
            raise TakeConflict('take is no longer awaiting a return')
        samples = normalize_samples(frames)
        if len(samples) != assignment.window.length:
            raise ValueError(f'expected {assignment.window.length} recording frames')
        db.execute(
            'INSERT INTO take_receipts(take_id, frames) VALUES (?, ?)',
            (take_id, json.dumps(samples)),
        )
        mark_received(db, take_id)
    return TakeReceipt(take_id, samples)


def get_receipt(db: sqlite3.Connection, take_id: int) -> TakeReceipt | None:
    row = db.execute('SELECT frames FROM take_receipts WHERE take_id = ?', (str(take_id),)).fetchone()
    return None if row is None else TakeReceipt(take_id, tuple(json.loads(row[0])))
