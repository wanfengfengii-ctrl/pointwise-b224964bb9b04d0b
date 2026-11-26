import json
import sqlite3
from dataclasses import asdict, dataclass

from edit.revisions import Revision
from media.provenance import SourceSpan
from mix.render import RenderedMix
from takes.coverage import CoverageSpan, WindowCoverage


@dataclass(frozen=True)
class TakeSource:
    take_id: int
    issued_revision_id: int
    window: tuple[int, int]
    spans: tuple[CoverageSpan, ...]


@dataclass(frozen=True)
class MasterManifest:
    scene: str
    revision_id: int
    sample_rate: int
    start: int
    end: int
    coverage: tuple[tuple[int, int], ...]
    sources: tuple[SourceSpan, ...]
    take: TakeSource


def make_manifest(revision: Revision, source: TakeSource, rendered: RenderedMix) -> MasterManifest:
    if (rendered.revision_id != revision.revision_id or rendered.start != 0
            or rendered.end != revision.length or len(rendered.frames) != revision.length
            or revision.layout.sample_rate is None):
        raise sqlite3.IntegrityError('render does not describe the complete revision')
    selected = tuple((span.occurrence_id, span.start, span.end) for span in source.spans)
    if not selected or selected != rendered.replacements:
        raise sqlite3.IntegrityError('render and take coverage disagree')
    recording_length = source.window[1] - source.window[0]
    if any(
        not 0 <= span.take_start < span.take_end <= recording_length
        or span.end - span.start != span.take_end - span.take_start
        for span in source.spans
    ):
        raise sqlite3.IntegrityError('take provenance is outside the recorded window')
    return MasterManifest(
        revision.scene, revision.revision_id, revision.layout.sample_rate,
        rendered.start, rendered.end, WindowCoverage(source.spans).intervals,
        rendered.sources, source,
    )


def encode_manifest(manifest: MasterManifest) -> str:
    return json.dumps(asdict(manifest))


def decode_manifest(value: str) -> MasterManifest:
    saved = json.loads(value)
    take = saved['take']
    saved['take'] = TakeSource(
        take['take_id'], take['issued_revision_id'], tuple(take['window']),
        tuple(CoverageSpan(**span) for span in take['spans']),
    )
    saved['coverage'] = tuple(tuple(interval) for interval in saved['coverage'])
    saved['sources'] = tuple(SourceSpan(**span) for span in saved['sources'])
    return MasterManifest(**saved)
