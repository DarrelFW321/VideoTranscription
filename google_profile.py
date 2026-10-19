"""Open normal Chrome so the user can sign in to the dedicated translation profile."""
import os
from pathlib import Path
import subprocess

from subpipe.browser import DEFAULT_PROFILE


def main(url="https://translate.google.com/?sl=ja&tl=en&op=translate"):
    candidates = [Path(os.environ.get(root, "")) / "Google/Chrome/Application/chrome.exe"
                  for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    chrome = next((p for p in candidates if p.is_file()), None)
    if chrome is None:
        raise SystemExit("Google Chrome was not found. Install Chrome before setting up this profile.")
    DEFAULT_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(chrome), f"--user-data-dir={DEFAULT_PROFILE}", "--no-first-run",
                      url])
    print("Chrome opened with the dedicated translation profile.")
    print("Sign in yourself, then close all windows of this profile before running the pipeline.")


if __name__ == "__main__":
    main()
