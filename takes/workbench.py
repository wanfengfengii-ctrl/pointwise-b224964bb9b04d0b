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
    if collection not in ('assets', 'revisions', 'takes', 'masters'):
        raise KeyError('unknown route')
    if not key.isascii() or not key.isdecimal() or int(key) <= 0:
        raise ValueError('path identifier must be a positive integer')
    identifier = int(key)

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
            return listen_master(db, identifier)


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
            except (RevisionConflict, TakeConflict) as exc:
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
