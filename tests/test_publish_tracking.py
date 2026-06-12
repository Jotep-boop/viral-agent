import json
import tempfile
import unittest
from pathlib import Path


class PublishTrackingTests(unittest.TestCase):
    def test_update_registry_entry_marks_uploaded_video_metadata(self):
        from content_registry import update_registry_entry

        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "content_registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "id": "clipforge-2026-06-07-011",
                                "status": "produced",
                                "topic": "Venus topic",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            update_registry_entry(
                entry_id="clipforge-2026-06-07-011",
                updates={
                    "status": "uploaded",
                    "youtube_url": "https://www.youtube.com/watch?v=abc123",
                    "youtube_video_id": "abc123",
                    "published_at": "2026-06-07T09:00:00+00:00",
                },
                registry_path=registry_path,
            )

            data = json.loads(registry_path.read_text(encoding="utf-8"))
            entry = data["entries"][0]
            self.assertEqual(entry["status"], "uploaded")
            self.assertEqual(entry["youtube_url"], "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(entry["youtube_video_id"], "abc123")
            self.assertEqual(entry["published_at"], "2026-06-07T09:00:00+00:00")

    def test_update_run_manifest_marks_uploaded_video_metadata(self):
        from artifact_paths import build_artifact_paths
        from manifest import update_run_manifest, write_run_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            paths = build_artifact_paths(output_dir, registry_id="clipforge-2026-06-07-011")
            paths.audio.write_text("fake mp3", encoding="utf-8")
            paths.srt.write_text("fake srt", encoding="utf-8")
            paths.raw_video.write_text("fake raw", encoding="utf-8")
            paths.final_video.write_text("fake final", encoding="utf-8")

            write_run_manifest(
                paths=paths,
                topic="Venus topic",
                theme="space physics",
                fact_summary="Venus has a longer day than year.",
                hook_angle="Planetary time feels backwards.",
                keywords=["venus planet"],
                status="produced",
                script_text="Venus script",
                duration_seconds=22.1,
            )

            manifest_path = update_run_manifest(
                paths.manifest,
                status="uploaded",
                youtube_url="https://www.youtube.com/watch?v=abc123",
                video_id="abc123",
                published_at="2026-06-07T09:00:00+00:00",
            )

            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "uploaded")
            self.assertEqual(data["youtube"]["url"], "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(data["youtube"]["video_id"], "abc123")
            self.assertEqual(data["youtube"]["published_at"], "2026-06-07T09:00:00+00:00")

    def test_track_successful_upload_updates_manifest_and_registry_for_run_video(self):
        from artifact_paths import build_artifact_paths
        from manifest import write_run_manifest
        from publish_tracking import track_successful_upload

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "output"
            registry_path = root / "content_registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "id": "clipforge-2026-06-07-011",
                                "status": "produced",
                                "topic": "Venus topic",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            paths = build_artifact_paths(output_dir, registry_id="clipforge-2026-06-07-011")
            paths.audio.write_text("fake mp3", encoding="utf-8")
            paths.srt.write_text("fake srt", encoding="utf-8")
            paths.raw_video.write_text("fake raw", encoding="utf-8")
            paths.final_video.write_text("fake final", encoding="utf-8")
            write_run_manifest(
                paths=paths,
                topic="Venus topic",
                theme="space physics",
                fact_summary="Venus has a longer day than year.",
                hook_angle="Planetary time feels backwards.",
                keywords=["venus planet"],
                status="produced",
                script_text="Venus script",
                duration_seconds=22.1,
            )

            result = track_successful_upload(
                video_path=paths.final_video,
                youtube_url="https://www.youtube.com/watch?v=abc123",
                registry_path=registry_path,
                published_at="2026-06-07T09:00:00+00:00",
            )

            manifest_data = json.loads(paths.manifest.read_text(encoding="utf-8"))
            registry_data = json.loads(registry_path.read_text(encoding="utf-8"))
            registry_entry = registry_data["entries"][0]

            self.assertEqual(result["registry_id"], "clipforge-2026-06-07-011")
            self.assertEqual(manifest_data["status"], "uploaded")
            self.assertEqual(manifest_data["youtube"]["video_id"], "abc123")
            self.assertEqual(registry_entry["status"], "uploaded")
            self.assertEqual(registry_entry["youtube_video_id"], "abc123")
            self.assertEqual(registry_entry["published_at"], "2026-06-07T09:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
