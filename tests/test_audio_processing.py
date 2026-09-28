import unittest

import numpy as np

from webui.audio_processing import join_audio_chunks


class AudioJoiningTests(unittest.TestCase):
    def test_chunks_are_joined_with_requested_silence(self):
        chunks = [np.ones(4), np.ones(3)]

        joined = join_audio_chunks(chunks, sample_rate=10, pause_ms=200)

        self.assertEqual(joined.shape[0], 9)
        np.testing.assert_array_equal(joined[4:6], np.zeros(2))

    def test_zero_pause_joins_chunks_directly(self):
        chunks = [np.ones(2), np.zeros(2)]

        joined = join_audio_chunks(chunks, sample_rate=10, pause_ms=0)

        np.testing.assert_array_equal(joined, np.array([1.0, 1.0, 0.0, 0.0]))


if __name__ == "__main__":
    unittest.main()
