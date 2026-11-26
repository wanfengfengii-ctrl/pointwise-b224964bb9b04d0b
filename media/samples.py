def normalize_samples(frames: object) -> tuple[int, ...]:
    if not isinstance(frames, (list, tuple)):
        raise ValueError('frames must be an array of integers')
    if any(type(frame) is not int for frame in frames):
        raise ValueError('every frame must be an integer')
    return tuple(frames)


def validate_sample_rate(sample_rate: object) -> int:
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError('sample_rate must be a positive integer')
    return sample_rate
