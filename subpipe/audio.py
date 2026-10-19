import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 16000


def metadata(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ], text=True, encoding="utf-8"))


def prepare(source, folder, options, start=0, duration=None, processed=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / "original_16k.wav"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
               "-ss", str(start)]
    if duration is not None:
        command += ["-t", str(duration)]
    subprocess.run(command + ["-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_f32le", str(original)], check=True)
    paths = {"original": original}
    if processed:
        filters = []
        if options["speech_filter"]:
            filters += ["highpass=f=70", "lowpass=f=7500"]
        if options["noise_reduction"]:
            filters += ["afftdn=nr=5:nf=-50:tn=1"]
        if options["compression"]:
            filters += ["acompressor=threshold=0.03:ratio=2:attack=20:release=250:makeup=2:knee=4"]
        target = folder / "processed_16k.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(original),
                        "-af", ",".join(filters) or "anull", "-c:a", "pcm_f32le", str(target)], check=True)
        data, rate = sf.read(target, dtype="float32")
        peak = float(np.max(np.abs(data))) if len(data) else 0
        if peak > 0:
            data *= (10 ** (options["peak_db"] / 20)) / peak
        sf.write(target, data, rate, subtype="FLOAT")
        paths["processed"] = target
    return paths


def dbfs(data):
    return float(20 * np.log10(max(float(np.sqrt(np.mean(np.square(data, dtype=np.float64)))) if len(data) else 0, 1e-10)))


def activity(data, threshold=-55):
    # Energy only: background sounds also trigger this; never call it speech detection.
    return [{"start": i / RATE, "end": min(i + RATE // 2, len(data)) / RATE,
             "dbfs": dbfs(data[i:i + RATE // 2])}
            for i in range(0, len(data), RATE // 2)
            if dbfs(data[i:i + RATE // 2]) > threshold]
