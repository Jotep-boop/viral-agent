import json
import tempfile
import unittest
from pathlib import Path


class RunManifestTests(unittest.TestCase):
    def test_build_artifact_paths_exposes_manifest_path_in_run_dir(self):
        from artifact_paths import build_artifact_paths

        paths = build_artifact_paths(Path("output"), registry_id="clipforge-2026-06-07-010")

        self.assertEqual(paths.manifest.name, "manifest.json")
        self.assertEqual(paths.manifest.parent, paths.run_dir)

    def test_write_run_manifest_records_metadata_and_relative_artifact_paths(self):
        from artifact_paths import build_artifact_paths
        from manifest import write_run_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            paths = build_artifact_paths(output_dir, registry_id="clipforge-2026-06-07-010")

            paths.audio.write_text("fake mp3", encoding="utf-8")
            paths.srt.write_text("fake srt", encoding="utf-8")
            paths.raw_video.write_text("fake raw", encoding="utf-8")
            paths.final_video.write_text("fake final", encoding="utf-8")
            paths.clip(0).write_text("fake clip", encoding="utf-8")
            paths.normalized_clip(0).write_text("fake norm", encoding="utf-8")

            manifest_path = write_run_manifest(
                paths=paths,
                topic="Sea otters hold hands while sleeping",
                theme="animal behavior",
                pillar="animal weirdness",
                hook_type="this-sounds-fake",
                fact_summary="Sea otters sometimes hold hands while sleeping so they do not drift apart.",
                hook_angle="It sounds like a human relationship habit in the wild.",
                keywords=["sea otter", "ocean", "kelp forest"],
                status="produced-dry-run",
                script_text="Sea otters hold hands while sleeping.",
                duration_seconds=21.3,
            )

            data = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest_path, paths.manifest)
            self.assertEqual(data["registry_id"], "clipforge-2026-06-07-010")
            self.assertEqual(data["status"], "produced-dry-run")
            self.assertEqual(data["topic"], "Sea otters hold hands while sleeping")
            self.assertEqual(data["pillar"], "animal weirdness")
            self.assertEqual(data["hook_type"], "this-sounds-fake")
            self.assertEqual(data["duration_seconds"], 21.3)
            self.assertEqual(data["paths"]["voiceover"], "audio/voiceover.mp3")
            self.assertEqual(data["paths"]["subtitles"], "audio/voiceover.srt")
            self.assertEqual(data["paths"]["raw_video"], "videos/raw.mp4")
            self.assertEqual(data["paths"]["final_video"], "videos/final.mp4")
            self.assertEqual(data["paths"]["clips"], ["clips/clip_00.mp4"])
            self.assertEqual(data["paths"]["normalized_clips"], ["clips/norm_00.mp4"])
            self.assertEqual(data["files_exist"]["final_video"], True)
            self.assertEqual(data["files_exist"]["manifest"], True)
            self.assertEqual(data["script_text"], "Sea otters hold hands while sleeping.")


if __name__ == "__main__":
    unittest.main()
