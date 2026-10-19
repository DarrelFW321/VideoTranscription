"""Manage independent audio projects while keeping the existing pipeline usable."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

from .common import digest, file_hash, read_json, save_json

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "jobs"
MEDIA_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".mp4", ".mkv", ".webm"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise ValueError("Job name must use 1–80 letters, numbers, hyphens or underscores")
    if name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("Choose a job name that is not a reserved Windows filename")
    return name


def source_name(source):
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(source).stem).strip("-_")[:70]
    return valid_name(name or "audio")


def load_job(name, jobs_root=JOBS):
    folder = Path(jobs_root) / valid_name(name)
    if not (folder / "job.json").is_file():
        raise ValueError(f"Unknown job '{name}'. Use 'list' to see available jobs.")
    return folder, read_json(folder / "job.json")


def job_paths(folder, job):
    return (folder / job["input"]).resolve(), (folder / job["work"]).resolve()


def create_job(source, name=None, jobs_root=JOBS, template=ROOT / "config.yaml", existing_work=None,
               preprocess="both", refine=True):
    source = Path(source).resolve()
    if not source.is_file() or source.suffix.lower() not in MEDIA_SUFFIXES:
        raise ValueError("Choose an existing audio/media file (MP3, WAV, FLAC, M4A, OGG, etc.)")
    name = valid_name(name) if name else source_name(source)
    folder = Path(jobs_root).resolve() / name
    if folder.exists():
        raise ValueError(f"Job '{name}' already exists. Resume it or choose --name ANOTHER_NAME.")
    config = yaml.safe_load(Path(template).read_text(encoding="utf-8"))
    settings = {"model": "kotoba", "preprocess": preprocess, "second_pass": refine, "second_model": "kotoba"}
    checksum = file_hash(source)
    if existing_work is not None:
        work = Path(existing_work).resolve()
        manifest = read_json(work / "manifest.json")
        saved = manifest["settings"]
        if saved["input_sha256"] != checksum:
            raise ValueError("Existing output belongs to a different audio file")
        if saved.get("test_seconds") is not None or saved.get("start", 0) != 0:
            raise ValueError("Adopt a full-recording run, not a sample output")
        config["asr"], config["audio"] = saved["asr"], saved["audio"]
        settings.update(model=saved["model"], preprocess=saved["preprocess"],
                        second_pass=(work / "refinement_candidates.json").exists())
        input_ref, work_ref = str(source), str(work)
    else:
        input_ref, work_ref = f"input/{source.name}", "work"
    folder.mkdir(parents=True)
    if existing_work is None:
        target = folder / input_ref
        target.parent.mkdir()
        shutil.copy2(source, target)
        if file_hash(target) != checksum:
            raise IOError("Copied input checksum does not match the source")
        (folder / "work").mkdir()
    (folder / "exports").mkdir()
    (folder / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    job = {"schema": 1, "id": name, "created_at": now(), "input": input_ref, "work": work_ref,
           "source_name": source.name, "input_sha256": checksum, "settings": settings,
           "adopted": existing_work is not None}
    save_json(folder / "job.json", job)
    return folder, job


def pipeline_command(folder, job, device="auto", seconds=None, start=0):
    source, work = job_paths(folder, job)
    if seconds is not None:
        if seconds <= 0 or start < 0:
            raise ValueError("Sample duration must be positive and start nonnegative")
        work = folder / "samples" / f"start-{start:g}_seconds-{seconds:g}"
    options = job["settings"]
    cmd = [sys.executable, str(ROOT / "main.py"), "--input", str(source), "--output-dir", str(work),
           "--config", str(folder / "config.yaml"), "--model", options["model"],
           "--device", device, "--preprocess", options["preprocess"], "--translation-provider", "none", "--resume"]
    if options["second_pass"]:
        cmd += ["--second-pass", "--second-model", options["second_model"], "--second-device", device]
    if seconds is not None:
        cmd += ["--test-seconds", str(seconds), "--start", str(start)]
    return cmd, work


def selected_source(folder, work, reviewed=False):
    if reviewed:
        path = folder / "reviewed_ja.json"
    else:
        path = work / "transcript_ja.json"
    if not path.is_file():
        raise ValueError(f"Transcript not found: {path}. Run transcribe/review first.")
    segments = read_json(path)
    if not isinstance(segments, list) or not segments:
        raise ValueError("Transcript must be a nonempty segment list")
    seen = set()
    for s in segments:
        if s["id"] in seen or not isinstance(s["text"], str) or not s["text"].strip() or not 0 <= s["start"] < s["end"]:
            raise ValueError("Transcript contains duplicate IDs, empty text or invalid timestamps; review it first")
        seen.add(s["id"])
    environment = work / "environment.json"
    if environment.exists():
        duration = float(read_json(environment)["audio"]["format"]["duration"])
        if any(s["end"] > duration + .001 for s in segments):
            raise ValueError("A transcript caption extends beyond the audio duration")
    return path, segments


def english_matches(japanese, english):
    if not isinstance(english, list) or len(japanese) != len(english):
        return False
    return all(a.get("id") == b.get("id") and a.get("text") == b.get("japanese")
               and a.get("start") == b.get("start") and a.get("end") == b.get("end")
               and isinstance(b.get("text"), str) and bool(b["text"].strip()) for a, b in zip(japanese, english))


def source_for_export(folder, work):
    choice = folder / "translation_request.json"
    if not choice.exists():
        choice = folder / "translation_source.json"
    reviewed = read_json(choice)["reviewed"] if choice.exists() else False
    return selected_source(folder, work, reviewed)


def export_job(folder, job):
    from .subtitles import export
    _, work = job_paths(folder, job)
    path, ja = source_for_export(folder, work)
    destination = folder / "exports"
    destination.mkdir(exist_ok=True)
    end = max(s["end"] for s in ja)
    en_path = work / "transcript_en.json"
    en = None
    if en_path.exists():
        en = read_json(en_path)
        if not english_matches(ja, en):
            raise ValueError("English captions do not match the selected Japanese transcript. Run translate again.")
    warnings = {"ja": export(ja, destination / f"{job['id']}_ja", end)}
    languages = ["ja"]
    if en is not None:
        warnings["en"] = export(en, destination / f"{job['id']}_en", end)
        languages.append("en")
    save_json(destination / "validation.json", {"format_timing_valid": True, "warnings": warnings})
    save_json(destination / "manifest.json", {"exported_at": now(), "source": str(path),
                                             "transcript_hash": digest(ja), "languages": languages})
    return destination


def transcribe_job(folder, job, device="auto", seconds=None, start=0):
    source, _ = job_paths(folder, job)
    if not source.is_file() or file_hash(source) != job["input_sha256"]:
        raise ValueError("Job input is missing or changed. Register the new recording as a new job.")
    cmd, work = pipeline_command(folder, job, device, seconds, start)
    subprocess.run(cmd, cwd=ROOT, check=True)
    return work


def translate_job(folder, job, reviewed=None, work_override=None, open_browser=True):
    from .manual_translation import run_manual
    _, work = job_paths(folder, job)
    work = work_override or work
    request = folder / "translation_request.json"
    if reviewed is None:
        reviewed = read_json(request)["reviewed"] if request.exists() and not work_override else False
    path, segments = selected_source(folder, work, reviewed)
    if not work_override:
        save_json(request, {"reviewed": reviewed, "path": str(path)})
    config = yaml.safe_load((folder / "config.yaml").read_text(encoding="utf-8"))["translation"]
    english = run_manual(segments, work / "translation", config.get("manual_max_chars", 3500),
                         config.get("manual_batch_segments", 60), config.get("manual_context_segments", 2), open_browser)
    save_json(work / "transcript_en.json", english)
    if work_override:
        from .subtitles import export
        export(english, work / f"{job['id']}_en", max(s["end"] for s in segments))
        return work
    save_json(folder / "translation_source.json", {"reviewed": reviewed, "path": str(path), "hash": digest(segments)})
    return export_job(folder, job)


def prepare_review(folder, job):
    _, work = job_paths(folder, job)
    source, _ = selected_source(folder, work)
    target = folder / "reviewed_ja.json"
    if not target.exists():
        shutil.copy2(source, target)
    return target


def job_status(folder, job):
    source, work = job_paths(folder, job)
    result = {"id": job["id"], "state": "ready to transcribe", "japanese": 0, "english": 0,
              "input": str(source), "work": str(work), "exports": str(folder / "exports")}
    if not source.exists():
        result["state"] = "input missing"
        return result
    if not (work / "transcript_ja.json").exists():
        if list((work / "asr").glob("*/block_*.json")):
            result["state"] = "transcription started (resume available)"
        return result
    _, ja = source_for_export(folder, work)
    result["japanese"] = len(ja)
    result["state"] = "ready to translate"
    result["flagged"] = sum(bool(s.get("flags")) for s in ja)
    if (work / "transcript_en.json").exists():
        en = read_json(work / "transcript_en.json")
        if english_matches(ja, en):
            result["english"] = len(en)
            result["state"] = "translated (review warnings may remain)"
        else:
            result["state"] = "English needs refresh"
    return result
