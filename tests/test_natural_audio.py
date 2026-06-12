import unittest

from video import should_prefer_natural_audio


class NaturalAudioHeuristicTests(unittest.TestCase):
    def test_detects_lyrebird_sound_hook(self):
        self.assertTrue(
            should_prefer_natural_audio(
                "Lyrebirds Can Copy Chainsaws, Camera Shutters, and Car Alarms",
                "lyrebird mimic sounds",
            )
        )

    def test_ignores_non_sound_topics(self):
        self.assertFalse(
            should_prefer_natural_audio(
                "This Tiny Shrimp Creates Temperatures Hotter Than the Sun",
                "marine physics pistol shrimp cavitation",
            )
        )


if __name__ == "__main__":
    unittest.main()
