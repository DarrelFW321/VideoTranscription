"""Numbered copy/paste translation with strict alignment and resumable progress."""
import re
from pathlib import Path
from urllib.parse import quote

from .common import digest, read_json, save_json


class TranslationPaused(Exception):
    pass


def translation_url(source):
    return "https://translate.google.com/?sl=ja&tl=en&op=translate&text=" + quote(source, safe="")


def make_batches(segments, max_chars=3500, max_segments=60, context=2):
    if not 100 <= max_chars <= 4500 or max_segments < 1 or context < 0:
        raise ValueError("Use 100–4500 characters, positive batch size and nonnegative context")
    if len({s["id"] for s in segments}) != len(segments):
        raise ValueError("Transcript IDs must be unique")
    def render(indices):
        return "\n".join(f"{i+1:04d} {' '.join(segments[i]['text'].split())}" for i in indices)
    batches, start = [], 0
    while start < len(segments):
        end, neighbors = min(len(segments), start + max_segments), context
        while True:
            indices = list(range(max(0, start-neighbors), min(len(segments), end+neighbors)))
            source = render(indices)
            if len(source) <= max_chars and len(translation_url(source)) < 24000:
                break
            if end-start > 1:
                end -= 1
            elif neighbors:
                neighbors -= 1
            else:
                raise ValueError(f"Caption {start+1} exceeds the batch limit; split it in the reviewed transcript")
        batches.append({"targets": list(range(start+1, end+1)), "expected": [i+1 for i in indices], "source": source})
        start = end
    return batches


def parse_paste(text, expected):
    text = normalize_paste(text)
    expected = set(expected)
    # Find labels throughout the text: Google can collapse every caption into
    # one paragraph. Non-label years/quantities must stay inside the dialogue.
    markers = [m for m in re.finditer(r"(?<!\w)([0-9]{4,})(?![0-9])(?=\s|[.:：)]|$)[.:：)]?", text)
               if m[1].startswith("0") or int(m[1]) in expected]
    if not markers or text[:markers[0].start()].strip():
        raise ValueError("Copy the numbered English result, starting with its first caption number.")
    values = {}
    for i, marker in enumerate(markers):
        number = int(marker[1])
        if number in values:
            raise ValueError(f"Number {number:04d} appears twice. Copy only the English translation.")
        end = markers[i+1].start() if i+1 < len(markers) else len(text)
        values[number] = " ".join(text[marker.end():end].split())
    missing, extra = set(expected)-set(values), set(values)-set(expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(f"{i:04d}" for i in sorted(missing)[:5]))
        if extra:
            detail.append("unexpected " + ", ".join(f"{i:04d}" for i in sorted(extra)[:5]))
        raise ValueError("Caption numbers don't match: " + "; ".join(detail))
    for number, value in values.items():
        if not value.strip():
            raise ValueError(f"Caption {number:04d} is empty.")
        if re.search(r"[\u3040-\u30ff]", value):
            raise ValueError(f"Caption {number:04d} still contains Japanese. Copy the English side.")
    return values


def normalize_paste(text):
    # Normalize digit glyphs only, preserving the English wording/punctuation.
    return text.strip().lstrip("\ufeff").translate(str.maketrans("０１２３４５６７８９", "0123456789"))


