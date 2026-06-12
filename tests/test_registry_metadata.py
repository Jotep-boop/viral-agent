import unittest


class RegistryMetadataTests(unittest.TestCase):
    def test_build_registry_entry_includes_pillar_and_hook_type(self):
        from content_registry import build_registry_entry

        entry = build_registry_entry(
            topic="The shortest war in history lasted 38 minutes",
            theme="military history",
            pillar="history / timeline shocks",
            hook_type="comparison-shock",
            fact_summary="The Anglo-Zanzibar War of 1896 lasted only 38 minutes.",
            hook_angle="A war shorter than a coffee break feels fake.",
            keywords=["war", "history"],
            entry_id="clipforge-2026-06-07-013",
        )

        self.assertEqual(entry["pillar"], "history / timeline shocks")
        self.assertEqual(entry["hook_type"], "comparison-shock")


if __name__ == "__main__":
    unittest.main()
