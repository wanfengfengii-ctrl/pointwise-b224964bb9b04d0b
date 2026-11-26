from tests.support import StudioCase, insert


class RecutContractTests(StudioCase):
    def _seed_master(self):
        dialogue = self.asset([10, 20, 30, 40], "original dialogue")
        bed = self.asset(list(range(1, 13)), "room tone")
        revision = self.edit([insert("dialogue", dialogue, 0, 4), insert("bed", bed, 0, 12)])
        take = self.issue(revision["revision_id"], 1, 3)["take_id"]
        self.returned(take, [70, 80])
        master_id = self.apply(take)["master_id"]
        return dialogue, revision, take, master_id

    def _open(self, master_id):
        draft = self.post("/recuts", {"master_id": master_id})
        return draft["recut_id"], draft["version_id"]

    def test_recut_open_contract_and_errors(self):
        _, _, _, master_id = self._seed_master()
        recut_id, version_id = self._open(master_id)
        detail = self.get(f"/recuts/{recut_id}")
        self.assertEqual(detail, {
            "recut_id": recut_id, "original_master_id": master_id, "version_id": version_id,
        })
        for body in ({}, {"master_id": master_id, "extra": 1}, {"master_id": "1"}, {"master_id": -1}):
            self.post("/recuts", body, 400)
        self.post("/recuts", {"master_id": 999}, 404)
        self.get("/recuts/999", 404)
        self.get("/recuts/0", 400)

    def test_stale_parent_and_failed_batch_leave_head_untouched(self):
        _, revision, _, master_id = self._seed_master()
        recut_id, base = self._open(master_id)
        original = next(item["occurrence_id"] for item in revision["placements"]
                        if item["track"] == "dialogue")
        path = f"/recuts/{recut_id}"
        moved = self.post(path + "/edits", {
            "parent_version_id": base,
            "instructions": [{"op": "move", "occurrence_id": original, "at": 4}],
        })["version_id"]
        self.post(path + "/edits", {
            "parent_version_id": base,
            "instructions": [{"op": "remove", "track": "dialogue", "start": 0, "end": 1}],
        }, 409)
        # A failed batch (bad removal after restore) creates no version and does
        # not consume the one allowed restore.
        self.post(path + "/edits", {
            "parent_version_id": moved,
            "instructions": [
                {"op": "restore_dialogue"},
                {"op": "remove", "track": "dialogue", "start": 40, "end": 41},
            ],
        }, 400)
        self.assertEqual(self.get(path)["version_id"], moved)
        restored = self.post(path + "/edits", {
            "parent_version_id": moved, "instructions": [{"op": "restore_dialogue"}],
        })["version_id"]
        self.post(path + "/edits", {
            "parent_version_id": restored, "instructions": [{"op": "restore_dialogue"}],
        }, 409)

    def test_recut_master_cannot_open_another_recut(self):
        _, _, _, master_id = self._seed_master()
        recut_id, base = self._open(master_id)
        new_master = self.post(f"/recuts/{recut_id}/publish", {"version_id": base})["master_id"]
        self.post("/recuts", {"master_id": new_master}, 409)
        self.assertEqual(self.get("/masters")["master_ids"], [master_id, new_master])

    def test_unknown_version_belonging_to_other_draft_is_404(self):
        _, _, _, master_id = self._seed_master()
        first, first_version = self._open(master_id)
        second, _ = self._open(master_id)
        self.post(f"/recuts/{second}/preview", {"version_id": first_version}, 404)
        self.post(f"/recuts/{second}/publish", {"version_id": first_version}, 404)

    def test_levels_muted_and_zero_percent_have_no_sources(self):
        _, revision, _, master_id = self._seed_master()
        recut_id, base = self._open(master_id)
        path = f"/recuts/{recut_id}"
        muted = self.post(path + "/edits", {
            "parent_version_id": base,
            "instructions": [{"op": "level", "track": "dialogue", "percent": 0, "muted": True}],
        })["version_id"]
        preview = self.post(path + "/preview", {"version_id": muted}, 200)
        self.assertEqual(preview["frames"], list(range(1, 13)))
        self.assertTrue(all(span["track"] == "bed" for span in preview["sources"]))
        # Historical version still previews the inherited replacement mix.
        base_preview = self.post(path + "/preview", {"version_id": base}, 200)
        self.assertEqual(base_preview["frames"], [11, 72, 83, 44, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_asset_zero_samples_keep_provenance_in_recut(self):
        zero_dialogue = self.asset([0, 0, 0, 0], "zero dialogue")
        bed = self.asset([1, 1, 1, 1], "bed")
        revision = self.edit([
            insert("dialogue", zero_dialogue, 0, 4), insert("bed", bed, 0, 4),
        ], scene="quiet")
        take = self.issue(revision["revision_id"], 0, 2)["take_id"]
        self.returned(take, [5, 6])
        master_id = self.apply(take)["master_id"]
        recut_id, base = self._open(master_id)
        preview = self.post(f"/recuts/{recut_id}/preview", {"version_id": base}, 200)
        dialogue_spans = [span for span in preview["sources"] if span["track"] == "dialogue"]
        self.assertEqual(
            [(span["kind"], span["start"], span["end"]) for span in dialogue_spans],
            [("take", 0, 2), ("asset", 2, 4)],
        )
        self.assertEqual(preview["frames"], [6, 7, 1, 1])
