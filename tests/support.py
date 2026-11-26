import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread, get_ident
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from takes.workbench import serve_workbench


class Workbench:
    def __init__(self, database: Path):
        self.database = database
        self.server = None
        self.thread = None
        self.trace = None

    def start(self):
        self.server = serve_workbench(self.database, trace_sql=self._trace)
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = None
        self.thread = None

    def restart(self):
        self.stop()
        self.start()

    def _trace(self, sql):
        if self.trace is not None:
            self.trace(sql)

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        request = Request(
            f'http://127.0.0.1:{self.server.server_port}{path}', data=data, method=method,
            headers={'Content-Type': 'application/json'},
        )
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as exc:
            response = exc
        with response:
            return response.code, json.load(response)

    def reject_master_commit(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('''
                CREATE TABLE permitted_test_masters (id INTEGER PRIMARY KEY);
                CREATE TABLE test_master_guard (
                    id INTEGER REFERENCES permitted_test_masters(id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER test_reject_master AFTER INSERT ON masters
                BEGIN
                    INSERT INTO test_master_guard(id) VALUES (new.id);
                END;
            ''')

    def allow_master_commit(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('''
                DROP TRIGGER test_reject_master;
                DROP TABLE test_master_guard;
                DROP TABLE permitted_test_masters;
            ''')


class CommitGate:
    def __init__(self):
        self.writer = None
        self.at_commit = Event()
        self.second_begin = Event()
        self.release = Event()
        self.timed_out = Event()

    def __call__(self, statement):
        if statement == 'BEGIN IMMEDIATE':
            if self.writer is None:
                self.writer = get_ident()
            elif self.writer != get_ident():
                self.second_begin.set()
        elif statement == 'COMMIT' and self.writer == get_ident():
            self.at_commit.set()
            if not self.release.wait(10):
                self.timed_out.set()


def insert(track, asset_id, start, end, at=0):
    return {
        'op': 'insert', 'track': track, 'asset_id': asset_id,
        'source_start': start, 'source_end': end, 'at': at,
    }


class StudioCase(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.studio = Workbench(directory / 'studio.sqlite')
        self.studio.start()
        self.addCleanup(self.studio.stop)

    def post(self, path, body, status=201):
        actual, result = self.studio.call('POST', path, body)
        self.assertEqual(actual, status, result)
        return result

    def get(self, path, status=200):
        actual, result = self.studio.call('GET', path)
        self.assertEqual(actual, status, result)
        return result

    def asset(self, frames, source='original', rate=48000):
        return self.post('/assets', {'source': source, 'sample_rate': rate, 'frames': frames})['asset_id']

    def edit(self, instructions, parent=None, scene='bridge', status=201):
        return self.post('/edits', {
            'scene': scene, 'parent_revision_id': parent, 'instructions': instructions,
        }, status)

    def preview(self, revision_id, start, end, status=200):
        return self.post('/preview', {'revision_id': revision_id, 'start': start, 'end': end}, status)

    def issue(self, revision_id, start, end, status=201):
        return self.post('/takes', {'revision_id': revision_id, 'start': start, 'end': end}, status)

    def returned(self, take_id, frames, status=201):
        return self.post('/takes/return', {'take_id': take_id, 'frames': frames}, status)

    def apply(self, take_id, status=201):
        return self.post('/takes/apply', {'take_id': take_id}, status)
