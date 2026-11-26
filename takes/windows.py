from dataclasses import dataclass

from edit.placements import Placement, clip_placement
from edit.revisions import Revision
from mix.timeline import validate_listen_window


@dataclass(frozen=True)
class RecordingWindow:
    revision_id: int
    scene: str
    sample_rate: int
    start: int
    end: int
    dialogue: tuple[Placement, ...]

    @property
    def length(self) -> int:
        return self.end - self.start


def capture_recording_window(revision: Revision, start: int, end: int) -> RecordingWindow:
    window = validate_listen_window(revision, start, end)
    dialogue = []
    for placement in revision.layout.placements:
        if placement.track == 'dialogue':
            piece = clip_placement(placement, window.start, window.end)
            if piece is not None:
                dialogue.append(piece)
    if not dialogue:
        raise ValueError('the recording window must intersect dialogue')
    return RecordingWindow(
        revision.revision_id, revision.scene, revision.layout.sample_rate,
        window.start, window.end, tuple(dialogue),
    )
