import sqlite3
from dataclasses import dataclass

from edit.revisions import get_revision
from edit.scenes import read_scene_head
from masters.catalog import get_master
from masters.manifest import MasterManifest, TakeSource
from masters.publish import publish_master
from mix.render import VoiceReplacement, render_mix
from mix.timeline import TimelineWindow
from takes.assignments import TakeConflict, get_assignment, record_adoption
from takes.coverage import resolve_window_coverage
from takes.returns import get_receipt


@dataclass(frozen=True)
class ApplyResult:
    master_id: int
    manifest: MasterManifest


def apply_take(db: sqlite3.Connection, take_id: int) -> ApplyResult:
    with db:
        # Both edits and adoption acquire the write transaction before reading the head.
        db.execute('BEGIN IMMEDIATE')
        assignment = get_assignment(db, take_id)
        if assignment.state == 'adopted':
            master = get_master(db, assignment.master_id)
            return ApplyResult(master.master_id, master.manifest)
        if assignment.state != 'received':
            raise TakeConflict('take has not been returned')
        receipt = get_receipt(db, take_id)
        if receipt is None:
            raise sqlite3.IntegrityError('received take is missing its receipt')

        window = assignment.window
        head = read_scene_head(db, window.scene)
        if head is None:
            raise sqlite3.IntegrityError('assignment has no scene head')
        revision = get_revision(db, head.revision_id)
        coverage = resolve_window_coverage(window, revision)
        replacements = tuple(
            VoiceReplacement(span.occurrence_id, span.start, receipt.frames[span.take_start:span.take_end])
            for span in coverage.spans
        )
        rendered = render_mix(db, revision, TimelineWindow(0, revision.length), replacements)
        source = TakeSource(take_id, window.revision_id, (window.start, window.end), coverage.spans)
        master = publish_master(db, revision, source, rendered)
        record_adoption(db, take_id, master.master_id)
    return ApplyResult(master.master_id, master.manifest)
