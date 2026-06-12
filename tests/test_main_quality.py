import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main


class MainQualityTests(unittest.TestCase):
    def test_check_quality_rejects_overlong_script_and_duration(self):
        script = SimpleNamespace(
            full_script="word " * 95,
            hook="You won't believe this",
        )

        ok, issues = main._check_quality(script, 46.0)

        self.assertFalse(ok)
        self.assertTrue(any("word_count 95" in issue for issue in issues))
        self.assertTrue(any("duration 46.0s" in issue for issue in issues))

    def test_check_quality_accepts_tighter_target_window(self):
        script = SimpleNamespace(
            full_script="word " * 72,
            hook="A black hole can sing",
        )

        ok, issues = main._check_quality(script, 29.0)

        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_screen_prompt_requires_orientation_guardrails(self):
        self.assertTrue(main._is_screen_prompt_risky("close-up of a glowing laptop screen with code"))
        self.assertFalse(
            main._is_screen_prompt_risky(
                "close-up of an upright laptop screen with legible code, straight-on, not mirrored"
            )
        )

    def test_frame_review_hard_fail_blocks_upload(self):
        issues = ["The phone UI is mirrored and the keyboard looks physically wrong."]
        self.assertTrue(main._frame_review_is_hard_fail(issues))

    def test_frame_review_soft_fail_allows_metaphorical_visuals(self):
        issues = [
            "The visuals are loosely related and show a desert tower rather than the jacket itself."
        ]
        self.assertFalse(main._frame_review_is_hard_fail(issues))

    def test_clip_retry_regenerates_audio_and_uses_new_script_for_captions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            audio_path = tmp / "voiceover.mp3"
            raw_video = tmp / "raw.mp4"
            final_video = tmp / "final.mp4"
            manifest_path = tmp / "manifest.json"
            clip_path = tmp / "clip_00.mp4"
            for path in [audio_path, raw_video, final_video, clip_path]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x")

            artifact_paths = SimpleNamespace(
                registry_id="clipforge-test-001",
                audio=audio_path,
                clips_dir=tmp / "clips",
                videos_dir=tmp / "videos",
                raw_video=raw_video,
                final_video=final_video,
            )

            idea = SimpleNamespace(angle="angle")
            script_a = SimpleNamespace(
                full_script="old script words",
                hook="hook",
                topic="topic",
                theme="theme",
                fact_summary="fact",
                hook_angle="angle",
                keywords=["kw"],
                format="scary",
                clips=[{"prompt": "bad laptop screen"}],
                beats=[{"text": "beat one"}],
                emphasis_words=["old"],
            )
            script_b = SimpleNamespace(
                full_script="new script words",
                hook="hook",
                topic="topic",
                theme="theme",
                fact_summary="fact",
                hook_angle="angle",
                keywords=["kw"],
                format="scary",
                clips=[{"prompt": "good concrete macro"}],
                beats=[{"text": "beat one"}],
                emphasis_words=["new"],
            )

            tts_calls = []
            captions_calls = []

            def fake_tts(text, output_path=None):
                tts_calls.append(text)
                assert output_path is not None
                output_path.write_text(text)
                return output_path

            def fake_add_captions(video, audio, script_text="", emphasis_words=None, output_path=None):
                captions_calls.append({
                    "video": video,
                    "audio": audio,
                    "script_text": script_text,
                    "emphasis_words": emphasis_words,
                    "output_path": output_path,
                })
                assert output_path is not None
                output_path.write_text("video")
                return output_path

            with ExitStack() as stack:
                stack.enter_context(patch("config.validate_config", return_value=None))
                stack.enter_context(patch("config.DEFAULT_FORMAT", "informative"))
                stack.enter_context(patch("config.OUTPUT_DIR", tmp))
                stack.enter_context(patch("config.CONTENT_REGISTRY_PATH", tmp / "registry.json"))
                stack.enter_context(patch("config.FAL_KEY", "test-key"))
                stack.enter_context(patch("artifact_paths.reserve_artifact_paths", return_value=artifact_paths))
                stack.enter_context(patch("tracker.get_top_performers", return_value=[]))
                stack.enter_context(patch("tracker.get_performance_insights", return_value={}))
                stack.enter_context(patch("main._pick_best_script", return_value=(idea, script_a)))
                stack.enter_context(patch("idea.run_idea_tournament", return_value=(None, [{"score": 1}])))
                stack.enter_context(patch("idea.generate_script", return_value=script_b))
                stack.enter_context(patch("voice.text_to_speech", side_effect=fake_tts))
                stack.enter_context(patch("main._get_audio_duration", return_value=28.0))
                stack.enter_context(patch("main._check_quality", return_value=(True, [])))
                stack.enter_context(patch("main._check_clip_prompts", side_effect=[(False, ["bad prompt"]), (True, [])]))
                stack.enter_context(patch("video.generate_footage_ai", return_value=[clip_path]))
                stack.enter_context(patch("video.assemble_video", return_value=raw_video))
                stack.enter_context(patch("captions.add_captions", side_effect=fake_add_captions))
                stack.enter_context(patch("content_registry.build_registry_entry", return_value={"id": "clipforge-test-001"}))
                stack.enter_context(patch("content_registry.append_registry_entry", return_value=None))
                stack.enter_context(patch("manifest.probe_duration_seconds", return_value=28.0))
                stack.enter_context(patch("main._extract_frames", return_value=[]))
                stack.enter_context(patch("manifest.write_run_manifest", return_value=manifest_path))
                main.run_pipeline(topic="topic", dry_run=True)

            self.assertEqual(tts_calls, ["old script words", "new script words"])
            self.assertEqual(len(captions_calls), 1)
            self.assertEqual(captions_calls[0]["script_text"], "new script words")
            self.assertEqual(captions_calls[0]["emphasis_words"], ["new"])


if __name__ == "__main__":
    unittest.main()
