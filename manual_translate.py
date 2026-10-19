"""Guided clipboard translation. Google runs in normal Chrome, without automation."""
import argparse
from pathlib import Path

from subpipe.common import read_json, save_json, transcript_stem
from subpipe.manual_translation import ManualSession, TranslationPaused, run_manual
from subpipe.subtitles import export


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", type=Path, default=Path("output/transcript_ja.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--stem", help="Export filename stem; inferred from audio metadata by default")
    parser.add_argument("--max-chars", type=int, default=3500)
    parser.add_argument("--batch-segments", type=int, default=60)
    parser.add_argument("--context", type=int, default=2)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    args.stem = args.stem or transcript_stem(args.transcript)
    if not args.transcript.is_file():
        parser.error(f"Transcript not found: {args.transcript}. Run Japanese transcription first.")
    segments = read_json(args.transcript)
    folder = args.output_dir / "translation"
    if args.prepare_only:
        session = ManualSession(segments, folder, args.max_chars, args.batch_segments, args.context)
        print(f"Prepared {len(session.batches)} batches in {session.folder}")
        return
    try:
        english = run_manual(segments, folder, args.max_chars, args.batch_segments,
                             args.context, not args.no_browser)
    except TranslationPaused as exc:
        print(exc)
        return
    save_json(args.output_dir / "transcript_en.json", english)
    duration = max((s["end"] for s in segments), default=0)
    warnings = export(english, args.output_dir / f"{args.stem}_en", duration)
    save_json(args.output_dir / "validation_manual.json", {"format_timing_valid": True, "warnings": warnings})
    print(f"Done: {args.output_dir / (args.stem + '_en.vtt')} (and .srt)")


if __name__ == "__main__":
    main()
