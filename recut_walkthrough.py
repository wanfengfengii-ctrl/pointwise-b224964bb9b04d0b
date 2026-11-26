import json
import sqlite3
from unittest.mock import patch

from takes import workbench
from tests.support import StudioCase, insert


class RecutWalkthrough(StudioCase):
    def _seed(self):
        dialogue = self.asset([10, 20, 30, 40], "original dialogue")
        bed = self.asset(list(range(1, 13)), "room tone")
        revision = self.edit([insert("dialogue", dialogue, 0, 4), insert("bed", bed, 0, 12)])
        take = self.issue(revision["revision_id"], 1, 3)["take_id"]
        self.returned(take, [70, 80])
        master_id = self.apply(take)["master_id"]
        master = self.get(f"/masters/{master_id}")
        return dialogue, revision, take, master

    def _open(self, master):
        draft = self.post("/recuts", {"master_id": master["master_id"]})
        self.assertEqual(draft["original_master_id"], master["master_id"])
        draft_id = draft["recut_id"]
        return f"/recuts/{draft_id}", draft["version_id"]

    def _edit(self, path, parent, instructions, status=201):
        return self.post(path + "/edits", {
            "parent_version_id": parent, "instructions": instructions,
        }, status)

    def _preview(self, path, version):
        return self.post(path + "/preview", {"version_id": version}, 200)

    def _dialogue_sources(self, preview):
        by_frame = {}
        for span in preview["sources"]:
            if span["track"] != "dialogue":
                continue
            if span["kind"] == "asset":
                source_id, offset, end = span["asset_id"], span["source_start"], span["source_end"]
            else:
                self.assertEqual(span["kind"], "take")
                source_id, offset, end = span["take_id"], span["take_start"], span["take_end"]
            self.assertEqual(span["end"] - span["start"], end - offset)
            for delta, frame in enumerate(range(span["start"], span["end"])):
                self.assertNotIn(frame, by_frame)
                by_frame[frame] = (span["occurrence_id"], span["kind"], source_id, offset + delta)
        return by_frame

    def test_v1_seed(self):
        _, revision, take, master = self._seed()
        self.assertEqual(master["frames"], [11, 72, 83, 44, 5, 6, 7, 8, 9, 10, 11, 12])
        self.assertEqual(master["revision_id"], revision["revision_id"])
        self.assertEqual(master["take"]["take_id"], take)
        span, = master["take"]["spans"]
        self.assertEqual((span["start"], span["end"], span["take_start"], span["take_end"]), (1, 3, 0, 2))

    def test_recut_release(self):
        dialogue, revision, take, master = self._seed()
        original = next(piece["occurrence_id"] for piece in revision["placements"] if piece["track"] == "dialogue")
        normal_head = self.edit([
            {"op": "level", "track": "dialogue", "percent": 0, "muted": True},
        ], revision["revision_id"])["revision_id"]
        path, base = self._open(master)
        self.assertEqual(self._preview(path, base)["frames"], master["frames"])
        edited = self._edit(path, base, [
            {"op": "move", "occurrence_id": original, "at": 4},
            {"op": "copy", "occurrence_id": original, "at": 8},
            {"op": "remove", "track": "dialogue", "start": 5, "end": 6},
        ])
        before = edited["version_id"]
        copy = next(piece["occurrence_id"] for piece in edited["placements"]
                    if piece["track"] == "dialogue" and piece["start"] == 8)
        self.assertNotEqual(copy, original)
        heard_before = self._preview(path, before)
        self.assertEqual(heard_before["frames"], [1, 2, 3, 4, 15, 6, 87, 48, 19, 80, 91, 52])
        self.assertEqual(self._dialogue_sources(heard_before)[6], (original, "take", take, 1))
        restore = {"op": "restore_dialogue"}
        self._edit(path, base, [restore], 409)
        self._edit(path, before, [restore, {"op": "remove", "track": "dialogue", "start": 20, "end": 21}], 400)
        self.assertEqual(self.get(path)["version_id"], before)
        after = self._edit(path, before, [
            restore, {"op": "level", "track": "dialogue", "percent": 50, "muted": False},
        ])["version_id"]
        heard_after = self._preview(path, after)
        self.assertEqual(heard_after["frames"], [1, 2, 3, 4, 10, 6, 22, 28, 14, 45, 51, 32])
        voice = self._dialogue_sources(heard_after)
        self.assertNotIn(5, voice)
        self.assertEqual(voice[6], (original, "asset", dialogue, 2))
        self.assertEqual(voice[9], (copy, "take", take, 0))
        self.assertEqual(voice[10], (copy, "take", take, 1))
        self._edit(path, after, [restore], 409)
        self.assertEqual(self.get(path)["version_id"], after)
        self.assertEqual(self._preview(path, before), heard_before)

        self._check_failed_publish(path, after, master["master_id"])
        published = self.post(path + "/publish", {"version_id": after})
        self.assertNotEqual(published["master_id"], master["master_id"])
        final_path = "/masters/{}".format(published["master_id"])
        signed = self.get(final_path)
        self.assertEqual(signed["original_master_id"], master["master_id"])
        for key in ("recut_id", "version_id", "sample_rate", "frames", "sources"):
            self.assertEqual(signed[key], heard_after[key])
        self.assertIn(published["master_id"], self.get("/masters")["master_ids"])

        moved = self._edit(path, after, [
            {"op": "move", "occurrence_id": copy, "at": 0},
        ])["version_id"]
        moved_audio = self._preview(path, moved)
        self.assertEqual(moved_audio["frames"], [6, 37, 43, 24, 10, 6, 22, 28, 9, 10, 11, 12])
        self.assertEqual(self._dialogue_sources(moved_audio)[2], (copy, "take", take, 1))
        self.studio.restart()
        self.assertEqual(self.get("/scenes/bridge")["revision_id"], normal_head)
        self.assertEqual(self.get(path)["version_id"], moved)
        self.assertEqual(self.get(final_path), signed)
        old_path = "/masters/{}".format(master["master_id"])
        self.assertEqual(self.get(old_path), master)
        print(json.dumps({"before_restore": heard_before, "recut_master": signed, "original_master": master},
                         ensure_ascii=False))

    def _check_failed_publish(self, path, version, original_master_id):
        connect = workbench._connect

        def reject_commit(action, subject, _arg2, _database, _trigger):
            if action == sqlite3.SQLITE_TRANSACTION and subject == "COMMIT":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def connect_without_commit(database):
            db = connect(database)
            db.set_authorizer(reject_commit)
            return db

        with patch.object(workbench, "_connect", side_effect=connect_without_commit):
            self.post(path + "/publish", {"version_id": version}, 500)
        self.assertEqual(self.get("/masters")["master_ids"], [original_master_id])
        self.assertEqual(self.get(path)["version_id"], version)

    def test_restore_then_copy_in_one_batch(self):
        dialogue, revision, _, master = self._seed()
        original = next(piece["occurrence_id"] for piece in revision["placements"] if piece["track"] == "dialogue")
        path, base = self._open(master)
        edited = self._edit(path, base, [
            {"op": "restore_dialogue"},
            {"op": "copy", "occurrence_id": original, "at": 8},
        ])
        copied = next(piece["occurrence_id"] for piece in edited["placements"]
                      if piece["track"] == "dialogue" and piece["start"] == 8)
        self.assertNotEqual(copied, original)
        result = self._preview(path, edited["version_id"])
        self.assertEqual(result["frames"], [11, 22, 33, 44, 5, 6, 7, 8, 19, 30, 41, 52])
        self.assertEqual(self._dialogue_sources(result)[9], (copied, "asset", dialogue, 1))
