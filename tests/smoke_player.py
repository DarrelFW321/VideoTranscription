"""Offline browser checks using a generated tone and neutral sample captions."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from subpipe.common import save_json
from subpipe.jobs import create_job
from subpipe.player import build_player


with tempfile.TemporaryDirectory(prefix="player-smoke-") as temporary:
    root = Path(temporary)
    source = root / "sample.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=6", str(source)], check=True)
    folder, job = create_job(source, jobs_root=root / "jobs")
    ja = [{"id": "s1", "start": 0, "end": 2, "text": "こんにちは。"},
          {"id": "s2", "start": 3, "end": 5, "text": "また明日。"}]
    en = [{**s, "japanese": s["text"], "text": text}
          for s, text in zip(ja, ["Hello.", "See you tomorrow."])]
    save_json(folder / "work/transcript_ja.json", ja)
    save_json(folder / "work/transcript_en.json", en)
    player = build_player(folder, job)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(player.as_uri())
        page.wait_for_function("document.querySelector('audio').readyState >= 1")
        assert page.locator("#transcript button").count() == 2
        assert "Hello." in page.locator("#caption").inner_text()
        page.evaluate("document.querySelector('audio').currentTime=2.5")
        page.wait_for_function("document.querySelector('#caption span').hidden")
        page.locator("#transcript button").nth(1).click()
        page.wait_for_function("document.querySelector('audio').currentTime >= 3")
        page.evaluate("document.querySelector('audio').pause()")
        assert "See you tomorrow." in page.locator("#caption").inner_text()
        page.select_option("#speed", "1.5")
        assert page.evaluate("document.querySelector('audio').playbackRate") == 1.5
        page.select_option("#language", "ja")
        assert page.locator("#caption").inner_text() == "また明日。"
        page.select_option("#language", "off")
        assert page.locator("#caption span").is_hidden()
        for width in [320, 375, 414, 768, 1280]:
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        (folder / "work/transcript_en.json").unlink()
        build_player(folder, job)
        page.reload()
        assert page.locator("#language").input_value() == "ja"
        assert page.locator('#language option[value="en"]').is_disabled()
        assert not errors, errors
        browser.close()
print("PASS: audio loading, captions, gaps, seeking, speed, languages, Japanese-only fallback, and five viewport widths")
