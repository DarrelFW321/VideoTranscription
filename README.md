# Audio subtitle workbench

Transcribe Japanese audio with Kotoba-Whisper v2.1, review difficult passages, translate through normal Google Translate using the copy/paste helper, and export English/Japanese SRT and VTT files. Each recording has its own settings and checkpoints.

## Add your next recording

From PowerShell in this folder:

```powershell
.\audio.ps1 add "D:\Downloads\new-audio.mp3" --name new-audio
.\audio.ps1 sample new-audio --seconds 30 --translate
.\audio.ps1 run new-audio
```

`add` copies the recording into its job; the source stays untouched. `--name` is optional if the filename makes a suitable unique job name. MP3, WAV, FLAC, M4A, AAC, OGG, Opus and other listed media formats are accepted.

`sample` runs a separate short test without affecting the full run. `run` transcribes the full audio, runs refinement, then opens the helper. Repeat either command to resume after stopping. Models and the Chrome profile are shared; recordings and translation progress are not.

The helper opens **normal Chrome with the Japanese already filled in** as `0001`, `0002`, etc. Click Google's **Copy translation** button on the English side. The helper checks the numbers, saves the batch, and opens the next one. If Google opens blank, paste the prepared clipboard text into the source box. Line wrapping does not affect caption matching. Close the helper to pause.

## Everyday commands

### Supply your own thumbnail

Keep your image anywhere on your computer, then attach it to an existing job:

```powershell
.\.venv\Scripts\python.exe audio.py thumbnail my-video "D:\Downloads\cover.png"
.\.venv\Scripts\python.exe audio.py watch my-video
```

The first command converts JPG, PNG, WebP, BMP or GIF to
`jobs/my-video/thumbnail.jpg`, replacing any previous thumbnail. Your source image
stays untouched. Nothing is uploaded online. You can also copy an existing JPEG
directly to that location. Run `watch` again to include the image in the player;
it requires a completed Japanese transcript. Attaching a thumbnail does not
require transcription and can be done immediately after importing audio.

| Command | Purpose |
| --- | --- |
| `.\audio.ps1 list` | List recordings and caption counts |
| `.\audio.ps1 status new-audio` | Show progress and file locations |
| `.\audio.ps1 transcribe new-audio` | Run/resume Japanese recognition only |
| `.\audio.ps1 review new-audio` | Create a Japanese transcript copy to edit |
| `.\audio.ps1 translate new-audio --reviewed` | Translate the reviewed copy |
| `.\audio.ps1 translate new-audio` | Continue translation without recognition |
| `.\audio.ps1 export new-audio` | Rebuild and validate subtitle exports |

Final files are in **`jobs/<name>/exports/`**. Inspect review flags and listen to ambiguous sections. Alternative recognition candidates are preserved rather than automatically merged. Valid subtitle formatting does not establish correct dialogue.

## Layout

```text
audio.py / audio.ps1        Job commands
config.yaml                Defaults copied into new jobs
subpipe/                   Pipeline modules and job management
tests/                     Tests and explicit GUI/browser smoke tests
jobs/<name>/
  job.json                 Input identity and run options
  config.yaml              Settings for this recording
  input/                   Copy of the recording
  work/                    Transcripts, checkpoints, candidates, translation batches
  samples/                 Short tests, separate from the full recording
  reviewed_ja.json         Created by review; used when explicitly selected
  exports/                 Japanese/English SRT and VTT plus validation
inbox/                     Optional place to drop recordings
.cache/                    Shared model downloads
.browser-profile/          Shared normal Chrome profile
docs/                      Pipeline reference
archive/experiments/       Preserved earlier sample runs
```

Job contents, recordings, model caches and browser sessions are excluded from Git. Do not share the browser profile. `config.yaml` is a template: editing it affects **new jobs**; existing recordings use `jobs/<name>/config.yaml`.

## Existing recording

`RJ397162` is registered with 532 Japanese and 532 English captions. Its original `RJ397162.mp3` and `output/` were left in place so earlier commands and checkpoints remain usable. Its job metadata points to those locations. Final subtitle copies are in `jobs/RJ397162/exports/`.

```powershell
.\audio.ps1 status RJ397162
.\audio.ps1 export RJ397162
```

Register another existing full run without copying/moving checkpoints:

```powershell
.\audio.ps1 adopt "D:\audio\recording.mp3" --output "D:\audio\old-output" --name recording
```

The input hash and original ASR/preprocessing settings are checked before adoption. A mismatching recording is rejected.

## First-time setup

Requires Windows, Python 3.11, Google Chrome, FFmpeg and FFprobe on PATH. On this prepared machine, use the existing `.venv`.

```powershell
winget install --id Gyan.FFmpeg -e
.\setup.ps1
```

If PowerShell prevents scripts, use Python directly:

```powershell
.\.venv\Scripts\python.exe audio.py add "D:\Downloads\new-audio.mp3" --name new-audio
.\.venv\Scripts\python.exe audio.py run new-audio
```

See [pipeline setup and model details](docs/pipeline-reference.md) for manual installation. Initial model downloads need internet; transcription runs locally. The default is FP16 on supported CUDA hardware, batch size 1, with CPU fallback for GPU failures. Google receives transcript text through the normal browser.

Optional: open the dedicated normal Chrome profile and sign in yourself:

```powershell
.\.venv\Scripts\python.exe google_profile.py
```

## Settings and review

New jobs default to original/processed comparison and second-pass refinement. Use `add --preprocess none --no-refine` for a lighter run. Device selection is per command: `run NAME --device cpu` or `--device cuda`. Samples support `--start 600 --seconds 60`.

Edit the job's `config.yaml` for chunk/overlap, filters and manual batch sizes. The helper defaults to 3,500 characters, 60 target captions and two context captions on each side. Changing ASR/preprocessing settings after recognition starts invalidates its resume fingerprint; register another job name for comparisons. Changing Japanese text invalidates its previous manual translation rather than silently assigning old English to new dialogue.

`review` never overwrites existing edits. Use `translate --reviewed` to select that copy; selection survives a pause. Export refuses English whose IDs, source Japanese or timestamps no longer match. Candidate conflicts and long captions may still need correction.

Run one writer per job. The shared GPU is best used for one recognition run at a time. Older `main.py`, `manual_translate.py`, and `google_document.py` commands still work; use job commands for new recordings to avoid mixing outputs.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Job tests cover copied inputs, collision/path protection, isolated samples, resumed review selection and stale-translation rejection.
