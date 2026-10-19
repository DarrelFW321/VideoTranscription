"""Reusable job CLI: add, list, sample, transcribe, review, translate, run, export."""
import argparse
import json
import subprocess
import webbrowser
from pathlib import Path

from subpipe import jobs
from subpipe.manual_translation import TranslationPaused


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage Japanese audio translation jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("from-url", help="Capture website audio, transcribe, translate and open a player")
    cmd.add_argument("url")
    cmd.add_argument("--name")
    cmd.add_argument("--capture-seconds", type=int, default=60)
    cmd.add_argument("--media-index", type=int)
    cmd.add_argument("--import-only", action="store_true")
    cmd.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    cmd.add_argument("--no-open", action="store_true")
    cmd = commands.add_parser("watch", help="Open audio, artwork and synchronized subtitles")
    cmd.add_argument("job")
    cmd.add_argument("--no-open", action="store_true")
    cmd = commands.add_parser("thumbnail", help="Attach your own cover image to a recording")
    cmd.add_argument("job")
    cmd.add_argument("image", type=Path)
    for name in ("add", "adopt"):
        cmd = commands.add_parser(name, help="Copy a new recording" if name == "add" else "Register existing pipeline output in place")
        cmd.add_argument("input", type=Path)
        cmd.add_argument("--name")
        if name == "add":
            cmd.add_argument("--preprocess", choices=["none", "gentle", "both"], default="both")
            cmd.add_argument("--no-refine", action="store_true")
        else:
            cmd.add_argument("--output", type=Path, required=True)
    commands.add_parser("list", help="Show all recordings and their progress")
    for name in ("status", "run", "sample", "transcribe", "review", "translate", "export"):
        cmd = commands.add_parser(name)
        cmd.add_argument("job")
        if name in ("run", "sample", "transcribe"):
            cmd.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
        if name in ("run", "sample", "translate"):
            cmd.add_argument("--no-browser", action="store_true")
        if name == "sample":
            cmd.add_argument("--seconds", type=float, default=30)
            cmd.add_argument("--start", type=float, default=0)
            cmd.add_argument("--translate", action="store_true")
        if name == "translate":
            cmd.add_argument("--reviewed", action="store_true", default=None, help="Use this job's reviewed_ja.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "from-url":
            from subpipe.web_import import import_url
            from subpipe.player import build_player
            folder, job = import_url(args.url, args.name, args.capture_seconds, args.media_index)
            args.job = job["id"]
            print(f"Registered {job['id']}: {folder}")
            if args.import_only:
                return 0
            jobs.transcribe_job(folder, job, args.device)
            jobs.export_job(folder, job)
            # Preserve a usable Japanese player even if English translation is paused.
            player = build_player(folder, job)
            try:
                jobs.translate_job(folder, job)
            finally:
                player = build_player(folder, job)
                print(f"Player: {player}")
                if not args.no_open:
                    webbrowser.open(player.as_uri())
            return 0
        if args.command in ("add", "adopt"):
            options = {"existing_work": args.output} if args.command == "adopt" else {"preprocess": args.preprocess, "refine": not args.no_refine}
            folder, job = jobs.create_job(args.input, args.name, **options)
            print(f"Registered {job['id']}: {folder}")
            if args.command == "adopt" and (args.output / "transcript_ja.json").exists():
                print(f"Exports: {jobs.export_job(folder, job)}")
            print(f"Next: .\\audio.ps1 run {job['id']}")
            return
        if args.command == "list":
            found = sorted(jobs.JOBS.glob("*/job.json"))
            if not found:
                print('No jobs yet. Use: .\\audio.ps1 add "path\\recording.mp3"')
            for file in found:
                folder, job = jobs.load_job(file.parent.name)
                try:
                    status = jobs.job_status(folder, job)
                    print(f"{status['id']:<24} JA {status['japanese']:>5}  EN {status['english']:>5}  {status['state']}")
                except (ValueError, KeyError) as exc:
                    print(f"{job['id']}: needs attention: {exc}")
            return
        folder, job = jobs.load_job(args.job)
        if args.command == "thumbnail":
            from subpipe.player import set_thumbnail
            print(f"Thumbnail saved: {set_thumbnail(folder, args.image)}")
            print(f"Open/rebuild the player with: .\\audio.ps1 watch {job['id']}")
        elif args.command == "watch":
            from subpipe.player import build_player
            player = build_player(folder, job)
            print(f"Player: {player}")
            if not args.no_open:
                webbrowser.open(player.as_uri())
        elif args.command == "status":
            print(json.dumps(jobs.job_status(folder, job), indent=2, ensure_ascii=True))
        elif args.command == "review":
            print(f"Edit: {jobs.prepare_review(folder, job)}")
            print(f"Then: .\\audio.ps1 translate {job['id']} --reviewed")
        elif args.command == "export":
            print(f"Exports: {jobs.export_job(folder, job)}")
        elif args.command == "sample":
            work = jobs.transcribe_job(folder, job, args.device, args.seconds, args.start)
            if args.translate:
                jobs.translate_job(folder, job, work_override=work, open_browser=not args.no_browser)
            print(f"Sample: {work}")
        elif args.command == "transcribe":
            print(f"Japanese transcript: {jobs.transcribe_job(folder, job, args.device) / 'transcript_ja.json'}")
        elif args.command == "translate":
            print(f"Exports: {jobs.translate_job(folder, job, args.reviewed, open_browser=not args.no_browser)}")
        elif args.command == "run":
            jobs.transcribe_job(folder, job, args.device)
            # Preserve an explicitly selected reviewed transcript on later resumes.
            choice = folder / "translation_request.json"
            reviewed = jobs.read_json(choice)["reviewed"] if choice.exists() else False
            print(f"Exports: {jobs.translate_job(folder, job, reviewed, open_browser=not args.no_browser)}")
    except TranslationPaused:
        print(f"Translation saved and paused. Continue with: .\\audio.ps1 translate {args.job}")
    except KeyboardInterrupt:
        print("Stopped. Completed checkpoints are saved; repeat the command to resume.")
        return 130
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
