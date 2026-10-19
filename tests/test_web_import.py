from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from subpipe.web_import import LinkCapture


class LinkCaptureTests(unittest.TestCase):
    def test_redirect_retains_original_media_and_artwork_and_ignores_popup(self):
        page = Mock(url="https://example.test/recording")
        page.frames = []
        original = {"page_url": page.url, "title": "Recording", "poster": "https://example.test/cover.jpg"}
        page.evaluate.return_value = original
        capture = LinkCapture(page, page.url)
        capture.snapshot()

        def response(owner, url):
            return SimpleNamespace(url=url, ok=True, headers={"content-type": "audio/mpeg"},
                request=SimpleNamespace(frame=SimpleNamespace(page=owner, url=owner.url),
                    all_headers=lambda: {"referer": original["page_url"]}))

        capture.response(response(page, "https://cdn.test/recording.mp3"))
        capture.response(response(Mock(), "https://ads.test/advert.mp3"))
        page.url = "https://example.test/redirect"
        page.evaluate.return_value = {"page_url": page.url, "title": "Redirect", "poster": None}
        capture.snapshot()
        self.assertEqual(len(capture.candidates), 1)
        selected = next(iter(capture.candidates.values()))
        self.assertEqual(selected["details"], original)
        self.assertEqual(selected["page_url"], original["page_url"])
        # Legitimate media loaded after a same-tab redirect is still captured.
        capture.response(response(page, "https://cdn.test/second.mp3"))
        self.assertEqual(len(capture.candidates), 2)

    def test_metadata_loaded_after_media_request_updates_only_matching_document(self):
        page = Mock(url="https://example.test/watch")
        page.frames = []
        capture = LinkCapture(page, page.url)
        capture.response(SimpleNamespace(url="https://cdn.test/audio.mp3", ok=True,
            headers={}, request=SimpleNamespace(frame=SimpleNamespace(page=page, url=page.url), all_headers=lambda: {})))
        page.evaluate.return_value = {"page_url": page.url, "title": "Loaded", "poster": "https://cdn.test/image.jpg"}
        capture.snapshot()
        self.assertEqual(next(iter(capture.candidates.values()))["details"]["title"], "Loaded")
        page.evaluate.side_effect = RuntimeError("Page closed")
        capture.snapshot()
        self.assertEqual(len(capture.candidates), 1)

    def test_artwork_from_media_frame_wins_and_survives_disappearing_cover(self):
        page = Mock(url="https://example.test/watch")
        frame = Mock(url="https://embed.test/player")
        other = Mock(url="https://ads.test/player")
        page.frames = [frame, other]
        page.evaluate.return_value = {"page_url": page.url, "title": "Recording", "poster": "https://example.test/social.jpg", "artwork_score": 50}
        frame.evaluate.return_value = {"poster": "https://embed.test/cover.jpg", "artwork_score": 120}
        other.evaluate.return_value = {"poster": "https://ads.test/ad.jpg", "artwork_score": 120}
        capture = LinkCapture(page, page.url)
        capture.snapshot()
        capture.response(SimpleNamespace(url="https://cdn.test/audio.mp3", ok=True,
            headers={}, request=SimpleNamespace(frame=SimpleNamespace(page=page, url=frame.url), all_headers=lambda: {})))
        selected = next(iter(capture.candidates.values()))
        self.assertEqual(selected["details"]["poster"], "https://embed.test/cover.jpg")
        self.assertEqual(selected["details"]["artwork_referrer"], frame.url)
        frame.evaluate.return_value = {"poster": None}
        capture.snapshot()
        self.assertEqual(selected["details"]["poster"], "https://embed.test/cover.jpg")
