from pathlib import Path
import tempfile
import unittest
import json

from subpipe.google_web import export_document, import_document, parse_numbered, json_batches, parse_json_translation


class GoogleWebTests(unittest.TestCase):
    def test_json_context_batches_and_alignment(self):
        segments = [{"id": f"s{i:05d}", "text": "こんにちは"} for i in range(8)]
        batches = json_batches(segments, batch_size=3, context=1)
        self.assertEqual([(a, b) for a, b, _ in batches], [(0, 3), (3, 6), (6, 8)])
        payload = json.loads(batches[1][2])
        self.assertEqual(payload["payload"]["context_before"][0]["id"], "s00002")
        self.assertEqual(payload["payload"]["context_after"][0]["id"], "s00006")
        ids = [s["id"] for s in payload["payload"]["targets"]]
        for s in payload["payload"]["targets"]:
            s["ja"] = "Hello."
        self.assertEqual(set(parse_json_translation(json.dumps(payload), ids)), set(ids))
        payload["payload"]["targets"].append(payload["payload"]["targets"][0])
        with self.assertRaises(ValueError):
            parse_json_translation(json.dumps(payload), ids)

    def test_numbered_alignment(self):
        result = parse_numbered("00000001 Hello.\n00000002 No, it's nothing.", [1, 2])
        self.assertEqual(result[2], "No, it's nothing.")
        for bad in ["00000001 Hello.", "00000001 A\n00000001 B", "00000001 こんにちは\n00000002 Hello"]:
            with self.assertRaises(ValueError):
                parse_numbered(bad, [1, 2])

    def test_document_roundtrip_preserves_source_timing(self):
        source = [{"id": "s00000", "start": 61.25, "end": 65.55, "text": "こんにちは", "flags": []}]
        translated = [{**source[0], "text": "Hello."}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "english.docx"
            export_document(translated, path)
            output = import_document(source, path)
            self.assertEqual(output[0]["start"], 61.25)
            self.assertEqual(output[0]["end"], 65.55)
            self.assertEqual(output[0]["text"], "Hello.")
            self.assertEqual(output[0]["japanese"], source[0]["text"])
            export_document(source, path)
            with self.assertRaises(ValueError):
                import_document(source, path)
