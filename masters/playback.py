import sqlite3
from dataclasses import asdict

from masters.catalog import get_master


def listen_master(db: sqlite3.Connection, master_id: int) -> dict:
    master = get_master(db, master_id)
    return {'master_id': master.master_id, **asdict(master.manifest), 'frames': master.frames}
