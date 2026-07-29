import unittest

import torch

from webui.audio_processing import join_audio_chunks


class AudioJoiningTests(unittest.TestCase):
    def test_chunks_are_joined_with_requested_silence(self):
        chunks = [torch.ones(4), torch.ones(3)]

        joined = join_audio_chunks(chunks, sample_rate=10, pause_ms=200)

        self.assertEqual(joined.shape[0], 9)
        self.assertTrue(torch.equal(joined[4:6], torch.zeros(2)))

    def test_zero_pause_joins_chunks_directly(self):
        chunks = [torch.ones(2), torch.zeros(2)]

        joined = join_audio_chunks(chunks, sample_rate=10, pause_ms=0)

        self.assertTrue(torch.equal(joined, torch.tensor([1.0, 1.0, 0.0, 0.0])))


if __name__ == "__main__":
    unittest.main()
