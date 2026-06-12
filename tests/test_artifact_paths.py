import json
import tempfile
import unittest
from pathlib import Path


class ArtifactPathTests(unittest.TestCase):
    def test_build_artifact_paths_uses_stable_names_inside_run_directory(self):
        from artifact_paths import build_artifact_paths

        paths = build_artifact_paths(Path("output"), registry_id="clipforge-2026-06-07-006")

        self.assertEqual(paths.audio.name, "voiceover.mp3")
        self.assertEqual(paths.srt.name, "voiceover.srt")
        self.assertEqual(paths.raw_video.name, "raw.mp4")
        self.assertEqual(paths.final_video.name, "final.mp4")
        self.assertEqual(paths.clip(2).name, "clip_02.mp4")
        self.assertEqual(paths.normalized_clip(2).name, "norm_02.mp4")

    def test_build_artifact_paths_places_everything_under_output_runs_registry_id(self):
        from artifact_paths import build_artifact_paths

        output_dir = Path("output")
        paths = build_artifact_paths(output_dir, registry_id="clipforge-2026-06-07-006")
        run_dir = output_dir / "runs" / "clipforge-2026-06-07-006"

        self.assertEqual(paths.run_dir, run_dir)
        self.assertEqual(paths.audio.parent, run_dir / "audio")
        self.assertEqual(paths.srt.parent, run_dir / "audio")
        self.assertEqual(paths.raw_video.parent, run_dir / "videos")
        self.assertEqual(paths.final_video.parent, run_dir / "videos")
        self.assertEqual(paths.clip(0).parent, run_dir / "clips")
        self.assertEqual(paths.normalized_clip(0).parent, run_dir / "clips")

    def test_reserve_artifact_paths_skips_existing_registry_and_run_dirs(self):
        import artifact_paths as ap

        real_datetime = ap.datetime

        class FakeDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2099, 1, 1, tzinfo=tz)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            output_dir = tmp / "output"
            runs_dir = output_dir / "runs"
            runs_dir.mkdir(parents=True)
            registry_path = tmp / "content_registry.json"
            registry_path.write_text(
                json.dumps({
                    "entries": [
                        {"id": "clipforge-2099-01-01-001"},
                        {"id": "clipforge-2099-01-01-002"}
                    ]
                }),
                encoding="utf-8",
            )
            (runs_dir / "clipforge-2099-01-01-003").mkdir()

            ap.datetime = FakeDateTime
            try:
                paths = ap.reserve_artifact_paths(output_dir, registry_path=registry_path)
            finally:
                ap.datetime = real_datetime

            self.assertEqual(paths.registry_id, "clipforge-2099-01-01-004")
            self.assertTrue(paths.run_dir.exists())


if __name__ == "__main__":
    unittest.main()
