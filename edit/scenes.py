import sqlite3
from dataclasses import dataclass


class RevisionConflict(Exception):
    pass


@dataclass(frozen=True)
class SceneHead:
    scene: str
    revision_id: int
    sample_rate: int | None


def initialize_scenes(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS scene_heads (
            scene TEXT PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES revisions(id),
            sample_rate TEXT
        )
    ''')


def read_scene_head(db: sqlite3.Connection, scene: str) -> SceneHead | None:
    row = db.execute(
        'SELECT revision_id, sample_rate FROM scene_heads WHERE scene = ?', (scene,),
    ).fetchone()
    if row is None:
        return None
    revision_id, rate = row
    return SceneHead(scene, revision_id, None if rate is None else int(rate))


def update_scene_head(db: sqlite3.Connection, head: SceneHead) -> None:
    rate = None if head.sample_rate is None else str(head.sample_rate)
    db.execute('''
        INSERT INTO scene_heads(scene, revision_id, sample_rate) VALUES (?, ?, ?)
        ON CONFLICT(scene) DO UPDATE SET
            revision_id = excluded.revision_id, sample_rate = excluded.sample_rate
    ''', (head.scene, head.revision_id, rate))
