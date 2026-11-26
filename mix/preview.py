import sqlite3
from dataclasses import asdict

from edit.revisions import get_revision
from mix.render import render_mix
from mix.timeline import validate_listen_window


def preview_revision(db: sqlite3.Connection, revision_id: int, start: int, end: int) -> dict:
    revision = get_revision(db, revision_id)
    window = validate_listen_window(revision, start, end)
    rendered = render_mix(db, revision, window)
    return {
        'revision_id': revision_id,
        'scene': revision.scene,
        'sample_rate': revision.layout.sample_rate,
        'start': window.start,
        'end': window.end,
        'frames': rendered.frames,
        'sources': [asdict(span) for span in rendered.sources],
    }
