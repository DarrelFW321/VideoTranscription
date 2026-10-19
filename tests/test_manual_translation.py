import tempfile
from pathlib import Path
import unittest

from subpipe.manual_translation import ManualSession, TranslationPaused, make_batches, parse_paste, translation_url


def segments(n=5):
    return [{"id": f"s{i:05d}", "start": i*3+60, "end": i*3+62, "text": "こんにちは。", "flags": []}
            for i in range(n)]


class ManualTests(unittest.TestCase):
    def test_collapsed_numbered_paragraph(self):
        self.assertEqual(parse_paste("0001 Hello. 0002 No, it's nothing. 0003 Come in!", [1, 2, 3]),
                         {1: "Hello.", 2: "No, it's nothing.", 3: "Come in!"})

    def test_wrapping_unicode_and_label_punctuation(self):
        self.assertEqual(parse_paste("\ufeff０００２： No,\n it's nothing.\u00a0０００１: Hello.", [1, 2]),
                         {2: "No, it's nothing.", 1: "Hello."})
        self.assertEqual(parse_paste("0001 Hello.0002 Come in.", [1, 2]),
                         {1: "Hello.", 2: "Come in."})

    def test_ordinary_numbers_remain_dialogue(self):
        self.assertEqual(parse_paste("0001 In 2026 there were 10000 people. 0002 Pay 1234 yen.", [1, 2]),
                         {1: "In 2026 there were 10000 people.", 2: "Pay 1234 yen."})
        for raw in ("0001 Hello. 0001 Again.", "0001 Hello. 0003 Extra.", "0001 0002 Hi."):
            with self.assertRaises(ValueError):
                parse_paste(raw, [1, 2])

    def test_context_limits_and_coverage(self):
        parts = make_batches(segments(), max_segments=2, context=1)
        self.assertEqual([p["targets"] for p in parts], [[1, 2], [3, 4], [5]])
        self.assertEqual(parts[1]["expected"], [2, 3, 4, 5])
        self.assertTrue(parts[0]["source"].startswith("0001 "))
        self.assertTrue(all(len(translation_url(b["source"])) < 24000 for b in parts))

    def test_long_url_is_split_without_lost_text(self):
        source = segments(8)
        for s in source:
            s["text"] = "あ" * 900
        parts = make_batches(source, max_chars=4500)
        self.assertEqual([i for b in parts for i in b["targets"]], list(range(1, 9)))
        self.assertTrue(all(len(translation_url(b["source"])) < 24000 for b in parts))

    def test_multiline_out_of_order_and_invalid_pastes(self):
        self.assertEqual(parse_paste("0002 No,\nit's nothing.\n0001 Hello.", [1, 2]),
                         {2: "No, it's nothing.", 1: "Hello."})
        for raw in ("0001 Hello.", "0001 A\n0001 B", "0001 こんにちは\n0002 Hi.",
                    "0001 \n0002 Hi.", "Unnumbered output", "0001 A\n0002 B\n0003 C"):
            with self.assertRaises(ValueError):
                parse_paste(raw, [1, 2])

    def test_resume_and_timing(self):
        source = segments(3)
        with tempfile.TemporaryDirectory() as folder:
            session = ManualSession(source, folder, max_segments=2, context=1)
            session.accept("0001 Hello.\n0002 Welcome.\n0003 Come in.")
            self.assertEqual(session.pending, 1)
            with self.assertRaises(TranslationPaused):
                session.result()
            resumed = ManualSession(source, folder, max_segments=2, context=1)
            self.assertEqual(resumed.pending, 1)
            resumed.accept("0002 Welcome back.\n0003 Come in!")
            result = resumed.result()
            self.assertEqual(result[1]["text"], "Welcome.")  # Context cannot overwrite earlier decisions.
            self.assertEqual(result[2]["text"], "Come in!")
            self.assertEqual(result[2]["start"], source[2]["start"])
            source[0]["text"] = "ありがとう。"
            changed = ManualSession(source, folder, max_segments=2, context=1)
            self.assertNotEqual(changed.folder, resumed.folder)
            self.assertEqual(changed.pending, 0)

    def test_rejected_clipboard_is_not_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            session = ManualSession(segments(1), folder)
            with self.assertRaises(ValueError):
                session.accept(session.batches[0]["source"])
            self.assertEqual(list(session.folder.glob("*_en.json")), [])
