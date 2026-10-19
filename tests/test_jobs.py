import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from subpipe.common import digest, file_hash, read_json, save_json
from subpipe.jobs import (ROOT, create_job, export_job, job_paths, job_status, load_job,
                         pipeline_command, prepare_review, translate_job, valid_name)
from subpipe.manual_translation import TranslationPaused


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "A recording.wav"
        self.source.write_bytes(b"test media bytes")
        self.jobs = self.root / "jobs"

    def add(self, **kwargs):
        return create_job(self.source, jobs_root=self.jobs, **kwargs)

    def transcript(self, folder, job):
        _, work = job_paths(folder, job)
        ja = [{"id": "s0", "start": 0, "end": 2, "text": "こんにちは。", "flags": []}]
        en = [{**ja[0], "japanese": ja[0]["text"], "text": "Hello."}]
        save_json(work / "transcript_ja.json", ja)
        save_json(work / "transcript_en.json", en)
        return work, ja, en

    def test_new_jobs_are_isolated_and_input_is_preserved(self):
        folder, job = self.add()
        copied, work = job_paths(folder, job)
        self.assertEqual(file_hash(copied), file_hash(self.source))
        self.assertEqual(job["id"], "A-recording")
        self.assertEqual(work, folder / "work")
        self.assertTrue(self.source.exists())
        other, _ = self.add(name="another")
        self.assertNotEqual(folder, other)
        with self.assertRaises(ValueError):
            self.add()
        for unsafe in ("../escape", "NUL", "nested/job", "C:\\outside", "name."):
            with self.assertRaises(ValueError):
                valid_name(unsafe)

    def test_adopt_preserves_original_paths_and_settings(self):
        existing = self.root / "old-output"
        config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        config["asr"]["chunk_length"] = 20
        settings = {"input_sha256": file_hash(self.source), "start": 0, "test_seconds": None,
                    "model": "kotoba", "preprocess": "gentle", "asr": config["asr"], "audio": config["audio"]}
        manifest = {"fingerprint": digest(settings), "settings": settings}
        save_json(existing / "manifest.json", manifest)
        save_json(existing / "refinement_candidates.json", [])
        folder, job = self.add(existing_work=existing)
        self.assertEqual(job_paths(folder, job), (self.source, existing))
        self.assertEqual(read_json(existing / "manifest.json"), manifest)
        self.assertEqual(job["settings"]["preprocess"], "gentle")
        saved = yaml.safe_load((folder / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(saved["asr"]["chunk_length"], 20)

    def test_sample_and_full_commands_keep_outputs_separate(self):
        folder, job = self.add()
        full, full_work = pipeline_command(folder, job)
        sample, sample_work = pipeline_command(folder, job, seconds=25, start=10)
        self.assertNotEqual(full_work, sample_work)
        self.assertIn("--resume", full)
        self.assertIn("--test-seconds", sample)
        self.assertNotIn("--test-seconds", full)
        self.assertEqual(full[full.index("--translation-provider")+1], "none")

    def test_export_checks_source_alignment_before_overwriting(self):
        folder, job = self.add()
        work, ja, en = self.transcript(folder, job)
        destination = export_job(folder, job)
        self.assertEqual(job_status(folder, job)["english"], 1)
        vtt = destination / f"{job['id']}_en.vtt"
        before = vtt.read_bytes()
        ja[0]["text"] = "ありがとう。"
        save_json(work / "transcript_ja.json", ja)
        with self.assertRaises(ValueError):
            export_job(folder, job)
        self.assertEqual(vtt.read_bytes(), before)
        self.assertEqual(job_status(folder, job)["state"], "English needs refresh")

    def test_review_edits_and_selection_survive_pause(self):
        folder, job = self.add()
        self.transcript(folder, job)
        target = prepare_review(folder, job)
        reviewed = read_json(target)
        reviewed[0]["text"] = "ありがとう。"
        save_json(target, reviewed)
        prepare_review(folder, job)
        self.assertEqual(read_json(target), reviewed)
        with patch("subpipe.manual_translation.run_manual", side_effect=TranslationPaused):
            with self.assertRaises(TranslationPaused):
                translate_job(folder, job, reviewed=True)
        self.assertEqual(job_status(folder, job)["state"], "English needs refresh")
        with self.assertRaises(ValueError):
            export_job(folder, job)
        translated = [{**reviewed[0], "japanese": reviewed[0]["text"], "text": "Thank you."}]
        with patch("subpipe.manual_translation.run_manual", return_value=translated) as mock:
            translate_job(folder, job)
            self.assertEqual(mock.call_args.args[0], reviewed)
        self.assertTrue(read_json(folder / "translation_source.json")["reviewed"])
