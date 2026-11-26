from dataclasses import dataclass

from edit.instructions import EditInstruction, _FIELDS, _decode_item


@dataclass(frozen=True)
class RecutInstruction:
    operation: str
    fields: dict


def decode_recut_instructions(value: object) -> tuple[RecutInstruction, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError('instructions must be a non-empty array')
    return tuple(_decode_recut_item(item) for item in value)


def _decode_recut_item(item: object) -> RecutInstruction:
    if not isinstance(item, dict):
        raise ValueError('each instruction must be an object')
    operation = item.get('op')
    if operation == 'restore_dialogue':
        if item.keys() != {'op'}:
            raise ValueError('invalid fields for restore_dialogue')
        return RecutInstruction(operation, {})
    if not isinstance(operation, str) or operation not in _FIELDS:
        raise ValueError('unknown edit operation')
    decoded: EditInstruction = _decode_item(item)
    return RecutInstruction(decoded.operation, decoded.fields)
