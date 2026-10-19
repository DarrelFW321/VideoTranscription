import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from subpipe.common import read_json
from subpipe.refinement import review
from subpipe.subtitles import export
from subpipe.transcription import transcribe, segments_from_result
from subpipe.translation import parse_translation, translate


class FakeRecognizer:
    options = {"block_length": 10, "overlap": 2}
    calls = 0

    def infer(self, data):
        self.calls += 1
        # Same utterance occurs in the overlapping border of adjacent blocks.
        timestamps = [9, 11] if self.calls == 1 else [1, 3]
        return {"chunks": [{"timestamp": timestamps, "text": "こんにちは。"}]}


class PipelineTests(unittest.TestCase):
    def test_overlap_ownership_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            r = FakeRecognizer()
            audio = np.ones(20 * 16000, dtype=np.float32) * .01
            result = transcribe(audio, r, folder, offset=60)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["start"], 69)
            self.assertEqual(r.calls, 2)
            self.assertEqual(result, transcribe(audio, r, folder, resume=True, offset=60))
            self.assertEqual(r.calls, 2)

    def test_export_overlap_unicode_and_hours(self):
        with tempfile.TemporaryDirectory() as folder:
            segments = [{"id": "a", "start": 3600, "end": 3603, "text": "日本語 & English"},
                        {"id": "b", "start": 3602, "end": 3605, "text": "Second voice"}]
            prefix = Path(folder) / "test"
            warnings = export(segments, prefix, 3605)
            self.assertTrue(warnings)
            self.assertIn("01:00:00.000 --> 01:00:05.000", prefix.with_suffix(".vtt").read_text())
            self.assertIn("Second voice", prefix.with_suffix(".srt").read_text(encoding="utf-8"))

    def test_invalid_timestamp_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                export([{"id": "a", "start": 2, "end": 1, "text": "x"}], Path(folder)/"bad", 5)

    def test_no_fake_confidence_or_inaudible(self):
        segments = segments_from_result({"chunks": [{"timestamp": [None, 2], "text": "小声"}]}, 10, 3)
        self.assertIn("estimated_timestamp", segments[0]["flags"])
        segments[0]["id"] = "a"
        review(segments, np.ones(48000, dtype=np.float32)*.0001, 10,
               {"quiet_db": -43, "max_caption_seconds": 10, "gap_seconds": 1})
        self.assertEqual(segments[0]["text"], "小声")
        self.assertNotIn("confidence", segments[0])

    def test_translation_context_cache_and_validation(self):
        segments = [{"id": "a", "start": 0, "end": 1, "text": "こんにちは"},
                    {"id": "b", "start": 2, "end": 3, "text": "ありがとう"}]
        calls = []
        def provider(payload):
            calls.append(payload)
            return json.dumps({s["id"]: {"a": "Hello.", "b": "Thank you."}[s["id"]] for s in payload["targets"]})
        cfg = {"batch_segments": 1, "context_segments": 1, "glossary": {}}
        with tempfile.TemporaryDirectory() as folder:
            result = translate(segments, cfg, Path(folder), provider=provider)
            self.assertEqual(calls[0]["context_after"][0]["ja"], "ありがとう")
            self.assertEqual(calls[1]["previous_english"][0]["en"], "Hello.")
            self.assertEqual(result[1]["start"], 2)
            translate(segments, cfg, Path(folder), resume=True, provider=provider)
            self.assertEqual(len(calls), 2)
            segments[1]["text"] = "ありがとうございます"
            translate(segments, cfg, Path(folder), resume=True, provider=provider)
            self.assertEqual(len(calls), 4)
        with self.assertRaises(ValueError):
            parse_translation('{"wrong": "Hello"}', ["a"])
        with self.assertRaises(ValueError):
            parse_translation('{"a": "こんにちは"}', ["a"])


if __name__ == "__main__":
    unittest.main()
