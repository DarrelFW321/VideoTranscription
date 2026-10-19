"""Build a local, offline player with synchronized caption text."""
import html
import json
import subprocess
from pathlib import Path

from . import jobs
from .common import read_json


def set_thumbnail(folder, image):
    """Normalize a user-supplied image without replacing a good cover on failure."""
    image = Path(image).resolve()
    if not image.is_file() or image.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        raise ValueError("Choose an existing JPG, PNG, WebP, BMP or GIF image")
    destination = Path(folder) / "thumbnail.jpg"
    pending = Path(folder) / "thumbnail.part.jpg"
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(image),
                        "-frames:v", "1", "-update", "1", str(pending)], check=True)
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)
    return destination


def build_player(folder, job):
    folder = Path(folder).resolve()
    source, work = jobs.job_paths(folder, job)
    _, japanese = jobs.source_for_export(folder, work)
    english = read_json(work / "transcript_en.json") if (work / "transcript_en.json").exists() else []
    if english and not jobs.english_matches(japanese, english):
        raise ValueError("English captions are stale. Translate again before opening the player.")
    media = folder / "playback.mp3"
    if not media.exists() or media.stat().st_mtime < source.stat().st_mtime:
        pending = folder / "playback.part.mp3"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(pending)], check=True)
            pending.replace(media)
        finally:
            pending.unlink(missing_ok=True)
    title = html.escape(job.get("web", {}).get("title", job["id"]))
    data = json.dumps({"ja": japanese, "en": english}, ensure_ascii=True).replace("<", "\\u003c")
    poster = '<img src="thumbnail.jpg" alt="Recording artwork">' if (folder / "thumbnail.jpg").exists() else '<div class="placeholder">Audio recording</div>'
    template = (Path(__file__).parent / "player.html").read_text(encoding="utf-8")
    for key, value in {"TITLE": title, "POSTER": poster, "DATA": data}.items():
        template = template.replace("{{" + key + "}}", value)
    destination = folder / "watch.html"
    destination.write_text(template, encoding="utf-8")
    return destination
