from takes.workbench import initialize_workspace
from tests.support import StudioCase, insert


class PlaybackTests(StudioCase):
    def _prepare(self):
        dialogue = self.asset([5, 6], 'dialogue')
        bed = self.asset([2, 3], 'room')
        first = self.edit([insert('dialogue', dialogue, 0, 2), insert('bed', bed, 0, 2)])
        take = self.issue(first['revision_id'], 0, 2)
        self.returned(take['take_id'], [50, 60])
        return dialogue, first, take['take_id'], self.apply(take['take_id'])

    def test_frozen_master_after_new_edit(self):
        _, first, take_id, adopted = self._prepare()
        master_path = f"/masters/{adopted['master_id']}"
        frozen = self.get(master_path)
        self.assertEqual(frozen['frames'], [52, 63])
        self.assertEqual(frozen['revision_id'], first['revision_id'])
        self.assertEqual(frozen['coverage'], [[0, 2]])
        self.assertEqual(frozen['take']['take_id'], take_id)
        self.assertEqual(frozen['sources'][0]['source'], 'room')
        occurrence = next(piece['occurrence_id'] for piece in first['placements'] if piece['track'] == 'dialogue')
        second = self.edit([{'op': 'move', 'occurrence_id': occurrence, 'at': 2}], first['revision_id'])
        self.studio.restart()
        self.assertEqual(self.get(master_path), frozen)
        self.assertEqual(self.apply(take_id), adopted)
        self.assertEqual(self.preview(first['revision_id'], 0, 2)['frames'], [7, 9])
        self.assertEqual(self.preview(second['revision_id'], 0, 4)['frames'], [2, 3, 5, 6])
        self.assertEqual(self.get('/masters')['master_ids'], [adopted['master_id']])

    def test_unknown_master(self):
        self.assertEqual(self.get('/masters/100', 404)['error'], 'not_found')
        self.assertEqual(self.get('/masters')['master_ids'], [])

    def test_repeated_initialization(self):
        asset, first, adopted_take, adopted = self._prepare()
        second = self.edit([
            {'op': 'level', 'track': 'bed', 'percent': 0, 'muted': True},
        ], first['revision_id'])
        received = self.issue(second['revision_id'], 0, 1)['take_id']
        self.returned(received, [88])
        paths = [
            f'/assets/{asset}', '/scenes/bridge', f"/revisions/{second['revision_id']}",
            f'/takes/{adopted_take}', f'/takes/{received}', f"/masters/{adopted['master_id']}",
        ]
        before = [self.get(path) for path in paths]
        self.studio.stop()
        initialize_workspace(self.studio.database)
        initialize_workspace(self.studio.database)
        self.studio.start()
        self.assertEqual([self.get(path) for path in paths], before)
        self.assertEqual(self.preview(second['revision_id'], 0, 2)['frames'], [5, 6])
        new = self.apply(received)
        self.assertEqual(self.get(f"/masters/{new['master_id']}")['frames'], [88, 6])
        self.assertEqual(self.get('/masters')['master_ids'], [adopted['master_id'], new['master_id']])