class ManualSession:
    def __init__(self, segments, folder, max_chars=3500, max_segments=60, context=2):
        self.segments = segments
        self.batches = make_batches(segments, max_chars, max_segments, context)
        identity = [{k: s[k] for k in ("id", "start", "end", "text")} for s in segments]
        self.fingerprint = digest({"schema": 1, "segments": identity, "batches": self.batches})
        self.folder = Path(folder) / ("manual_" + self.fingerprint[:16])
        self.folder.mkdir(parents=True, exist_ok=True)
        self.values = {}
        for i, batch in enumerate(self.batches):
            (self.folder / f"batch_{i+1:03d}_ja.txt").write_text(batch["source"], encoding="utf-8")
            path = self.folder / f"batch_{i+1:03d}_en.json"
            if path.exists():
                record = read_json(path)
                if record["fingerprint"] != self.fingerprint:
                    raise ValueError("Manual translation checkpoint does not match source")
                self._store(i, parse_paste(record["raw"], batch["expected"]))
        save_json(self.folder / "manifest.json", {"fingerprint": self.fingerprint, "batches": self.batches})

    def _store(self, index, parsed):
        for number in self.batches[index]["targets"]:
            self.values[number] = "[inaudible]" if self.segments[number-1]["text"] == "[inaudible]" else parsed[number]

    @property
    def pending(self):
        return next((i for i, b in enumerate(self.batches) if any(n not in self.values for n in b["targets"])), None)

    def accept(self, raw):
        index = self.pending
        if index is None:
            raise ValueError("All batches are already complete")
        batch = self.batches[index]
        if raw.strip() == batch["source"].strip():
            raise ValueError("Clipboard still contains the Japanese input")
        parsed = parse_paste(raw, batch["expected"])
        save_json(self.folder / f"batch_{index+1:03d}_en.json",
                  {"fingerprint": self.fingerprint, "raw": raw})
        self._store(index, parsed)
        save_json(self.folder / "progress.json", {"complete_captions": len(self.values), "total_captions": len(self.segments)})

    def result(self):
        if self.pending is not None:
            raise TranslationPaused("Translation paused. Run the same command to continue.")
        return [{**s, "japanese": s["text"], "text": self.values[i]}
                for i, s in enumerate(self.segments, 1)]


def run_manual(segments, folder, max_chars=3500, max_segments=60, context=2, open_browser=True):
    session = ManualSession(segments, folder, max_chars, max_segments, context)
    if session.pending is None:
        return session.result()
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Subtitle translation — copy and paste")
    root.geometry("620x440")
    root.attributes("-topmost", True)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    progress, status = tk.StringVar(), tk.StringVar()
    ttk.Label(frame, textvariable=progress, font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Google opens with the numbered Japanese already filled in.\n"
                         "Click Copy translation on Google's English side.\n"
                         "This window saves it and opens the next batch automatically.\n"
                         "If Google opens blank, paste with Ctrl+V—the input is also copied.",
              justify="left", padding=(0, 10)).pack(anchor="w")
    preview = tk.Text(frame, height=8, wrap="word", font=("Segoe UI", 10))
    preview.pack(fill="both", expand=True)
    ttk.Label(frame, textvariable=status, wraplength=580, padding=(0, 10)).pack(anchor="w")
    bar = ttk.Frame(frame)
    bar.pack(fill="x")
    last_seen = None

    def copy_current(message="Input ready. Click Copy translation on Google's English side.", navigate=False):
        nonlocal last_seen
        index = session.pending
        if index is None:
            return
        source = session.batches[index]["source"]
        root.clipboard_clear()
        root.clipboard_append(source)
        root.update_idletasks()
        last_seen = source
        progress.set(f"Batch {index+1} of {len(session.batches)}  ·  {len(session.values)}/{len(segments)} captions saved")
        preview.config(state="normal")
        preview.delete("1.0", "end")
        preview.insert("1.0", source)
        preview.config(state="disabled")
        status.set(message)
        if navigate and open_browser:
            open_translate()

    def check_clipboard():
        nonlocal last_seen
        try:
            raw = root.clipboard_get()
        except tk.TclError:
            root.after(700, check_clipboard)
            return
        if raw != last_seen:
            last_seen = raw
            # Ignore unrelated clipboard contents without saving or logging them.
            if re.match(r"^[0-9]{4,}(?=\s|[.:：)]|$)", normalize_paste(raw)):
                try:
                    session.accept(raw)
                except ValueError as exc:
                    status.set(str(exc))
                else:
                    if session.pending is None:
                        root.destroy()
                        return
                    copy_current("English saved. Next batch opened. Click Copy translation when ready.", navigate=True)
        root.after(700, check_clipboard)

    def open_translate():
        from google_profile import main as open_profile
        try:
            index = session.pending
            open_profile(translation_url(session.batches[index]["source"]))
        except (OSError, SystemExit) as exc:
            status.set(f"Open translate.google.com in your normal browser. {exc}")

    ttk.Button(bar, text="Copy Japanese again", command=copy_current).pack(side="left")
    ttk.Button(bar, text="Open Google Translate", command=open_translate).pack(side="left", padx=8)
    ttk.Button(bar, text="Pause and close", command=root.destroy).pack(side="right")
    copy_current(navigate=True)
    root.after(700, check_clipboard)
    root.mainloop()
    return session.result()
