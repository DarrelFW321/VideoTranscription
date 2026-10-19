"""Capture direct media requests from a user-operated browser page."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

import requests

from . import jobs
from .common import save_json

ARTWORK_SCRIPT = (Path(__file__).with_name("player_artwork.js")).read_text(encoding="utf-8")


def http_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use an http:// or https:// page URL")
    return value


def media_suffix(url, content_type):
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in jobs.MEDIA_SUFFIXES:
        return suffix
    return {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a",
            "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/ogg": ".ogg",
            "video/mp4": ".mp4", "video/webm": ".webm"}.get(content_type.split(";")[0].strip().lower())


class LinkCapture:
    """Keep requests from the supplied link's page, including its child frames."""

    def __init__(self, page, url):
        self.page = page
        self.url = url
        self.documents = {}
        self.frames = {}
        self.candidates = {}

    def snapshot(self):
        try:
            details = self.page.evaluate(ARTWORK_SCRIPT)
            previous = self.documents.get(details["page_url"], {})
            if previous.get("poster") and not details.get("poster"):
                details = {**details, "poster": previous["poster"], "artwork_score": previous.get("artwork_score", 0)}
            self.documents[details["page_url"]] = details
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    artwork = frame.evaluate(ARTWORK_SCRIPT)
                    if artwork.get("poster"):
                        self.frames[(details["page_url"], frame.url)] = artwork
                except Exception:
                    continue
            for item in self.candidates.values():
                if item["page_url"] == details["page_url"]:
                    item["details"] = self.details_for(details["page_url"], item.get("frame_url"))
        except Exception:
            # Navigation or closing a tab must not discard captured requests.
            pass

    def details_for(self, page_url, frame_url):
        details = self.documents.get(page_url, {}).copy()
        embedded = self.frames.get((page_url, frame_url), {})
        if embedded.get("poster") and embedded.get("artwork_score", 0) >= details.get("artwork_score", 0):
            details.update(poster=embedded["poster"], artwork_referrer=frame_url)
        return details

    def response(self, response):
        try:
            # Frame ownership stays with the original page across redirects;
            # popup/ad tabs have a different Page even if they take focus.
            if response.request.frame.page != self.page:
                return
            suffix = media_suffix(response.url, response.headers.get("content-type", ""))
            if not suffix or not response.ok or response.url in self.candidates:
                return
            headers = response.request.all_headers()
            page_url = self.page.url
            frame_url = response.request.frame.url
            self.candidates[response.url] = {"url": response.url, "suffix": suffix,
                "headers": headers, "page_url": page_url, "frame_url": frame_url,
                "details": self.details_for(page_url, frame_url)}
        except Exception:
            # Service-worker requests can lack an owning frame.
            return


def download(session, url, target, headers, limit):
    """Stream a complete resource; never retain a partial download as input."""
    part = target.with_suffix(target.suffix + ".part")
    try:
        with session.get(http_url(url), headers=headers, stream=True, timeout=(20, 60)) as response:
            response.raise_for_status()
            if response.status_code == 206:
                raise ValueError("Server returned only a media fragment, not the complete recording")
            size = 0
            with part.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError("Download exceeds the configured size limit")
                    output.write(chunk)
            if not size:
                raise ValueError("The downloaded resource was empty")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def import_url(url, name=None, capture_seconds=60, media_index=None, jobs_root=jobs.JOBS):
    from playwright.sync_api import sync_playwright, Error as BrowserError
    http_url(url)
    if not 5 <= capture_seconds <= 600:
        raise ValueError("Capture time must be between 5 and 600 seconds")
    if name:
        jobs.valid_name(name)
        if (Path(jobs_root) / name).exists():
            raise ValueError(f"Job '{name}' already exists; use run/watch to resume it")
    with tempfile.TemporaryDirectory(prefix="subtitle-import-") as temporary, sync_playwright() as pw:
        temp = Path(temporary)
        browser = pw.chromium.launch(channel="chrome", headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            capture = LinkCapture(page, url)
            context.on("response", capture.response)
            page.on("domcontentloaded", lambda: capture.snapshot())
            print(f"Watching the supplied link for {capture_seconds} seconds. Press Play on its page. Popup tabs are ignored.", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except BrowserError:
                if page.is_closed():
                    raise ValueError("The supplied link's tab closed before capture began; keep it open and retry")
                print("Navigation was interrupted or timed out; continuing to watch the supplied link's tab.")
            deadline = time.monotonic() + capture_seconds
            while time.monotonic() < deadline and not page.is_closed():
                capture.snapshot()
                try:
                    page.wait_for_timeout(min(500, max(0, (deadline - time.monotonic()) * 1000)))
                except BrowserError:
                    if not page.is_closed():
                        raise
            found = list(capture.candidates.values())
            if not found:
                raise ValueError("No direct audio/video request found. Press Play during capture. HLS/DASH/blob-only streams are not supported.")
            if media_index is None and len(found) > 1:
                for index, item in enumerate(found, 1):
                    # Avoid printing signed URL query strings.
                    parsed = urlsplit(item["url"])
                    print(f"{index}: {parsed.hostname}{parsed.path}")
                media_index = int(input("Choose the recording number: "))
            index = (media_index or 1) - 1
            if not 0 <= index < len(found):
                raise ValueError("Media number is outside the captured list")
            selected = found[index]
            details = selected["details"]
            title = details.get("title") or name or "Recording"
            poster = details.get("poster")
            headers = {key: value for key, value in selected["headers"].items()
                       if key.lower() in {"user-agent", "referer", "origin", "authorization", "accept"}}
            headers.setdefault("Referer", selected["page_url"])
            with requests.Session() as session:
                for cookie in context.cookies():
                    session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"], secure=cookie["secure"])
                source = temp / ("recording" + selected["suffix"])
                download(session, selected["url"], source, headers, 4 * 1024**3)
                # Validate that an actual audio stream exists before registering the job.
                probe = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(source)], text=True)
                if not probe.strip():
                    raise ValueError("The captured file has no audio stream")
                thumbnail = None
                if poster:
                    try:
                        raw = temp / "poster-source"
                        download(session, poster, raw, {"Referer": details.get("artwork_referrer", selected["page_url"])}, 20 * 1024**2)
                        thumbnail = temp / "thumbnail.jpg"
                        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-frames:v", "1", str(thumbnail)], check=True, capture_output=True)
                    except (requests.RequestException, ValueError, subprocess.CalledProcessError):
                        thumbnail = None
                        print("Page thumbnail could not be downloaded; the player will use a plain background.")
                else:
                    print("No downloadable player artwork or page thumbnail was found.")
            folder, job = jobs.create_job(source, name or jobs.source_name(title), jobs_root=jobs_root)
            if thumbnail:
                shutil.copy2(thumbnail, folder / "thumbnail.jpg")
            # Do not persist signed media URLs, cookies, or authentication headers.
            job["web"] = {"title": title, "page_url": url, "thumbnail": "thumbnail.jpg" if thumbnail else None}
            save_json(folder / "job.json", job)
            return folder, job
        finally:
            browser.close()
