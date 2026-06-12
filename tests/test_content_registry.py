import json
import tempfile
import unittest
from pathlib import Path


class ContentRegistryTests(unittest.TestCase):
    def _write_registry(self, entries):
        tmpdir = tempfile.TemporaryDirectory()
        path = Path(tmpdir.name) / "content_registry.json"
        path.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        self.addCleanup(tmpdir.cleanup)
        return path

    def test_duplicate_topic_is_detected_case_insensitively(self):
        from content_registry import is_duplicate_candidate

        registry_path = self._write_registry([
            {
                "topic": "Octopuses Have Three Hearts",
                "fact_summary": "An octopus has three hearts.",
            }
        ])

        self.assertTrue(
            is_duplicate_candidate(
                topic="octopuses have three hearts",
                fact_summary="Completely different summary",
                registry_path=registry_path,
            )
        )

    def test_duplicate_fact_summary_is_detected_even_with_punctuation_changes(self):
        from content_registry import is_duplicate_candidate

        registry_path = self._write_registry([
            {
                "topic": "Original topic",
                "fact_summary": "Honey can last for thousands of years!",
            }
        ])

        self.assertTrue(
            is_duplicate_candidate(
                topic="Fresh topic",
                fact_summary="Honey can last for thousands of years",
                registry_path=registry_path,
            )
        )

    def test_near_duplicate_fact_summary_is_detected_with_fuzzy_matching(self):
        from content_registry import is_duplicate_candidate

        registry_path = self._write_registry([
            {
                "topic": "Honey can outlast civilizations",
                "theme": "food science",
                "theme_slug": "food-science-honey-never-spoils",
                "fact_summary": "Honey resists spoilage because it is low in water, acidic, and naturally hostile to microbes.",
                "hook_angle": "An everyday kitchen item suddenly feels ancient and indestructible.",
            }
        ])

        self.assertTrue(
            is_duplicate_candidate(
                topic="Why honey basically never spoils",
                theme="food science",
                fact_summary="Honey almost never goes bad because it contains very little water and microbes struggle to survive in it.",
                hook_angle="A normal food item feels weirdly immortal once you learn why it lasts so long.",
                registry_path=registry_path,
            )
        )

    def test_near_duplicate_hook_is_detected_when_theme_and_topic_overlap(self):
        from content_registry import is_duplicate_candidate

        registry_path = self._write_registry([
            {
                "topic": "Sharks are older than trees",
                "theme": "deep time",
                "theme_slug": "deep-time-sharks-older-than-trees",
                "fact_summary": "Sharks existed roughly 400 million years ago, while the first trees appeared around 350 million years ago.",
                "hook_angle": "Time-scale comparison that makes familiar things feel absurd.",
            }
        ])

        self.assertTrue(
            is_duplicate_candidate(
                topic="Sharks existed before trees",
                theme="deep time",
                fact_summary="A timeline comparison shows sharks appeared tens of millions of years before the first trees.",
                hook_angle="A timeline comparison makes two familiar things feel impossible together.",
                registry_path=registry_path,
            )
        )

    def test_distinct_clip_is_not_marked_as_duplicate(self):
        from content_registry import is_duplicate_candidate

        registry_path = self._write_registry([
            {
                "topic": "Honey can outlast civilizations",
                "theme": "food science",
                "theme_slug": "food-science-honey-never-spoils",
                "fact_summary": "Honey resists spoilage because it is low in water, acidic, and naturally hostile to microbes.",
                "hook_angle": "An everyday kitchen item suddenly feels ancient and indestructible.",
            }
        ])

        self.assertFalse(
            is_duplicate_candidate(
                topic="Bananas are berries but strawberries are not",
                theme="food science",
                fact_summary="Bananas are botanically berries while strawberries are not, based on scientific fruit classification.",
                hook_angle="Reveals that common fruit names are scientifically misleading.",
                registry_path=registry_path,
            )
        )

    def test_append_registry_entry_persists_new_script_metadata(self):
        from content_registry import append_registry_entry

        registry_path = self._write_registry([])
        entry = {
            "id": "clipforge-test-001",
            "status": "generated",
            "topic": "Sharks are older than trees",
            "theme": "deep time",
            "theme_slug": "deep-time-sharks-older-than-trees",
            "fact_summary": "Sharks existed before trees.",
            "hook_angle": "Timeline comparison",
            "keywords": ["shark", "ancient earth"],
        }

        append_registry_entry(entry, registry_path=registry_path)

        data = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["topic"], entry["topic"])
        self.assertEqual(data["entries"][0]["theme_slug"], entry["theme_slug"])


if __name__ == "__main__":
    unittest.main()
