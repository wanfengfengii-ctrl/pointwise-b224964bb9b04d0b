from tests.support import StudioCase, insert


class EditingTests(StudioCase):
    def test_preview_with_clipping(self):
        dialogue = self.asset([32000, -32000, 0], 'dialogue')
        bed = self.asset([1000, -1000, 0], 'bed')
        revision = self.edit([insert('dialogue', dialogue, 0, 3), insert('bed', bed, 0, 3)])
        preview = self.preview(revision['revision_id'], 0, 3)
        self.assertEqual(preview['frames'], [32767, -32768, 0])
        self.assertEqual(preview['revision_id'], revision['revision_id'])
        self.assertEqual([(span['source'], span['start'], span['end']) for span in preview['sources']],
                         [('bed', 0, 3), ('dialogue', 0, 3)])
        self.assertEqual(preview, self.preview(revision['revision_id'], 0, 3))

    def test_register_rejects_invalid_values(self):
        good = self.asset([7, 8], 'valid source')
        for rate, frames in [(True, [1]), (0, [1]), (1.0, [1]), (None, [1]),
                             (48000, [True]), (48000, [1.5]), (48000, [None]), (48000, None)]:
            with self.subTest(rate=rate, frames=frames):
                self.post('/assets', {'source': 'invalid', 'sample_rate': rate, 'frames': frames}, 400)
        self.assertEqual(self.get(f'/assets/{good}')['frames'], [7, 8])
        revision = self.edit([insert('dialogue', good, 0, 2)])['revision_id']
        self.assertEqual(self.preview(revision, 0, 2)['frames'], [7, 8])

    def test_rejects_mixed_sample_rates(self):
        dialogue = self.asset([9])
        mismatch = self.asset([12], rate=44100)
        revision = self.edit([insert('dialogue', dialogue, 0, 1)])['revision_id']
        self.edit([insert('bed', mismatch, 0, 1)], revision, status=400)
        self.assertEqual(self.get('/scenes/bridge')['revision_id'], revision)
        self.assertEqual(self.preview(revision, 0, 1)['frames'], [9])

    def test_reject_out_of_bounds_cut(self):
        asset = self.asset([7, 8, 9])
        revision = self.edit([insert('dialogue', asset, 1, 3)])['revision_id']
        before = self.preview(revision, 0, 2)
        error = self.edit([insert('bed', asset, 1, 4)], revision, status=400)
        self.assertEqual(error['error'], 'invalid_request')
        self.assertEqual(before['frames'], [8, 9])
        self.assertEqual(before, self.preview(revision, 0, 2))
        self.assertEqual(self.get('/scenes/bridge')['revision_id'], revision)

    def test_reject_stale_parent(self):
        asset = self.asset([14, 15])
        first = self.edit([insert('dialogue', asset, 0, 2)])
        occurrence = first['placements'][0]['occurrence_id']
        move = {'op': 'move', 'occurrence_id': occurrence, 'at': 1}
        second = self.edit([move], first['revision_id'])
        self.edit([move], first['revision_id'], status=409)
        current = self.get('/scenes/bridge')
        self.assertEqual(current['revision_id'], second['revision_id'])
        self.assertEqual(self.get(f"/revisions/{second['revision_id']}")['parent_revision_id'], first['revision_id'])
        self.assertEqual(self.preview(first['revision_id'], 0, 2)['frames'], [14, 15])
        self.assertEqual(self.preview(second['revision_id'], 0, 3)['frames'], [0, 14, 15])

    def test_failed_batch_keeps_head(self):
        asset = self.asset([23, 24])
        first = self.edit([insert('dialogue', asset, 0, 2)])
        occurrence = first['placements'][0]['occurrence_id']
        move = {'op': 'move', 'occurrence_id': occurrence, 'at': 4}
        self.edit([move, insert('bed', asset + 999, 0, 1)], first['revision_id'], status=404)
        self.studio.restart()
        self.assertEqual(self.get('/scenes/bridge')['revision_id'], first['revision_id'])
        self.get(f"/revisions/{first['revision_id'] + 1}", 404)
        self.assertEqual(self.preview(first['revision_id'], 0, 2)['frames'], [23, 24])
        second = self.edit([move], first['revision_id'])
        self.assertEqual(self.preview(second['revision_id'], 0, 6)['frames'], [0, 0, 0, 0, 23, 24])

    def test_copy_has_own_occurrence(self):
        asset = self.asset([8, 8])
        first = self.edit([insert('dialogue', asset, 0, 2)])
        occurrence = first['placements'][0]['occurrence_id']
        second = self.edit([{'op': 'copy', 'occurrence_id': occurrence, 'at': 2}], first['revision_id'])
        preview = self.preview(second['revision_id'], 0, 4)
        first_span, second_span = preview['sources']
        self.assertEqual(preview['frames'], [8, 8, 8, 8])
        self.assertEqual(first_span['occurrence_id'], occurrence)
        self.assertNotEqual(second_span['occurrence_id'], occurrence)
        self.assertEqual([span['asset_id'] for span in preview['sources']], [asset, asset])
        self.assertEqual([(span['source_start'], span['source_end']) for span in preview['sources']],
                         [(0, 2), (0, 2)])

    def test_window_uses_scene_coordinates(self):
        asset = self.asset([6, 7, 8, 9])
        revision = self.edit([insert('dialogue', asset, 0, 4, at=4)])['revision_id']
        full = self.preview(revision, 0, 8)
        part = self.preview(revision, 5, 8)
        self.assertEqual(full['frames'], [0, 0, 0, 0, 6, 7, 8, 9])
        self.assertEqual(part['frames'], [7, 8, 9])
        self.assertEqual(part['frames'], full['frames'][5:8])
        span, = part['sources']
        self.assertEqual((span['start'], span['end'], span['source_start'], span['source_end']), (5, 8, 1, 4))
        self.preview(revision, 8, 9, 400)

    def test_level_and_mute(self):
        dialogue = self.asset([-3, 3, -1])
        bed = self.asset([300, 300, 300])
        revision = self.edit([
            insert('dialogue', dialogue, 0, 3), insert('bed', bed, 0, 3),
            {'op': 'level', 'track': 'dialogue', 'percent': 50, 'muted': False},
            {'op': 'level', 'track': 'bed', 'percent': 100, 'muted': True},
        ])['revision_id']
        preview = self.preview(revision, 0, 3)
        self.assertEqual(preview['frames'], [-1, 1, 0])
        self.assertEqual([span['track'] for span in preview['sources']], ['dialogue'])

    def test_sums_before_saturation(self):
        above = self.asset([30000, -30000])
        inverse = self.asset([-30000, 30000])
        revision = self.edit([
            insert('a', above, 0, 2, at=3),
            insert('b', above, 0, 2, at=3),
            insert('c', inverse, 0, 2, at=3),
        ])['revision_id']
        self.assertEqual(self.preview(revision, 0, 5)['frames'], [0, 0, 0, 30000, -30000])
        self.assertEqual(self.preview(revision, 3, 5)['frames'], [30000, -30000])

    def test_half_tracks_are_added_before_rounding(self):
        asset = self.asset([1, -1])
        revision = self.edit([
            insert('a', asset, 0, 2), insert('b', asset, 0, 2),
            {'op': 'level', 'track': 'a', 'percent': 50, 'muted': False},
            {'op': 'level', 'track': 'b', 'percent': 50, 'muted': False},
        ])['revision_id']
        self.assertEqual(self.preview(revision, 0, 2)['frames'], [1, -1])

    def test_empty_scene_has_no_listen_window(self):
        eighth = self.edit([{'op': 'level', 'track': 'bed', 'percent': 100, 'muted': False}])
        self.assertEqual(eighth['length'], 0)
        self.preview(eighth['revision_id'], 0, 1, 400)
        self.issue(eighth['revision_id'], 0, 1, 400)
        self.preview(eighth['revision_id'] + 1, 0, 1, 404)
