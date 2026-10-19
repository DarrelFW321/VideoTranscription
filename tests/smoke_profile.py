"""Explicit browser integration check using only a synthetic test cookie."""
import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from subpipe.browser import browser_page

with tempfile.TemporaryDirectory(prefix="subtitle-profile-") as folder:
    with sync_playwright() as p:
        with browser_page(p, profile=folder, channel="chrome") as page:
            page.context.add_cookies([{"name": "subtitle_test", "value": "ok",
                                       "domain": "example.test", "path": "/", "expires": time.time()+3600}])
        with browser_page(p, profile=folder, channel="chrome") as page:
            assert any(c["name"] == "subtitle_test" and c["value"] == "ok"
                       for c in page.context.cookies("https://example.test"))
print("PASS: dedicated Chrome profile preserves a synthetic cookie across launches")
