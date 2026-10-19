"""Export/upload/import a transcript without loading a recognition model."""
import argparse
from pathlib import Path

from subpipe.common import read_json, save_json, transcript_stem
from subpipe.google_web import export_document, import_document, translate_google
from subpipe.subtitles import export


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--transcript", required=True, type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--stem", help="Export filename stem; inferred from audio metadata by default")
    p.add_argument("--export-only", action="store_true")
    p.add_argument("--import-docx", type=Path)
    p.add_argument("--headed", action="store_true")
    p.add_argument("--stealth", action="store_true", help="Experimental Playwright stealth mode")
    p.add_argument("--profile", type=Path, help="Dedicated persistent Chrome profile")
    p.add_argument("--channel", choices=["chrome", "msedge", "chromium"])
    p.add_argument("--resume", action="store_true")
    p.add_argument("--method", choices=["text", "document"], default="text")
    a = p.parse_args()
    a.stem = a.stem or transcript_stem(a.transcript)
    segments = read_json(a.transcript)
    a.output_dir.mkdir(parents=True, exist_ok=True)
    source = a.output_dir / f"{a.stem}_ja.docx"
    export_document(segments, source)
    if a.export_only:
        print(f"Upload {source} to https://translate.google.com/?sl=ja&tl=en&op=docs")
        return
    translated = import_document(segments, a.import_docx) if a.import_docx else translate_google(
        segments, a.output_dir / "translation", a.resume, a.headed, a.method,
        profile=a.profile, channel=a.channel, stealth=a.stealth)
    save_json(a.output_dir / "transcript_en.json", translated)
    duration = max((s["end"] for s in segments), default=0)
    warnings = export(translated, a.output_dir / f"{a.stem}_en", duration)
    save_json(a.output_dir / "validation.json", {"format_timing_valid": True, "warnings": warnings})
    print(f"English SRT/VTT written to {a.output_dir}")


if __name__ == "__main__":
    main()
