from dataclasses import dataclass


@dataclass(frozen=True)
class TrackLevel:
    percent: int = 100
    muted: bool = False

    def __post_init__(self) -> None:
        if type(self.percent) is not int or self.percent < 0:
            raise ValueError('percent must be a non-negative integer')
        if type(self.muted) is not bool:
            raise ValueError('muted must be a boolean')

    @property
    def audible(self) -> bool:
        return not self.muted and self.percent != 0


def scale_contribution(sample: int, level: TrackLevel) -> int:
    return sample * level.percent if level.audible else 0


def finalize_sample(total: int) -> int:
    magnitude = abs(total) // 100
    value = -magnitude if total < 0 else magnitude
    return max(-32768, min(32767, value))
