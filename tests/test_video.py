import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class VideoTests(unittest.TestCase):
    def test_generate_footage_ai_prefers_image_first_pipeline(self):
        import video

        calls: list[tuple[str, dict]] = []

        def fake_subscribe(model, arguments, **kwargs):
            calls.append((model, arguments))
            if model == video.config.FALAI_IMAGE_MODEL:
                return {"images": [{"url": f"https://example.com/still-{len(calls)}.png"}]}
            return {"video": {"url": f"https://example.com/{arguments['duration']}.mp4"}}

        fake_fal_client = types.SimpleNamespace(subscribe=fake_subscribe)

        def fake_download(url: str, dest: Path) -> None:
            dest.write_bytes(b"fake mp4")

        with tempfile.TemporaryDirectory() as tmpdir:
            clips_dir = Path(tmpdir) / "clips"
            with patch.dict(sys.modules, {"fal_client": fake_fal_client}):
                with patch.object(video.config, "FAL_KEY", "test-key"):
                    with patch.object(video, "_download_file", side_effect=fake_download):
                        with patch.object(video, "_review_still", return_value=True):
                            paths = video.generate_footage_ai(
                                [{"prompt": "clip one", "duration": 4}],
                                clips_dir=clips_dir,
                            )

        self.assertEqual(len(paths), 1)
        self.assertEqual(calls[0][0], video.config.FALAI_IMAGE_MODEL)
        self.assertEqual(calls[1][0], video.config.FALAI_I2V_MODEL)
        self.assertEqual(calls[1][1]["duration"], "5")

    def test_generate_footage_ai_falls_back_to_text_to_video(self):
        import video

        calls: list[tuple[str, dict]] = []

        def fake_subscribe(model, arguments, **kwargs):
            calls.append((model, arguments))
            if model == video.config.FALAI_IMAGE_MODEL:
                raise RuntimeError("image model unavailable")
            return {"video": {"url": f"https://example.com/{arguments['duration']}.mp4"}}

        fake_fal_client = types.SimpleNamespace(subscribe=fake_subscribe)

        def fake_download(url: str, dest: Path) -> None:
            dest.write_bytes(b"fake mp4")

        with tempfile.TemporaryDirectory() as tmpdir:
            clips_dir = Path(tmpdir) / "clips"
            with patch.dict(sys.modules, {"fal_client": fake_fal_client}):
                with patch.object(video.config, "FAL_KEY", "test-key"):
                    with patch.object(video, "_download_file", side_effect=fake_download):
                        paths = video.generate_footage_ai(
                            [{"prompt": "clip one", "duration": 9}],
                            clips_dir=clips_dir,
                        )

        self.assertEqual(len(paths), 1)
        self.assertEqual(calls[0][0], video.config.FALAI_IMAGE_MODEL)
        self.assertEqual(calls[1][0], video.config.FALAI_MODEL)
        self.assertEqual(calls[1][1]["duration"], "10")

    def test_generate_footage_ai_normalizes_unsupported_kling_durations(self):
        import video

        calls: list[tuple[str, dict]] = []

        fake_fal_client = types.SimpleNamespace()

        def fake_subscribe(model, arguments, **kwargs):
            calls.append((model, arguments))
            if model == video.config.FALAI_IMAGE_MODEL:
                raise RuntimeError("image model unavailable")
            return {"video": {"url": f"https://example.com/{arguments['duration']}.mp4"}}

        fake_fal_client.subscribe = fake_subscribe

        def fake_download(url: str, dest: Path) -> None:
            dest.write_bytes(b"fake mp4")

        with tempfile.TemporaryDirectory() as tmpdir:
            clips_dir = Path(tmpdir) / "clips"
            with patch.dict(sys.modules, {"fal_client": fake_fal_client}):
                with patch.object(video.config, "FAL_KEY", "test-key"):
                    with patch.object(video, "_download_file", side_effect=fake_download):
                        paths = video.generate_footage_ai(
                            [
                                {"prompt": "clip one", "duration": 4},
                                {"prompt": "clip two", "duration": 6},
                                {"prompt": "clip three", "duration": 9},
                            ],
                            clips_dir=clips_dir,
                        )

            t2v_calls = [arguments for model, arguments in calls if model == video.config.FALAI_MODEL]
            self.assertEqual([call["duration"] for call in t2v_calls], ["5", "5", "10"])
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
