import unittest

from webui.text_processing import split_text


class TextSplittingTests(unittest.TestCase):
    def test_chunks_do_not_exceed_limit(self):
        text = "First sentence. " + ("word " * 100)

        chunks = split_text(text, 100)

        self.assertTrue(chunks)
        self.assertTrue(all(0 < len(chunk) <= 100 for chunk in chunks))

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(split_text(" \n\t ", 300), [])


if __name__ == "__main__":
    unittest.main()
