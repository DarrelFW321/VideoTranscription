"""Exercise real Tk event loop with an in-memory clipboard; no Google request."""
import sys
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subpipe.manual_translation import run_manual
from subpipe.subtitles import export

original_tk = tk.Tk
clipboard = {}


def test_window():
    root = original_tk()
    root.withdraw()
    root.clipboard_clear = lambda: clipboard.update(text="")
    root.clipboard_append = lambda text: clipboard.update(text=text)
    root.clipboard_get = lambda: clipboard["text"]
    root.after(300, lambda: clipboard.update(text="0001 Hello.\n0002 Come in."))
    root.after(5000, root.destroy)
    return root


with tempfile.TemporaryDirectory() as folder, patch.object(tk, "Tk", test_window):
    source = [{"id": "a", "start": 1, "end": 2, "text": "こんにちは。"},
              {"id": "b", "start": 3, "end": 5, "text": "どうぞ。"}]
    result = run_manual(source, folder, open_browser=False)
    assert result[0]["text"] == "Hello."
    assert result[1]["start"] == 3
    export(result, Path(folder) / "smoke_en", 5)
print("PASS: GUI polling, acceptance, completion, and SRT/VTT export (simulated clipboard)")
