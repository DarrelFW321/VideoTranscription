# Japanese audio → English subtitles

> Detailed reference preserved from the original single-recording workflow. For new recordings, use the job commands in [the current README](../README.md). Earlier `sample*` folders now live under `archive/experiments/`; replace paths in historical sample commands accordingly. The model-source inspection copy is `docs/kotoba_upstream.py`. Browser automation is experimental; the current default uses normal Chrome and the copy/paste helper.

A local Windows/Python pipeline for `RJ397162.mp3`. It uses Kotoba-Whisper v2.1 for Japanese recognition and a separate contextual translator for English. It keeps the original MP3, raw recognition outputs, alternative candidates, and review flags. Accuracy still needs listening and Japanese review: a small translation model and Whisper cannot guarantee recovery of whispers, overlaps, or muffled dialogue.

## Current workflow: one copy click per translation batch

The default is now `manual`. A small helper opens **normal Chrome**, using your saved profile, with the Japanese already filled into Google Translate. Input is simply `0001 Japanese text`, `0002 Japanese text`, etc. No Playwright, Selenium, stealth scripts or automated browser controls are used in this workflow.

Click Google's **Copy translation** button on the English side. The helper detects the numbered English on the clipboard, validates all labels, saves the batch and opens the next one. It automatically creates the final English SRT/VTT after the last batch. Each batch opens a new normal tab; close finished tabs as convenient. If the prefilled link opens blank, the Japanese is also on the clipboard: paste it into Google's source box.

Try the existing **25-second sample**:

```powershell
.\.venv\Scripts\python.exe manual_translate.py --transcript sample\transcript_ja.json --output-dir sample_manual
```

For a completed full transcript:

```powershell
.\.venv\Scripts\python.exe manual_translate.py --transcript output\transcript_ja.json --output-dir output
```

Close the helper to pause. Run the same command to resume; accepted batches are not repeated. The helper watches the clipboard only while open and saves only validated numbered translations. It ignores unrelated contents. Missing, duplicate or untranslated labels keep the current batch pending, with a message explaining the problem. Timestamps come from the original transcript, never from Google.

Defaults: up to 3,500 input characters, 60 target captions and two neighboring captions on each side. Neighbor translations provide context but do not overwrite previous batches. `--max-chars`, `--batch-segments`, and `--context` adjust those limits. Large inputs are split at caption boundaries, including a limit on the prefilled URL length. `--prepare-only` exports the numbered text batches without opening a browser; `--no-browser` opens only the helper for manual pasting. All intermediate text and accepted translations are under `translation/manual_*`.

## Setup (PowerShell, Python 3.11)

```powershell
cd D:\repos\translator-video
# Install FFmpeg if ffmpeg/ffprobe are not already on PATH:
winget install --id Gyan.FFmpeg -e
# Open a fresh terminal if PATH changed.
.\setup.ps1
.\.venv\Scripts\python.exe main.py --input RJ397162.mp3 --inspect
```

