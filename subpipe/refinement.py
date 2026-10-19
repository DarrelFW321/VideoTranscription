import re

from .audio import RATE, activity, dbfs
from .common import save_json, read_json
from .transcription import segments_from_result


def compare_variants(primary, alternative):
    findings = []
    for s in primary:
        matches = [c for c in alternative if min(s["end"], c["end"]) > max(s["start"], c["start"])]
        norm = lambda text: re.sub(r"[\W_]", "", text)
        if norm(s["text"]) != norm("".join(c["text"] for c in matches)):
            s.setdefault("flags", []).append("preprocessing_disagreement")
            findings.append({"primary_id": s["id"], "primary": s, "alternative": matches,
                             "decision": "manual_review_required"})
    for c in alternative:
        if not any(min(s["end"], c["end"]) > max(s["start"], c["start"]) for s in primary):
            findings.append({"primary_id": None, "alternative": [c], "decision": "possible_missing_dialogue"})
    return findings


def review(segments, audio, offset, config):
    for s in segments:
        a, b = round((s["start"] - offset) * RATE), round((s["end"] - offset) * RATE)
        level = dbfs(audio[max(0, a):max(0, b)])
        s["rms_dbfs"] = level
        flags = s.setdefault("flags", [])
        if level < config["quiet_db"]:
            flags.append("quiet_or_silence_hallucination_risk")
        if s["end"] - s["start"] > config["max_caption_seconds"]:
            flags.append("long_caption")
        if re.search(r"(.{2,12})\1{2,}", s["text"]):
            flags.append("repetition")
        if any(t in s["text"] for t in ("ご視聴", "チャンネル登録", "字幕")):
            flags.append("common_hallucination_phrase_check_audio")
        if len(s["text"]) / max(.01, s["end"] - s["start"]) > 15:
            flags.append("high_text_density")
        s["flags"] = sorted(set(flags))
    # Uncovered audible intervals are candidates, NOT proof of missing dialogue.
    uncovered = []
    for frame in activity(audio):
        a, b = offset + frame["start"], offset + frame["end"]
        if any(s["start"] < b and s["end"] > a for s in segments):
            continue
        if uncovered and a <= uncovered[-1]["end"] + .01:
            uncovered[-1]["end"] = b
        else:
            uncovered.append({"start": a, "end": b, "reason": "uncovered_audio_activity"})
    return [g for g in uncovered if g["end"] - g["start"] >= config["gap_seconds"]]


def refine(segments, gaps, alternative_audio, offset, recognizer, folder, resume):
    tasks = [{"id": s["id"], "start": s["start"], "end": s["end"], "original": s["text"]}
             for s in segments if s["flags"]]
    tasks += [{"id": f"gap{i:05}", **g, "original": None} for i, g in enumerate(gaps)]
    records = []
    for task in tasks:
        path = folder / (task["id"] + ".json")
        if resume and path.exists():
            records.append(read_json(path))
            continue
        a = max(0, task["start"] - offset - 3)
        b = min(len(alternative_audio) / RATE, task["end"] - offset + 3)
        raw = recognizer.infer(alternative_audio[round(a * RATE):round(b * RATE)],
                               chunk=max(2 * recognizer.options["overlap"] + 2, recognizer.options["chunk_length"] - 4))
        record = {**task, "candidate": segments_from_result(raw, offset + a, b - a),
                  "raw": raw, "decision": "manual_review_required", "model": recognizer.name}
        save_json(path, record)
        records.append(record)
    return records
