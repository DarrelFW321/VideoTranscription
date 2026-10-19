import argparse
import logging
import os
from pathlib import Path

# Keep downloaded models and trusted upstream code inside this project.
os.environ.setdefault("HF_HOME", str(Path(__file__).parent / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import soundfile as sf
import yaml

from subpipe.audio import RATE, metadata, prepare
from subpipe.common import digest, file_hash, read_json, save_json
from subpipe.refinement import compare_variants, refine, review
from subpipe.subtitles import export
from subpipe.transcription import Recognizer, hardware, transcribe
from subpipe.translation import translate


def main():
    parser = argparse.ArgumentParser(description="Japanese audio to reviewed English subtitles")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--model", choices=["kotoba", "large-v3"], default="kotoba")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--preprocess", choices=["none", "gentle", "both"], default="none")
    parser.add_argument("--chunk-length", type=float)
    parser.add_argument("--overlap", type=float)
    parser.add_argument("--second-pass", action="store_true")
    parser.add_argument("--second-model", choices=["kotoba", "large-v3"], default="kotoba")
    parser.add_argument("--second-device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--translation-provider", choices=["manual", "local", "api", "google-web", "none"])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--test-seconds", type=float)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--reviewed-transcript", type=Path, help="JSON list of corrected segments; bypass ASR")
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(out / "run.log", encoding="utf-8")])
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    for cli, key in [(args.chunk_length, "chunk_length"), (args.overlap, "overlap")]:
        if cli is not None:
            config["asr"][key] = cli
    if args.translation_provider:
        config["translation"]["provider"] = args.translation_provider
    if not 0 <= config["asr"]["overlap"] * 2 < config["asr"]["chunk_length"] <= 30:
        parser.error("Require 0 <= 2*overlap < chunk-length <= 30")
    if config["asr"]["block_length"] <= 0 or config["asr"]["beams"] < 1:
        parser.error("block_length and beams must be positive")
    meta = metadata(args.input)
    duration = float(meta["format"]["duration"])
    if not 0 <= args.start < duration or (args.test_seconds is not None and args.test_seconds <= 0):
        parser.error("Invalid sample start/duration")
    hw = hardware()
    logging.info("Hardware: %s", hw)
    save_json(out / "environment.json", {"hardware": hw, "audio": meta})
    if args.inspect:
        return
    signature = {"schema": 1, "input_sha256": file_hash(args.input), "start": args.start,
                 "test_seconds": args.test_seconds, "preprocess": args.preprocess,
                 "asr": config["asr"], "audio": config["audio"], "model": args.model}
    fingerprint = digest(signature)
    manifest = out / "manifest.json"
    if manifest.exists():
        existing = read_json(manifest)
        if existing["fingerprint"] != fingerprint:
            raise ValueError("Output belongs to different input/ASR settings. Choose a new output directory.")
        if not args.resume:
            raise ValueError("Output exists. Use --resume or a new output directory.")
    save_json(manifest, {"fingerprint": fingerprint, "settings": signature})
    need_processed = args.preprocess != "none" or args.second_pass
    audio_paths = prepare(args.input, out / "audio", config["audio"], args.start, args.test_seconds, need_processed)
    original, _ = sf.read(audio_paths["original"], dtype="float32")
    sample_end = args.start + len(original) / RATE
    variants = ["original", "processed"] if args.preprocess == "both" else ["processed" if args.preprocess == "gentle" else "original"]
    primary = variants[0]
    recognizer = Recognizer(args.model, args.device, config["asr"])
    if args.reviewed_transcript:
        segments = read_json(args.reviewed_transcript)
        if not isinstance(segments, list) or len({s["id"] for s in segments}) != len(segments):
            raise ValueError("Reviewed transcript needs a list with unique ids")
        for s in segments:
            if not args.start <= s["start"] < s["end"] <= sample_end + .001 or not s["text"].strip():
                raise ValueError("Reviewed transcript contains invalid text/timestamps")
    else:
        variant_results = {}
        for variant in variants:
            data, _ = sf.read(audio_paths[variant], dtype="float32")
            candidate = transcribe(data, recognizer, out / "asr" / variant, args.resume, args.start)
            save_json(out / f"transcript_{variant}.json", candidate)
            variant_results[variant] = candidate
            if variant == primary:
                segments = candidate
        recognizer.close()
        if len(variants) == 2:
            save_json(out / "comparison.json", compare_variants(segments, variant_results["processed"]))
    gaps = review(segments, original, args.start, config["review"])
    save_json(out / "transcript_ja.json", segments)
    save_json(out / "review.json", {"segments": [s for s in segments if s["flags"]], "activity_gaps": gaps,
                                    "notice": "Flags are heuristics, not confidence scores. Gaps may be sound effects."})
    if args.second_pass:
        alternative = "processed" if primary == "original" else "original"
        data, _ = sf.read(audio_paths[alternative], dtype="float32")
        second = Recognizer(args.second_model, args.second_device, config["asr"])
        refine_key = digest({"segments": segments, "gaps": gaps, "model": args.second_model, "audio": alternative})[:16]
        records = refine(segments, gaps, data, args.start, second, out / "refinement" / refine_key, args.resume)
        save_json(out / "refinement_candidates.json", records)
        second.close()
    stem = args.input.stem
    warnings = {"ja": export(segments, out / f"{stem}_ja", sample_end)}
    if config["translation"]["provider"] != "none":
        from subpipe.manual_translation import TranslationPaused
        try:
            english = translate(segments, config["translation"], out / "translation", args.resume)
        except TranslationPaused as exc:
            logging.info("%s Use manual_translate.py --transcript %s --output-dir %s", exc, out / "transcript_ja.json", out)
            return
        save_json(out / "transcript_en.json", english)
        warnings["en"] = export(english, out / f"{stem}_en", sample_end)
    save_json(out / "validation.json", {"valid": True, "duration": sample_end, "warnings": warnings,
                                       "review_count": sum(bool(s["flags"]) for s in segments), "activity_gaps": len(gaps)})
    logging.info("Done. Subtitle format/timing validated; inspect review.json and validation.json for accuracy/readability issues.")


if __name__ == "__main__":
    main()
