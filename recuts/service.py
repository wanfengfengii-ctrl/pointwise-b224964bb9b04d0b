import json
import sqlite3

from edit.revisions import get_revision
from masters.catalog import get_master
from recuts.instructions import decode_recut_instructions
from recuts.layout import RecutLayout, scene_length
from recuts.render import render_recut
from recuts.splices import RecutConflict, apply_recut_instructions
from recuts.storage import (
    RecutDraft, RecutVersion, get_draft, get_publication, get_version,
    insert_draft, insert_publication, insert_version, require_original_master,
    update_head,
)
from recuts.voices import TakeVoice


class RecutVersionConflict(RecutConflict):
    pass


def open_recut(db: sqlite3.Connection, master_id: int) -> tuple[RecutDraft, RecutVersion]:
    if type(master_id) is not int or master_id <= 0:
        raise ValueError('master_id must be a positive integer')
    with db:
        db.execute('BEGIN IMMEDIATE')
        require_original_master(db, master_id)
        stored = get_master(db, master_id)
        manifest = stored.manifest
        revision = get_revision(db, manifest.revision_id)
        base = revision.layout
        voices: dict[int, list[TakeVoice]] = {}
        for span in manifest.take.spans:
            voices.setdefault(span.occurrence_id, []).append(
                TakeVoice(span.source_start, span.source_end,
                          manifest.take.take_id, span.take_start)
            )
        layout = RecutLayout(
            base.sample_rate,
            base.placements,
            dict(base.levels),
            base.next_occurrence,
            {key: tuple(sorted(excerpt, key=lambda voice: voice.asset_start))
             for key, excerpt in voices.items()},
        )
        draft, version = insert_draft(db, master_id, layout, frozenset(voices))
    return draft, version


def submit_recut_edits(db: sqlite3.Connection, recut_id: int, parent_version_id: int,
                       instructions: list[dict]) -> RecutVersion:
    if type(parent_version_id) is not int or parent_version_id <= 0:
        raise ValueError('parent_version_id must be a positive integer')
    operations = decode_recut_instructions(instructions)
    with db:
        db.execute('BEGIN IMMEDIATE')
        draft = get_draft(db, recut_id)
        if draft.head_version_id != parent_version_id:
            raise RecutVersionConflict('parent_version_id is not the current recut version')
        parent = get_version(db, parent_version_id)
        if parent.recut_id != recut_id:
            raise KeyError(f'unknown recut version {parent_version_id}')
        layout, restored = apply_recut_instructions(
            db, parent.layout, operations, draft.restored, draft.inherited,
        )
        version = insert_version(db, draft, parent_version_id, layout, restored)
        update_head(db, draft, version.version_id, restored)
    return version


def preview_recut(db: sqlite3.Connection, recut_id: int, version_id: int) -> dict:
    if type(version_id) is not int or version_id <= 0:
        raise ValueError('version_id must be a positive integer')
    get_draft(db, recut_id)
    version = get_version(db, version_id)
    if version.recut_id != recut_id:
        raise KeyError(f'unknown recut version {version_id}')
    rendered = render_recut(db, version.layout)
    return {
        'recut_id': recut_id, 'version_id': version_id,
        'sample_rate': rendered.sample_rate, 'frames': list(rendered.frames),
        'sources': list(rendered.sources),
    }


def publish_recut(db: sqlite3.Connection, recut_id: int, version_id: int) -> int:
    if type(version_id) is not int or version_id <= 0:
        raise ValueError('version_id must be a positive integer')
    with db:
        db.execute('BEGIN IMMEDIATE')
        draft = get_draft(db, recut_id)
        version = get_version(db, version_id)
        if version.recut_id != recut_id:
            raise KeyError(f'unknown recut version {version_id}')
        rendered = render_recut(db, version.layout)
        if rendered.sample_rate is None:
            raise ValueError('the recut scene has no sample rate')
        if len(rendered.frames) != scene_length(version.layout):
            raise sqlite3.IntegrityError('recut render length mismatch')
        original = get_master(db, draft.original_master_id)
        cursor = db.execute(
            'INSERT INTO masters(revision_id, manifest, frames) VALUES (?, ?, ?)',
            (original.manifest.revision_id, json.dumps({'recut': True}),
             json.dumps(list(rendered.frames))),
        )
        master_id = cursor.lastrowid
        insert_publication(
            db, master_id, draft, version, rendered.sample_rate,
            rendered.frames, rendered.sources,
        )
    return master_id


def listen_recut_master(db: sqlite3.Connection, master_id: int) -> dict | None:
    return get_publication(db, master_id)