If script execution is restricted, execute the following commands directly:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==24.3.1 setuptools==75.6.0 wheel==0.45.1
.\.venv\Scripts\python.exe -m pip install torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -r requirements.txt
```

The old Whisper dependency required by stable-ts needs `pkg_resources`; pinned setuptools and `--no-build-isolation` avoid its build failure with newer setuptools. PyTorch's CUDA 12.1 wheels include the runtime; a separate CUDA toolkit is unnecessary. For CPU-only installations replace `cu121` with `cpu`. Do not upgrade Transformers independently: the v2.1 custom pipeline is coupled to its internal APIs.

The prepared `.venv` on this machine reuses installed CUDA PyTorch via system site packages and overrides Transformers locally; global packages were not changed. A fresh installation via `setup.ps1` uses an isolated venv. Initial model downloads require internet and several GB of disk space. Models are cached in `.cache/huggingface`. Subsequent fully cached runs can set `$env:HF_HUB_OFFLINE='1'`.

## Run a short sample first

```powershell
.\.venv\Scripts\python.exe main.py --input RJ397162.mp3 --output-dir sample --test-seconds 25 --preprocess both --translation-provider manual --resume
```

Use `--start 600 --test-seconds 60 --output-dir sample_600` to test a difficult minute. Sample subtitle timestamps remain relative to the **full original audio**, including `--start`. Play them against that original; extracted WAVs start at zero.

## Process the full recording

```powershell
.\.venv\Scripts\python.exe main.py --input RJ397162.mp3 --model kotoba --output-dir output --device auto --preprocess both --second-pass --translation-provider manual --resume
```

This transcribes both versions, keeps the original version as primary, generates alternative candidates for flagged intervals, then opens the copy/paste helper. After you copy each English batch, it writes English subtitles. Alternatives are **not** silently accepted. Pause the helper to review Japanese first if necessary. The first run may take a long time, especially with CPU fallback. No full-recording speed estimate is promised.

Outputs:

- `RJ397162_ja.srt`, `RJ397162_ja.vtt`, `RJ397162_en.srt`, `RJ397162_en.vtt`
- `asr/{original,processed}/block_*.json`: raw responses and offsets, saved after each 120-second block
- `transcript_original.json`, `transcript_processed.json`: separate recognition candidates
- `transcript_ja.json`, `transcript_en.json`: selected segments, timestamps, IDs, review flags
- `review.json`: suspected missing dialogue, quiet intervals, repetitions, timing concerns
- `refinement_candidates.json`: alternate readings, never auto-merged
- `translation/`: contextual translation requests, responses, and validated batch checkpoints
- `validation.json`: format/timing checks and readability warnings
- `environment.json`, `manifest.json`, `run.log`, and temporary mono WAVs under `audio/`

`--resume` reuses completed recognition blocks. An input SHA-256 and ASR/preprocessing settings prevent reuse from a different recording or configuration. Use a new output directory when changing those settings. Translation checkpoints additionally fingerprint the Japanese targets, neighboring context, previous English, provider settings, and prompt; editing the transcript invalidates affected translations. A failed translation leaves Japanese subtitles and recognition checkpoints intact.

## Review before treating subtitles as final

1. Listen around `review.json` intervals and compare the two transcript files and refinement candidates. Energy-based gap checks also flag background sounds; they are not a voice activity classifier.
2. Copy `transcript_ja.json` to `reviewed_ja.json`. Correct text/timing, preserve unique IDs, and add recovered missing segments with new IDs. Use `[inaudible]` only after listening establishes that words cannot be recovered. Uncertain recognition is never automatically replaced with that label.
3. Regenerate translation and exports without rerunning ASR:

```powershell
.\.venv\Scripts\python.exe main.py --input RJ397162.mp3 --output-dir output --preprocess both --resume --reviewed-transcript reviewed_ja.json --translation-provider manual
```

Keep the same input, sample range, and ASR/preprocessing settings as the original run. The review JSON is a list of `{id,start,end,text,flags}` objects; times are absolute seconds. Correct invalid zero-duration intervals before export. Translation never guesses timestamps.

## Accuracy and memory controls

- `--device auto|cuda|cpu`: detects GPU/VRAM, uses FP16 on the RTX 3050, batch size 1 and SDPA. GPU runtime/memory errors retry the current block on CPU. CPU ASR uses FP32. The log records GPU allocation/peak usage.
- `--chunk-length 24 --overlap 4`: Transformers' Whisper token decoding reconciles internal overlapping chunks. 120-second checkpoint blocks have context on both sides; midpoint ownership selects boundary captions. Only exact overlapping duplicates across blocks are removed and their candidates retained. Conflicting boundary text is marked for listening.
- Deterministic beam search (`beams: 3`) and disabled previous-token conditioning limit repetition propagation. Exact digital silence alone is skipped; low-energy signals are not gated. No unsupported probability/confidence thresholds are used, and no model confidence score is fabricated.
- `--preprocess none|gentle|both`: always mono 16 kHz. Gentle mode uses 2:1 compression, a 20 ms attack, a 250 ms release, and peak normalization to −1 dBFS. Noise reduction (5 dB) and 70–7500 Hz filtering are off by default. Enable separately in `config.yaml` after listening. These changes can hurt recognition, hence comparison mode.
- Kotoba's punctuator is enabled. `stable_ts` silence adjustment is disabled to avoid snapping whisper timestamps to energy thresholds. Whisper timestamps are estimates, not forced alignment. Overlapping speakers cannot reliably be separated by this pipeline.
- `--second-pass`: rereads flagged segments and uncovered activity using the other audio variant, three seconds of context, and shifted chunk sizes. Both readings survive. `--second-model large-v3 --second-device cpu` requests Whisper Large V3 on CPU; it is too large for normal FP16 inference within 4 GB. It needs substantial system RAM and can be very slow. There is no tested disk-offloading path.
- `--preprocess both` keeps original audio primary; use `gentle` in a **new output directory** if listening establishes that processed recognition is better.

## Translation providers

The optional `google-web` provider uses Playwright-controlled Google Chrome with a dedicated persistent profile, small JSON batches (six targets plus up to three neighboring captions), and strict caption-ID validation. Requests stay below 4,500 characters. Only transcript text is submitted. This does not require an API key. Translation quality still needs review; automated tests did not reproduce the user's better normal-browser translation. Prefer the default `manual` helper described above.

To retain your Google account/session, run:

```powershell
.\.venv\Scripts\python.exe google_profile.py
```

Sign in yourself in the normal Chrome window, then close all windows of this dedicated profile. The pipeline can then reuse it. Cookies remain inside `.browser-profile/`, excluded from Git; regular browser profiles are not copied. Do not share this folder. Google's challenges are not bypassed. Only one process can use this profile at a time.

Retest the sample with that profile (omit `--resume` to obtain a fresh translation after changing login/settings):

```powershell
.\.venv\Scripts\python.exe google_document.py --transcript sample\transcript_ja.json --output-dir sample_google_signedin --headed --profile .browser-profile --channel chrome
```

For the full pipeline use `--translation-provider google-web` instead of `local` in the commands above. `config.yaml` controls `browser_visible`, `browser_profile`, `browser_channel`, `browser_format`, `batch_segments`, and `context_segments`. Run from the project directory so the relative profile path stays consistent. A signed-in profile may give different results, but that has not yet been verified.

Google document upload is also available through `google_document.py --method document`. The live test returned unchanged Japanese DOCX files, so the tested default uses text batches. `--export-only` creates a DOCX for manual upload, and `--import-docx PATH` imports its translation with ID validation.

An experimental `--stealth` option is available on `google_document.py`, or set `translation.browser_stealth: true` for the main pipeline. It uses playwright-stealth 2.0.2 initialization scripts and removes Chrome's automation banner flag while preserving real language, platform, user-agent and GPU properties. The sample test with saved cookies and visible Chrome still produced the incorrect ping-pong translation. Stealth is therefore **off by default** and is not a demonstrated quality fix. It does not solve CAPTCHAs. Run the comparison without `--resume` so earlier results are not reused:

```powershell
.\.venv\Scripts\python.exe google_document.py --transcript sample\transcript_ja.json --output-dir sample_google_stealth --headed --profile .browser-profile --channel chrome --stealth
```

`local` uses `Qwen/Qwen2.5-1.5B-Instruct` with Transformers. Recognition is unloaded first; translation uses GPU if available and falls back to CPU on GPU memory/runtime errors. This compact model makes the pipeline runnable on limited hardware, but is a **draft translator**, particularly for omitted Japanese subjects, names, and subtle tone. For accuracy, review Japanese first and use a stronger configured model/provider if available. Change `translation.local_model` and `translation.device` in YAML; CPU FP32 needs roughly 6 GB just for this model's weights plus runtime memory.

Each batch includes neighboring Japanese captions and previous English. The response must contain exactly the requested segment IDs with nonempty strings. Malformed output or leftover Japanese kana stops the stage; raw responses remain saved. Passing structural checks does not prove faithful translation. Glossary entries under `translation.glossary` help maintain names and references.

`api` supports a configurable chat-completions endpoint, including a local server. Set `translation.endpoint`, `api_model`, and optionally the environment variable named by `api_key_env`. The server must accept JSON-object response format. Only transcript text/context is sent; audio stays local. No hosted provider or credential is assumed. `--translation-provider none` runs Japanese recognition/review/export alone.

## Subtitle behavior and validation

SRT/VTT are round-tripped through independent parsers, checked for matching cue counts/timestamps, nonnegative ordered durations and full-audio bounds. English wraps near 42 characters at word boundaries. Long captions are flagged instead of inventing word-level timing to split them. Overlapping source captions are grouped into one cue with ` / ` separators and a warning; raw JSON retains each original timing and text. Resolve boundary conflicts manually rather than treating grouping as recognition agreement. Large text blocks may exceed two lines until reviewed. Important pauses between source segments are preserved.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover overlap ownership, resume, translation context and cache invalidation, strict translation IDs, missing timestamps, Unicode, hour boundaries, overlap export, and invalid timing. See `TEST_REPORT.md` for the actual audio smoke-test results and remaining limits.

## Model/API references

- [Kotoba v2.1 official model card](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.1): custom pipeline, `trust_remote_code=True`, punctuator and Japanese transcription arguments.
- [Pinned custom pipeline source](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.1/blob/57a9d8ab771a0124706b67d22509bedd07c36187/kotoba_whisper.py): inspected for timestamp outputs, stride behavior and supported options. `kotoba_upstream.py` is the inspection copy, not imported by the application.
- [Transformers 4.46.3 Whisper docs](https://huggingface.co/docs/transformers/v4.46.3/en/model_doc/whisper)
- [Qwen model and chat-template usage](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)

The Kotoba custom code is pinned to a commit in `config.yaml`. Punctuation model assets and the configurable translation model use their upstream defaults; record cached revisions if strict reproducibility across machines is needed.
