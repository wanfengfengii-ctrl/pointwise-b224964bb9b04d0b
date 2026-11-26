from dataclasses import dataclass

from mix.levels import TrackLevel


@dataclass(frozen=True)
class EditInstruction:
    operation: str
    fields: dict


_FIELDS = {
    'insert': ('track', 'asset_id', 'source_start', 'source_end', 'at'),
    'copy': ('occurrence_id', 'at'),
    'move': ('occurrence_id', 'at'),
    'remove': ('track', 'start', 'end'),
    'level': ('track', 'percent', 'muted'),
}


def decode_instructions(value: object) -> tuple[EditInstruction, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError('instructions must be a non-empty array')
    return tuple(_decode_item(item) for item in value)


def _decode_item(item: object) -> EditInstruction:
    if not isinstance(item, dict):
        raise ValueError('each instruction must be an object')
    operation = item.get('op')
    if not isinstance(operation, str) or operation not in _FIELDS:
        raise ValueError('unknown edit operation')

    fields = {key: value for key, value in item.items() if key != 'op'}
    required = set(_FIELDS[operation])
    optional = {'piece_start'} if operation in ('move', 'copy') else set()
    if not required <= fields.keys() <= required | optional:
        raise ValueError(f'invalid fields for {operation}')

    if 'track' in fields:
        track = fields['track']
        if not isinstance(track, str) or not track.strip():
            raise ValueError('track must be a non-empty string')
    if operation == 'level':
        setting = TrackLevel(fields['percent'], fields['muted'])
        return EditInstruction(operation, {'track': fields['track'], 'setting': setting})

    for key, value in fields.items():
        if key == 'track':
            continue
        minimum = 1 if key in ('asset_id', 'occurrence_id') else 0
        if type(value) is not int or value < minimum:
            raise ValueError(f'invalid integer for {key}')
    return EditInstruction(operation, fields)
