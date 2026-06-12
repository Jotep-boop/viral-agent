import unittest
from pathlib import Path
from unittest.mock import patch


class Top5SyncTests(unittest.TestCase):
    def test_parse_top5_builds_ordered_beats(self):
        import formats

        parsed = formats._parse_top5(
            {
                "hook": "These places look impossible.",
                "items": [
                    {"rank": 5, "title": "Door to Hell", "description": "A crater on fire."},
                    {"rank": 4, "title": "Lake Hillier", "description": "A pink lake."},
                    {"rank": 3, "title": "Socotra Island", "description": "Alien-looking trees."},
                    {"rank": 2, "title": "The Wave", "description": "A stone wave."},
                    {"rank": 1, "title": "Antelope Canyon", "description": "Light beams through stone."},
                ],
                "cta": "Which one would you visit first?",
                "full_script": "full",
                "keywords": ["impossible places"],
                "clips": [],
            }
        )

        beat_queries = [beat["query"] for beat in parsed["beats"]]
        self.assertEqual(
            beat_queries,
            [
                "surreal natural landscape",
                "Door to Hell",
                "Lake Hillier",
                "Socotra Island",
                "The Wave",
                "Antelope Canyon",
                "traveler awe landscape",
            ],
        )

    def test_estimate_segment_durations_preserves_total_audio_length(self):
        import video

        durations = video._estimate_segment_durations(
            [
                "Short hook",
                "A much longer middle section with many more words than the hook",
                "CTA",
            ],
            30.0,
        )

        self.assertEqual(len(durations), 3)
        self.assertAlmostEqual(sum(durations), 30.0, places=3)
        self.assertGreater(durations[1], durations[0])
        self.assertGreater(durations[1], durations[2])

    def test_fetch_footage_for_beats_uses_beat_queries_before_fallback_keywords(self):
        import video

        searched_queries: list[str] = []
        downloaded: list[tuple[str, str]] = []

        def fake_search(query: str, max_results: int = 1):
            searched_queries.append(query)
            if query == "Door to Hell":
                return [{"video_files": [{"width": 720, "link": "https://example.com/door.mp4"}]}]
            if query == "Lake Hillier":
                return [{"video_files": [{"width": 720, "link": "https://example.com/lake.mp4"}]}]
            return []

        def fake_download(url: str, dest: Path):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"mp4")
            downloaded.append((url, dest.name))

        beats = [
            {"text": "Number 5: Door to Hell.", "query": "Door to Hell"},
            {"text": "Number 4: Lake Hillier.", "query": "Lake Hillier"},
        ]

        with patch.object(video, "_search_pexels_videos", side_effect=fake_search):
            with patch.object(video, "_download_file", side_effect=fake_download):
                paths = video.fetch_footage_for_beats(
                    beats,
                    fallback_keywords=["impossible places", "earth mysteries"],
                    clips_dir=Path("/tmp/clipforge-test-sync"),
                )

        self.assertEqual(searched_queries[:2], ["Door to Hell", "Lake Hillier"])
        self.assertEqual([path.name for path in paths], ["clip_00.mp4", "clip_01.mp4"])
        self.assertEqual(
            downloaded,
            [
                ("https://example.com/door.mp4", "clip_00.mp4"),
                ("https://example.com/lake.mp4", "clip_01.mp4"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
