from concurrent.futures import ThreadPoolExecutor

from tests.support import CommitGate, StudioCase, insert


class DubbingTests(StudioCase):
    def _line(self, frames):
        asset = self.asset(frames)
        return asset, self.edit([insert('dialogue', asset, 0, len(frames))])

    def _assert_master(self, result, revision, frames, coverage):
        self.assertEqual(result['revision_id'], revision)
        self.assertEqual(result['coverage'], coverage)
        master = self.get(f"/masters/{result['master_id']}")
        self.assertEqual(master.pop('frames'), frames)
        self.assertEqual(master, result)

    def test_same_revision_take(self):
        dialogue = self.asset([10, 20, 30, 40])
        bed = self.asset([1, 2, 3, 4], 'music')
        revision = self.edit([insert('dialogue', dialogue, 0, 4), insert('bed', bed, 0, 4)])['revision_id']
        issued = self.issue(revision, 1, 3)
        take_id = issued['take_id']
        self.assertEqual((issued['length'], issued['state']), (2, 'pending'))
        self.apply(take_id, 409)
        self.assertEqual(self.get('/masters')['master_ids'], [])
        self.returned(take_id, [70, 80])
        result = self.apply(take_id)
        self._assert_master(result, revision, [11, 72, 83, 44], [[1, 3]])
        self.assertEqual(result['take']['issued_revision_id'], revision)
        self.assertEqual(result['take']['window'], [1, 3])
        self.assertEqual(self.get(f'/takes/{take_id}')['state'], 'adopted')

    def test_replaces_only_dialogue(self):
        dialogue = self.asset([10, 20])
        bed = self.asset([1, 2, 3])
        revision = self.edit([
            insert('dialogue', dialogue, 0, 1), insert('dialogue', dialogue, 1, 2, at=2),
            insert('bed', bed, 0, 3),
        ])['revision_id']
        take_id = self.issue(revision, 0, 3)['take_id']
        self.returned(take_id, [70, 99, 80])
        result = self.apply(take_id)
        self._assert_master(result, revision, [71, 2, 83], [[0, 1], [2, 3]])
        self.assertEqual([span['track'] for span in result['sources']], ['bed'])

    def test_issue_checks_dialogue_window(self):
        asset = self.asset([6, 7])
        revision = self.edit([insert('dialogue', asset, 0, 2, at=4)])['revision_id']
        self.issue(revision, 0, 4, 400)
        self.issue(revision, 4, 7, 400)
        self.issue(revision, True, 6, 400)
        self.issue(revision + 1, 0, 1, 404)
        self.get('/takes/1', 404)
        issued = self.issue(revision, 2, 6)
        self.assertEqual((issued['start'], issued['end'], issued['length']), (2, 6, 4))
        self.assertEqual(issued['revision_id'], revision)

    def test_wrong_take_length(self):
        _, revision = self._line([20] * 6)
        take_id = self.issue(revision['revision_id'], 0, 6)['take_id']
        error = self.returned(take_id, [1, 2, 3, 4, 5], 400)
        self.assertIn('6', error['message'])
        self.assertEqual(self.get(f'/takes/{take_id}')['state'], 'pending')
        self.assertIsNone(self.get(f'/takes/{take_id}')['receipt'])
        self.returned(take_id, [11, 12, 13, 14, 15, 16])
        result = self.apply(take_id)
        self._assert_master(result, revision['revision_id'], [11, 12, 13, 14, 15, 16], [[0, 6]])

    def test_receipt_remains_pending(self):
        _, revision = self._line([6] * 6)
        take_id = self.issue(revision['revision_id'], 0, 6)['take_id']
        self.returned(take_id, [99] * 5, 400)
        self.studio.restart()
        pending = self.get(f'/takes/{take_id}')
        self.assertEqual((pending['state'], pending['receipt']), ('pending', None))
        self.returned(take_id, [True] * 6, 400)
        self.returned(take_id + 1, [7] * 6, 404)
        self.returned(take_id, [7] * 6)
        self.returned(take_id, [9] * 6, 409)
        self._assert_master(self.apply(take_id), revision['revision_id'], [7] * 6, [[0, 6]])

    def test_take_follows_moved_line(self):
        _, first = self._line([10, 20])
        occurrence = first['placements'][0]['occurrence_id']
        take_id = self.issue(first['revision_id'], 0, 2)['take_id']
        other = self.asset([30, 40], 'old position')
        second = self.edit([
            {'op': 'move', 'occurrence_id': occurrence, 'at': 4},
            insert('dialogue', other, 0, 2),
        ], first['revision_id'])
        self.returned(take_id, [71, 72])
        result = self.apply(take_id)
        self._assert_master(result, second['revision_id'], [30, 40, 0, 0, 71, 72], [[4, 6]])
        self.assertEqual(second['placements'][-1]['occurrence_id'], occurrence)
        self.assertEqual(result['take']['spans'][0]['occurrence_id'], occurrence)
        self.assertEqual(self.preview(first['revision_id'], 0, 2)['frames'], [10, 20])

    def test_removed_window_conflict(self):
        _, first = self._line([10, 20])
        take_id = self.issue(first['revision_id'], 0, 2)['take_id']
        revision = self.edit([{'op': 'remove', 'track': 'dialogue', 'start': 0, 'end': 2}], first['revision_id'])
        self.assertEqual(revision['length'], 0)
        self.returned(take_id, [1, 2])
        self.apply(take_id, 409)
        self.assertEqual(self.get('/masters')['master_ids'], [])
        self.assertEqual(self.get(f'/takes/{take_id}')['state'], 'received')

    def test_no_survivor_with_other_dialogue(self):
        original, first = self._line([8, 8])
        take_id = self.issue(first['revision_id'], 0, 2)['take_id']
        second = self.edit([
            {'op': 'remove', 'track': 'dialogue', 'start': 0, 'end': 2},
            insert('dialogue', original, 0, 2),
        ], first['revision_id'])
        self.returned(take_id, [71, 72])
        self.apply(take_id, 409)
        self.assertEqual(self.get('/masters')['master_ids'], [])
        self.assertEqual(self.preview(second['revision_id'], 0, 2)['frames'], [8, 8])

    def test_retry_failed_master(self):
        _, revision = self._line([20, 30])
        take_id = self.issue(revision['revision_id'], 0, 2)['take_id']
        self.returned(take_id, [70, 80])
        self.studio.reject_master_commit()
        try:
            result = self.apply(take_id, 500)
            self.assertEqual(result['error'], 'storage_failure')
            self.assertEqual(self.get('/masters')['master_ids'], [])
            saved = self.get(f'/takes/{take_id}')
            self.assertEqual((saved['state'], saved['master_id']), ('received', None))
            self.assertEqual(saved['receipt']['frames'], [70, 80])
        finally:
            self.studio.allow_master_commit()
        self.studio.restart()
        result = self.apply(take_id)
        self._assert_master(result, revision['revision_id'], [70, 80], [[0, 2]])
        self.assertEqual(self.apply(take_id), result)
        self.assertEqual(self.get('/masters')['master_ids'], [result['master_id']])

    def _equal_copy_case(self):
        dialogue = self.asset([20] * 6, 'dialogue')
        bed = self.asset([0] * 6, 'room tone')
        first = self.edit([insert('dialogue', dialogue, 0, 6), insert('bed', bed, 0, 6)])
        take_id = self.issue(first['revision_id'], 0, 6)['take_id']
        replacement = [
            {'op': 'remove', 'track': 'dialogue', 'start': 2, 'end': 4},
            insert('dialogue', dialogue, 2, 4, at=2),
        ]
        return first, take_id, replacement

    def test_equal_copy_uses_original_offsets(self):
        first, take_id, replacement = self._equal_copy_case()
        unchanged_take = self.issue(first['revision_id'], 0, 6)['take_id']
        recording = [11, 12, 13, 14, 15, 16]
        self.returned(unchanged_take, recording)
        unchanged = self.apply(unchanged_take)
        self._assert_master(unchanged, first['revision_id'], recording, [[0, 6]])

        second = self.edit(replacement, first['revision_id'])
        self.assertEqual(self.preview(second['revision_id'], 0, 6)['frames'], [20] * 6)
        self.returned(take_id, recording)
        result = self.apply(take_id)
        master = self.get(f"/masters/{result['master_id']}")
        observed = (result['coverage'], result['revision_id'], master['frames'])
        expected = ([[0, 2], [4, 6]], second['revision_id'], [11, 12, 20, 20, 15, 16])
        self.assertEqual(observed, expected, 'EQUAL_COPY_COVERAGE')
        self.assertEqual(result['take']['issued_revision_id'], first['revision_id'])
        self.assertEqual([(span['take_start'], span['take_end']) for span in result['take']['spans']],
                         [(0, 2), (4, 6)])
        self.assertEqual([span['occurrence_id'] for span in result['take']['spans']],
                         [unchanged['take']['spans'][0]['occurrence_id']] * 2)

    def test_reordered_survivors_keep_take_offsets(self):
        first, take_id, replacement = self._equal_copy_case()
        second = self.edit(replacement, first['revision_id'])
        occurrence = next(item['occurrence_id'] for item in first['placements'] if item['track'] == 'dialogue')
        third = self.edit([
            {'op': 'move', 'occurrence_id': occurrence, 'piece_start': 0, 'at': 6},
            {'op': 'move', 'occurrence_id': occurrence, 'piece_start': 4, 'at': 0},
            {'op': 'move', 'occurrence_id': occurrence, 'piece_start': 6, 'at': 4},
        ], second['revision_id'])
        self.returned(take_id, [11, 12, 13, 14, 15, 16])
        result = self.apply(take_id)
        self._assert_master(result, third['revision_id'], [15, 16, 20, 20, 11, 12], [[0, 2], [4, 6]])
        self.assertEqual([span['take_start'] for span in result['take']['spans']], [4, 0])

    def _commit_order(self, edit_first):
        first, take_id, replacement = self._equal_copy_case()
        self.returned(take_id, [11, 12, 13, 14, 15, 16])
        edit = ('POST', '/edits', {
            'scene': 'bridge', 'parent_revision_id': first['revision_id'], 'instructions': replacement,
        })
        apply = ('POST', '/takes/apply', {'take_id': take_id})
        leader, follower = (edit, apply) if edit_first else (apply, edit)
        gate = CommitGate()
        self.studio.trace = gate
        try:
            with ThreadPoolExecutor(max_workers=2) as requests:
                first_request = requests.submit(self.studio.call, *leader)
                try:
                    self.assertTrue(gate.at_commit.wait(5), 'first writer did not reach COMMIT')
                    second_request = requests.submit(self.studio.call, *follower)
                    self.assertTrue(gate.second_begin.wait(5), 'second writer did not attempt to begin')
                    self.assertEqual(self.get('/masters')['master_ids'], [])
                    self.assertEqual(self.get('/scenes/bridge')['revision_id'], first['revision_id'])
                finally:
                    gate.release.set()
                first_status, first_result = first_request.result()
                second_status, second_result = second_request.result()
        finally:
            self.studio.trace = None
        self.assertFalse(gate.timed_out.is_set())
        self.assertEqual((first_status, second_status), (201, 201), (first_result, second_result))
        revised, applied = (first_result, second_result) if edit_first else (second_result, first_result)
        self.assertEqual(self.get('/scenes/bridge')['revision_id'], revised['revision_id'])
        before = self.get(f"/masters/{applied['master_id']}")
        if edit_first:
            self._assert_master(applied, revised['revision_id'], [11, 12, 20, 20, 15, 16], [[0, 2], [4, 6]])
        else:
            self._assert_master(applied, first['revision_id'], [11, 12, 13, 14, 15, 16], [[0, 6]])
        self.assertEqual(before['take']['issued_revision_id'], first['revision_id'])
        self.edit([{'op': 'level', 'track': 'dialogue', 'percent': 0, 'muted': True}], revised['revision_id'])
        self.studio.restart()
        self.assertEqual(self.get(f"/masters/{applied['master_id']}"), before)

    def test_edit_commits_first(self):
        self._commit_order(edit_first=True)

    def test_apply_commits_first(self):
        self._commit_order(edit_first=False)
