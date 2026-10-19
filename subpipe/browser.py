"""Persistent, user-owned Google session without copying browser credentials."""
from contextlib import contextmanager
from pathlib import Path

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / ".browser-profile"


@contextmanager
def browser_page(playwright, headed=False, profile=None, channel=None, stealth=False):
    options = {"headless": not headed}
    if channel:
        options["channel"] = channel
    if stealth:
        options["ignore_default_args"] = ["--enable-automation"]
        options["args"] = ["--disable-blink-features=AutomationControlled"]
    browser = None
    if profile:
        context = playwright.chromium.launch_persistent_context(
            str(Path(profile).resolve()), accept_downloads=True,
            viewport={"width": 1280, "height": 900}, **options)
    else:
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(accept_downloads=True, locale="en-US")
    try:
        if stealth:
            from playwright_stealth import Stealth
            # Apply to the explicitly created context; avoid the package's
            # launch wrapper, which does not support persistent contexts.
            Stealth(init_scripts_only=True, navigator_languages=False,
                    navigator_languages_override=None, navigator_platform_override=None,
                    navigator_user_agent=False, navigator_platform=False,
                    navigator_vendor=False, webgl_vendor=False,
                    navigator_hardware_concurrency=False, sec_ch_ua=False).apply_stealth_sync(context)
        page = context.new_page()
        yield page
    finally:
        context.close()
        if browser:
            browser.close()
