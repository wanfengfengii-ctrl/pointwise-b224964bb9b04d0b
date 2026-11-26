import argparse
import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from os import PathLike
from urllib.parse import unquote, urlsplit

from edit.revisions import Revision, get_revision, initialize_revisions, submit_revision
from edit.scenes import RevisionConflict, initialize_scenes, read_scene_head
from masters.catalog import initialize_masters, list_master_ids
from masters.playback import listen_master
from media.catalog import get_asset, register_asset
from media.repository import initialize_assets
from mix.preview import preview_revision
from recuts.service import (
    listen_recut_master, open_recut, preview_recut, publish_recut, submit_recut_edits,
)
from recuts.splices import RecutConflict
from recuts.storage import get_draft, initialize_recuts
from takes.apply import apply_take
from takes.assignments import Assignment, TakeConflict, get_assignment, initialize_assignments, issue_take
from takes.returns import accept_return, get_receipt, initialize_receipts


def _connect(database: str | PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(database, timeout=15)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def initialize_workspace(database: str | PathLike[str]) -> None:
    with closing(_connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        initialize_assets(db)
        initialize_revisions(db)
        initialize_scenes(db)
        initialize_masters(db)
        initialize_assignments(db)
        initialize_receipts(db)
        initialize_recuts(db)


def dispatch_json(db: sqlite3.Connection, method: str, path: str,
                  body: object = None) -> tuple[int, dict]:
    route = urlsplit(path).path
    if method == 'POST':
        return _post(db, route, body)
    if method == 'GET':
        return 200, _get(db, route)
    raise KeyError('unknown route')


def _fields(body: object, *names: str) -> tuple:
    if not isinstance(body, dict) or body.keys() != set(names):
        raise ValueError('expected an object containing ' + ', '.join(names))
    return tuple(body[name] for name in names)


def _post(db: sqlite3.Connection, route: str, body: object) -> tuple[int, dict]:
    match route:
        case '/assets':
            asset = register_asset(db, *_fields(body, 'source', 'sample_rate', 'frames'))
            return 201, {
                'asset_id': asset.asset_id, 'source': asset.source, 'sample_rate': asset.sample_rate,
                'length': len(asset.frames),
            }
        case '/edits':
            revision = submit_revision(db, *_fields(body, 'scene', 'parent_revision_id', 'instructions'))
            return 201, _revision_view(revision)
        case '/preview':
            return 200, preview_revision(db, *_fields(body, 'revision_id', 'start', 'end'))
        case '/takes':
            assignment = issue_take(db, *_fields(body, 'revision_id', 'start', 'end'))
            return 201, _assignment_view(assignment)
        case '/takes/return':
            receipt = accept_return(db, *_fields(body, 'take_id', 'frames'))
            return 201, {'take_id': receipt.take_id, 'length': len(receipt.frames), 'state': 'received'}
        case '/takes/apply':
            result = apply_take(db, *_fields(body, 'take_id'))
            return 201, {'master_id': result.master_id, **asdict(result.manifest)}
        case _:
            if route == '/recuts':
                draft, version = open_recut(db, *_fields(body, 'master_id'))
                return 201, {
                    'recut_id': draft.recut_id,
                    'original_master_id': draft.original_master_id,
                    'version_id': version.version_id,
                }
            parts = route.split('/')
            if (len(parts) == 3 and parts[0] == '' and parts[1] == 'recuts'
                    and parts[2].isascii() and parts[2].isdecimal() and int(parts[2]) > 0):
                raise KeyError('use a recut sub-resource')
            if len(parts) == 4 and parts[0] == '' and parts[1] == 'recuts' and parts[3] in (
                'edits', 'preview', 'publish',
            ):
                recut_id = _path_id(parts[2])
                get_draft(db, recut_id)
                match parts[3]:
                    case 'edits':
                        version = submit_recut_edits(
                            db, recut_id, *_fields(body, 'parent_version_id', 'instructions'),
                        )
                        return 201, {
                            'version_id': version.version_id,
                            'placements': [_recut_placement_view(item) for item in version.layout.placements],
                        }
                    case 'preview':
                        return 200, preview_recut(db, recut_id, *_fields(body, 'version_id'))
                    case 'publish':
                        return 201, {'master_id': publish_recut(db, recut_id, *_fields(body, 'version_id'))}
            raise KeyError('unknown route')


def _get(db: sqlite3.Connection, route: str) -> dict:
    if route == '/masters':
        return {'master_ids': list_master_ids(db)}

    parts = route.split('/')
    if len(parts) != 3 or not parts[2]:
        raise KeyError('unknown route')
    _, collection, key = parts
    if collection == 'scenes':
        head = read_scene_head(db, unquote(key, errors='strict'))
        if head is None:
            raise KeyError('unknown scene')
        return asdict(head)
    if collection == 'recuts':
        recut_id = _path_id(key)
        draft = get_draft(db, recut_id)
        return {
            'recut_id': draft.recut_id,
            'original_master_id': draft.original_master_id,
            'version_id': draft.head_version_id,
        }
    if collection not in ('assets', 'revisions', 'takes', 'masters'):
        raise KeyError('unknown route')
    identifier = _path_id(key)

    match collection:
        case 'assets':
            return asdict(get_asset(db, identifier))
        case 'revisions':
            return _revision_view(get_revision(db, identifier))
        case 'takes':
            with db:
                db.execute('BEGIN')
                assignment = get_assignment(db, identifier)
                receipt = get_receipt(db, identifier)
                return {
                    **_assignment_view(assignment), 'master_id': assignment.master_id,
                    'receipt': None if receipt is None else asdict(receipt),
                }
        case 'masters':
            recut_master = listen_recut_master(db, identifier)
            if recut_master is not None:
                return recut_master
            return listen_master(db, identifier)


def _path_id(key: str) -> int:
    if not key.isascii() or not key.isdecimal() or int(key) <= 0:
        raise ValueError('path identifier must be a positive integer')
    return int(key)


def _recut_placement_view(placement) -> dict:
    return {
        'occurrence_id': placement.occurrence_id, 'track': placement.track,
        'asset_id': placement.asset_id, 'source_start': placement.source_start,
        'source_end': placement.source_end, 'start': placement.start,
        'end': placement.end,
    }


def _revision_view(revision: Revision) -> dict:
    return {
        'revision_id': revision.revision_id, 'scene': revision.scene,
        'parent_revision_id': revision.parent_revision_id, 'length': revision.length,
        'sample_rate': revision.layout.sample_rate,
        'placements': [dict(asdict(item), end=item.end) for item in revision.layout.placements],
        'levels': {track: asdict(level) for track, level in revision.layout.levels.items()},
    }


def _assignment_view(assignment: Assignment) -> dict:
    window = assignment.window
    return {
        'take_id': assignment.take_id, 'state': assignment.state,
        'revision_id': window.revision_id, 'sample_rate': window.sample_rate,
        'start': window.start, 'end': window.end, 'length': window.length,
    }


def serve_workbench(database: str | PathLike[str], port: int = 0, *,
                    trace_sql: Callable[[str], None] | None = None) -> ThreadingHTTPServer:
    initialize_workspace(database)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._dispatch('GET')

        def do_POST(self):
            self._dispatch('POST')

        def _dispatch(self, method):
            try:
                body = self._read_json() if method == 'POST' else None
                with closing(_connect(database)) as db:
                    if trace_sql is not None:
                        db.set_trace_callback(trace_sql)
                    status, result = dispatch_json(db, method, self.path, body)
            except ValueError as exc:
                status, result = 400, {'error': 'invalid_request', 'message': str(exc)}
            except KeyError as exc:
                status, result = 404, {'error': 'not_found', 'message': str(exc.args[0])}
            except (RevisionConflict, TakeConflict, RecutConflict) as exc:
                status, result = 409, {'error': 'conflict', 'message': str(exc)}
            except sqlite3.Error:
                status, result = 500, {'error': 'storage_failure', 'message': 'database operation failed'}

            data = json.dumps(result).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self):
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0:
                raise ValueError('a JSON request body is required')
            return json.loads(self.rfile.read(length).decode('utf-8'))

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description='Local radio drama recording workbench')
    parser.add_argument('--database', required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    with serve_workbench(args.database, args.port) as server:
        print(f'Listening on http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
