import json
from pathlib import Path

from tests.support import StudioCase, insert


class WorkdayTests(StudioCase):
    def test_workday(self):
        sample_path = Path(__file__).resolve().parents[1] / 'examples' / 'bridge.json'
        sample = json.loads(sample_path.read_text(encoding='utf-8'))
        dialogue = self.post('/assets', sample['dialogue'])['asset_id']
        bed = self.post('/assets', sample['bed'])['asset_id']
        scene = sample['scene']
        revision = self.edit([insert('dialogue', dialogue, 0, 4), insert('bed', bed, 0, 4)], scene=scene)
        revision_id = revision['revision_id']
        preview = self.preview(revision_id, 0, 4)
        self.assertEqual(preview['frames'], sample['expected']['preview'])
        self.assertEqual({item['asset_id'] for item in preview['sources']}, {dialogue, bed})

        issued = self.issue(revision_id, *sample['take_window'])
        self.assertEqual(issued['length'], 2)
        self.returned(issued['take_id'], sample['returned'])
        adopted = self.apply(issued['take_id'])
        self.assertEqual(adopted['coverage'], [[1, 3]])
        self.assertEqual(adopted['revision_id'], revision_id)
        occurrence = next(piece['occurrence_id'] for piece in revision['placements'] if piece['track'] == 'dialogue')
        second = self.edit([
            {'op': 'move', 'occurrence_id': occurrence, 'at': sample['move_dialogue_to']},
        ], revision_id, scene=scene)
        self.studio.restart()
        master = self.get(f"/masters/{adopted['master_id']}")
        current_preview = self.preview(second['revision_id'], 0, 6)
        self.assertEqual(master['frames'], sample['expected']['master'])
        self.assertEqual(current_preview['frames'], sample['expected']['next_preview'])
        self.assertEqual({key: value for key, value in master.items() if key != 'frames'}, adopted)

        scenario = {
            'case_id': 'v3',
            'input': {
                'dialogue': sample['dialogue']['frames'], 'bed': sample['bed']['frames'],
                'take_window': sample['take_window'], 'recording': sample['returned'],
                'next_dialogue_start': sample['move_dialogue_to'],
            },
            'expected': sample['expected']['preview'],
            'actual': preview['frames'],
            'downstream_expected': {
                'master': sample['expected']['master'], 'coverage': [[1, 3]],
                'next_preview': sample['expected']['next_preview'],
            },
            'downstream_actual': {
                'master': master['frames'], 'coverage': master['coverage'],
                'next_preview': current_preview['frames'],
            },
            'code_paths': [
                'edit/revisions.py', 'mix/render.py', 'takes/coverage.py', 'takes/apply.py',
                'masters/publish.py', 'masters/playback.py',
            ],
            'oracle': '手算原对白与伴奏逐帧相加。定稿仅把对白的第 1、2 帧换为 70、80。新版对白从第 2 帧起放置。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=True, sort_keys=True))
