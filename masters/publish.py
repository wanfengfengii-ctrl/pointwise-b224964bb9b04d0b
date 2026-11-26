import sqlite3

from edit.revisions import Revision
from masters.catalog import StoredMaster, insert_master
from masters.manifest import TakeSource, make_manifest
from mix.render import RenderedMix


def publish_master(db: sqlite3.Connection, revision: Revision,
                   source: TakeSource, rendered: RenderedMix) -> StoredMaster:
    if not db.in_transaction:
        raise sqlite3.ProgrammingError('publishing requires an adoption transaction')
    manifest = make_manifest(revision, source, rendered)
    return insert_master(db, manifest, rendered.frames)
