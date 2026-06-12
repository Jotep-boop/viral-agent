"""Tests for publish_stats — sync YouTube view/like/comment stats into content registry."""
import json
import tempfile
from pathlib import Path
import unittest

from content_registry import load_registry, append_registry_entry, build_registry_entry

import publish_stats


class StatsFetchTests(unittest.TestCase):
    """Test fetch_stats_for_entry (no real API calls — use mock)."""

    def test_fetch_with_valid_stats_dict(self):
        sample = {
            "viewCount": "12345",
            "likeCount": "456",
            "commentCount": "78",
            "faveCount": "12",
        }
        result = publish_stats.fetch_stats_for_entry(sample)
        self.assertEqual(result["views"], "12345")
        self.assertEqual(result["likes"], "456")
        self.assertEqual(result["comments"], "78")
        self.assertEqual(result["favorites"], "12")
        self.assertTrue(result["fetched_at"])

    def test_fetch_handles_unknown_fields_ignored(self):
        sample = {"viewCount": "0", "likeCount": "0", "commentCount": "0", "extra": "xyz"}
        result = publish_stats.fetch_stats_for_entry(sample)
        self.assertNotIn("extra", result)  # extra keys stripped

    def test_fetch_handles_missing_count_fields(self):
        sample = {"viewCount": "99"}
        result = publish_stats.fetch_stats_for_entry(sample)
        self.assertEqual(result["views"], "99")
        self.assertEqual(result["likes"], "0")
        self.assertEqual(result["comments"], "0")

    def test_fetch_handles_empty_dict(self):
        result = publish_stats.fetch_stats_for_entry({})
        self.assertEqual(result["views"], "0")
        self.assertEqual(result["likes"], "0")
        self.assertEqual(result["comments"], "0")

    def test_fetch_null_counts_treated_as_zero(self):
        result = publish_stats.fetch_stats_for_entry({"viewCount": None, "likeCount": None, "commentCount": None})
        self.assertEqual(result["views"], "0")
        self.assertEqual(result["likes"], "0")


class RegistrySyncTests(unittest.TestCase):
    """Test update_with_stats writing stats back to registry."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "registry.json"
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text('{"entries": []}', encoding="utf-8")

    def _make_entry(self):
        return build_registry_entry(
            topic="Test Topic", theme="Science", fact_summary="Iron expands when hot",
            hook_angle="Did you know?", keywords=["iron", "science"],
            registry_path=self.tmp, status="uploaded",
        )

    def test_update_with_stats_updates_entry(self):
        entry = self._make_entry()
        append_registry_entry(entry, self.tmp)
        stats = {"views": "500", "likes": "25", "comments": "3", "favorites": "1", "fetched_at": "2026-06-07T10:00:00Z"}
        path = publish_stats.update_with_stats(entry["id"], stats, registry_path=self.tmp)
        self.assertTrue((self.tmp).exists())
        data = json.loads(self.tmp.read_text(encoding="utf-8"))
        updated = data["entries"][0]
        self.assertEqual(updated["youtube_stats"]["views"], "500")
        self.assertEqual(updated["youtube_stats"]["fetched_at"], "2026-06-07T10:00:00Z")

    def test_update_with_stats_ignores_missing_entry_id(self):
        # Should not raise — just return None/silent
        result = publish_stats.update_with_stats("clipforge-999999", {"views": "0"}, registry_path=self.tmp)
        self.assertIsNone(result)  # No matching entry


class SyncForRunTests(unittest.TestCase):
    """Test sync_for_run — finds the video's registry entry and updates it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "registry.json"
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text('{"entries": []}', encoding="utf-8")
        self.run_dir = Path(tempfile.mkdtemp()) / "output" / "runs" / "clipforge-2026-06-07-001" / "videos"
        self.run_dir.mkdir(parents=True)
        self.final_video = self.run_dir / "final.mp4"
        self.final_video.write_bytes(b"fake")
        # Create manifest too
        manifest_dir = self.final_video.parent.parent.parent.parent  # /output/runs/clipforge-2026-06-07-001

    def test_sync_for_run_updates_matching_entry(self):
        entry = build_registry_entry(
            topic="Test", theme="Test", fact_summary="Test",
            hook_angle="Test", keywords=["t"],
            registry_path=self.tmp, status="uploaded",
            entry_id="clipforge-2026-06-07-001",
        )
        append_registry_entry(entry, self.tmp)

        stats = {"views": "42", "likes": "5", "comments": "1", "fetched_at": "now"}
        result = publish_stats.sync_for_run(
            video_path=str(self.final_video),
            stats=stats,
            registry_path=self.tmp,
        )
        self.assertEqual(result["success"], True)
        data = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertEqual(data["entries"][-1]["youtube_stats"]["views"], "42")

    def test_sync_for_run_fails_with_mismatched_registry_id(self):
        # registry_id in path = "clipforge-2026-06-07-001"
        # but we add an entry with a different id
        entry = build_registry_entry(
            topic="Test", theme="Test", fact_summary="Test",
            hook_angle="Test", keywords=["t"],
            registry_path=self.tmp, status="uploaded",
            entry_id="different-id",
        )
        append_registry_entry(entry, self.tmp)

        stats = {"views": "42", "likes": "0", "comments": "0", "fetched_at": "now"}
        result = publish_stats.sync_for_run(
            video_path=str(self.final_video),
            stats=stats,
            registry_path=self.tmp,
        )
        self.assertEqual(result["success"], False)


class StatsFetchIntegrationTests(unittest.TestCase):
    """Test that fetch_all_and_update writes to all uploaded entries."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "registry.json"
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.tmp.write_text('{"entries": []}', encoding="utf-8")

    def _add_entries(self, count):
        for i in range(count):
            entry = build_registry_entry(
                topic=f"Topic {i}", theme="Science", fact_summary=f"Fact {i}",
                hook_angle="Hook", keywords=["t"],
                registry_path=self.tmp, status="uploaded",
                entry_id=f"clipforge-2026-06-07-{i+1:03d}",
            )
            append_registry_entry(entry, self.tmp)

    def test_fetch_all_and_update_skips_non_uploaded(self):
        self._add_entries(3)
        # fetch_stats_for_entry receives the full entry dict; simulate stats available
        # for the first two entries only (third has no youtube_video_id → returns None)
        uploaded_ids = {"clipforge-2026-06-07-001", "clipforge-2026-06-07-002"}
        original = publish_stats.fetch_stats_for_entry
        publish_stats.fetch_stats_for_entry = (
            lambda entry: (
                {"viewCount": "100", "likeCount": "10", "commentCount": "2",
                 "favoriteCount": "0", "fetched_at": "now"}
                if isinstance(entry, dict) and entry.get("id") in uploaded_ids
                else None
            )
        )
        try:
            results = publish_stats.fetch_all_and_update(registry_path=self.tmp)
            self.assertEqual(len(results), 3)
            self.assertTrue(results[0]["success"], "first entry should succeed")
            self.assertTrue(results[1]["success"], "second entry should succeed")
            self.assertFalse(results[2]["success"], "third entry should be skipped")
        finally:
            publish_stats.fetch_stats_for_entry = original


if __name__ == "__main__":
    unittest.main()
