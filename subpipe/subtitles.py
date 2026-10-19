from datetime import timedelta
import html
import re
import textwrap

import srt
import webvtt


def layout(text, width=42):
    text = " ".join(text.split())
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False))


def captions(segments, duration):
    # Keep source timestamps untouched in JSON. Serialize overlaps together so no words disappear.
    groups = []
    warnings = []
    for s in sorted(segments, key=lambda s: (s["start"], s["end"])):
        a, b = round(max(0, s["start"]), 3), round(min(duration, s["end"]), 3)
        if b <= a:
            raise ValueError(f"Caption {s['id']} has invalid timing; correct the review transcript")
        if groups and a < groups[-1]["end"]:
            groups[-1]["end"] = max(b, groups[-1]["end"])
            groups[-1]["text"] += " / " + s["text"]
            warnings.append({"id": s["id"], "issue": "overlap_grouped_review_required"})
        else:
            groups.append({"start": a, "end": b, "text": s["text"]})
    for i, c in enumerate(groups):
        c["text"] = layout(c["text"])
        span = c["end"] - c["start"]
        if len(c["text"].splitlines()) > 2 or span > 10 or len(c["text"]) / span > 22:
            warnings.append({"caption": i+1, "issue": "readability_review_required"})
    return groups, warnings


def export(segments, prefix, duration):
    groups, warnings = captions(segments, duration)
    items = [srt.Subtitle(i+1, timedelta(seconds=c["start"]), timedelta(seconds=c["end"]),
                          html.escape(c["text"], quote=False)) for i, c in enumerate(groups)]
    srt_path, vtt_path = prefix.with_suffix(".srt"), prefix.with_suffix(".vtt")
    srt_path.write_text(srt.compose(items), encoding="utf-8")
    vtt = webvtt.WebVTT()
    for item in items:
        stamp = lambda t: srt.timedelta_to_srt_timestamp(t).replace(",", ".")
        vtt.captions.append(webvtt.Caption(stamp(item.start), stamp(item.end), item.content))
    vtt.save(str(vtt_path))
    validate(srt_path, vtt_path, duration, len(items))
    return warnings


def validate(srt_path, vtt_path, duration, expected):
    subtitles = list(srt.parse(srt_path.read_text(encoding="utf-8")))
    vtt = webvtt.read(str(vtt_path))
    if len(subtitles) != expected or len(vtt.captions) != expected:
        raise ValueError("Subtitle roundtrip lost captions")
    previous = 0
    for a, b in zip(subtitles, vtt.captions):
        start, end = a.start.total_seconds(), a.end.total_seconds()
        if not 0 <= previous <= start < end <= duration + .001:
            raise ValueError("Subtitle timing validation failed")
        def seconds(stamp):
            h, m, s = stamp.split(":")
            return int(h)*3600 + int(m)*60 + float(s)
        if abs(start - seconds(b.start)) > .001 or abs(end - seconds(b.end)) > .001:
            raise ValueError("SRT/VTT timestamps disagree")
        previous = end
