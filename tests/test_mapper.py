import unittest

from mx4_rumble_bridge.config import BridgeConfig
from mx4_rumble_bridge.mapper import RumbleMapper


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class RumbleMapperTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.mapper = RumbleMapper(BridgeConfig(), self.clock)

    def test_deadzone(self):
        self.assertIsNone(self.mapper.map(0.0, 0.0))
        self.assertIsNone(self.mapper.map(0.07, 0.0))

    def test_low_frequency_levels(self):
        self.assertEqual(self.mapper.map(0.10, 0.0).pattern, "Nudge")
        self.clock.advance(0.1)
        self.assertEqual(self.mapper.map(0.50, 0.0).pattern, "Strong")
        self.clock.advance(0.1)
        self.assertEqual(self.mapper.map(1.0, 0.0).pattern, "Burst")

    def test_high_frequency_and_mixed(self):
        self.assertEqual(self.mapper.map(0.0, 0.80).pattern, "Strong")
        self.clock.advance(0.1)
        self.assertEqual(self.mapper.map(0.80, 0.80).pattern, "Buzz")

    def test_intensity_is_clamped_and_scaled(self):
        event = self.mapper.map(0.21, 0.0)
        self.assertEqual(event.intensity, 21)
        self.clock.advance(0.1)
        self.assertEqual(self.mapper.map(1.0, 0.0).intensity, 100)

    def test_rate_limit_and_repeat(self):
        self.assertIsNotNone(self.mapper.map(0.2, 0.0))
        self.assertIsNone(self.mapper.map(0.3, 0.0))
        self.clock.advance(0.071)
        self.assertIsNotNone(self.mapper.map(0.3, 0.0))

    def test_stop_allows_next_rumble(self):
        self.assertIsNotNone(self.mapper.map(0.5, 0.0))
        self.clock.advance(0.01)
        self.assertIsNone(self.mapper.map(0.0, 0.0))
        self.clock.advance(0.01)
        self.assertIsNotNone(self.mapper.map(0.5, 0.0))


if __name__ == "__main__":
    unittest.main()