import json
import sqlite3
from dataclasses import asdict, dataclass

from edit.instructions import decode_instructions
from edit.placements import Placement, scene_extent
from edit.scenes import RevisionConflict, SceneHead, read_scene_head, update_scene_head
from edit.splices import SceneLayout, apply_instructions
from mix.levels import TrackLevel


@dataclass(frozen=True)
class Revision:
    revision_id: int
    scene: str
    parent_revision_id: int | None
    layout: SceneLayout

    @property
    def length(self) -> int:
        return scene_extent(self.layout.placements)


def initialize_revisions(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY,
            scene TEXT NOT NULL,
            parent_id INTEGER REFERENCES revisions(id),
            snapshot TEXT NOT NULL
        )
    ''')


def submit_revision(db: sqlite3.Connection, scene: str, parent_revision_id: int | None,
                    instructions: list[dict]) -> Revision:
    if not isinstance(scene, str) or not scene.strip():
        raise ValueError('scene must be a non-empty string')
    if parent_revision_id is not None:
        _validate_revision_id(parent_revision_id)
    operations = decode_instructions(instructions)

    with db:
        db.execute('BEGIN IMMEDIATE')
        head = read_scene_head(db, scene)
        current_id = None if head is None else head.revision_id
        if current_id != parent_revision_id:
            raise RevisionConflict('parent_revision_id is not the current scene revision')
        if head is None:
            layout = SceneLayout(None, (), {}, 1)
        else:
            layout = get_revision(db, head.revision_id).layout
        candidate = apply_instructions(db, layout, operations)
        cursor = db.execute(
            'INSERT INTO revisions(scene, parent_id, snapshot) VALUES (?, ?, ?)',
            (scene, parent_revision_id, json.dumps(asdict(candidate))),
        )
        revision = Revision(cursor.lastrowid, scene, parent_revision_id, candidate)
        update_scene_head(db, SceneHead(scene, revision.revision_id, candidate.sample_rate))
    return revision


def get_revision(db: sqlite3.Connection, revision_id: int) -> Revision:
    _validate_revision_id(revision_id)
    row = db.execute(
        'SELECT scene, parent_id, snapshot FROM revisions WHERE id = ?', (str(revision_id),),
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown revision {revision_id}')
    scene, parent_id, snapshot = row
    saved = json.loads(snapshot)
    layout = SceneLayout(
        saved['sample_rate'],
        tuple(Placement(**item) for item in saved['placements']),
        {track: TrackLevel(**level) for track, level in saved['levels'].items()},
        saved['next_occurrence'],
    )
    return Revision(revision_id, scene, parent_id, layout)


def _validate_revision_id(revision_id: int) -> None:
    if type(revision_id) is not int or revision_id <= 0:
        raise ValueError('revision_id must be a positive integer')
