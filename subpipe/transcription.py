import gc
import logging
from pathlib import Path

import numpy as np
import torch

from .audio import RATE
from .common import read_json, save_json

MODELS = {"kotoba": "kotoba-tech/kotoba-whisper-v2.1", "large-v3": "openai/whisper-large-v3"}


def hardware():
    info = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available()}
    if info["cuda_available"]:
        p = torch.cuda.get_device_properties(0)
        info.update(name=p.name, vram_gib=round(p.total_memory / 2**30, 2), capability=list(torch.cuda.get_device_capability(0)))
    return info


class Recognizer:
    def __init__(self, model, device, options):
        self.name, self.options = model, options
        self.device = "cuda:0" if device == "auto" and torch.cuda.is_available() else device
        if self.device == "auto":
            self.device = "cpu"
        if self.device == "cuda":
            self.device = "cuda:0"
        self.pipe = None

    def load(self):
        from transformers import pipeline
        cuda = self.device.startswith("cuda")
        dtype = torch.float16 if cuda and torch.cuda.get_device_capability(0)[0] >= 5 else torch.float32
        args = dict(model=MODELS[self.name], device=self.device, torch_dtype=dtype,
                    batch_size=1, model_kwargs={"low_cpu_mem_usage": True, "attn_implementation": "sdpa"})
        if self.name == "kotoba":
            args.update(trust_remote_code=True, punctuator=self.options["punctuator"],
                        stable_ts=False, revision=self.options["revision"])
        else:
            args["task"] = "automatic-speech-recognition"
        logging.info("Loading %s on %s (%s)", self.name, self.device, dtype)
        self.pipe = pipeline(**args)

    def close(self):
        self.pipe = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def infer(self, data, chunk=None):
        try:
            if self.pipe is None:
                self.load()
            with torch.inference_mode():
                result = self.pipe({"array": np.asarray(data, dtype=np.float32), "sampling_rate": RATE},
                    chunk_length_s=chunk or self.options["chunk_length"],
                    stride_length_s=self.options["overlap"], return_timestamps=True,
                    generate_kwargs={"language": "ja", "task": "transcribe", "num_beams": self.options["beams"],
                                     "do_sample": False, "condition_on_prev_tokens": False})
            if self.device.startswith("cuda"):
                logging.info("GPU allocated %.2f GiB; peak %.2f GiB", torch.cuda.memory_allocated() / 2**30,
                             torch.cuda.max_memory_allocated() / 2**30)
            return result
        except (RuntimeError, AssertionError) as exc:
            if not self.device.startswith("cuda") or not any(x in str(exc).lower() for x in ("cuda", "cudnn", "memory", "driver", "not compiled")):
                raise
            logging.exception("GPU failed; retrying this block on CPU")
            self.close()
            self.device = "cpu"
        # Outside the exception scope: release failed GPU traceback tensors first.
        return self.infer(data, chunk)


def segments_from_result(result, offset, duration):
    segments = []
    chunks = result.get("chunks", [])
    if not chunks and result.get("text", "").strip():
        chunks = [{"timestamp": [None, None], "text": result["text"]}]
    previous = 0
    for item in chunks:
        text = item["text"].strip()
        if not text:
            continue
        a, b = item["timestamp"]
        flags = []
        if a is None or b is None:
            flags.append("estimated_timestamp")
        a = previous if a is None else float(a)
        b = duration if b is None else float(b)
        a, b = max(0, min(a, duration)), max(0, min(b, duration))
        if b <= a:
            flags.append("invalid_timestamp")
        segments.append({"start": offset + a, "end": offset + b, "text": text, "flags": flags})
        previous = b
    return segments


def transcribe(data, recognizer, folder, resume=False, offset=0):
    folder = Path(folder)
    length = len(data) / RATE
    block = recognizer.options["block_length"]
    margin = recognizer.options["overlap"]
    candidates = []
    for index, core_start in enumerate(np.arange(0, length, block)):
        core_end = min(length, core_start + block)
        start, end = max(0, core_start - margin), min(length, core_end + margin)
        path = folder / f"block_{index:05}.json"
        if resume and path.exists():
            record = read_json(path)
        else:
            logging.info("Transcribing %.1f–%.1f / %.1f seconds", start, end, length)
            audio = data[round(start * RATE):round(end * RATE)]
            # Only exact digital silence is skipped. Quiet signals always reach the model.
            result = {"text": "", "chunks": []} if not np.any(audio) else recognizer.infer(audio)
            record = {"offset": offset + start, "duration": end - start, "result": result,
                      "core": [offset + core_start, offset + core_end]}
            save_json(path, record)
        parts = segments_from_result(record["result"], record["offset"], record["duration"])
        for part in parts:
            mid = (part["start"] + part["end"]) / 2
            # Midpoint ownership keeps a caption whole instead of cutting words at a block edge.
            if offset + core_start <= mid < offset + core_end:
                part["block"] = index
                candidates.append(part)
    candidates.sort(key=lambda s: (s["start"], s["end"]))
    result = []
    import re
    normalized = lambda t: re.sub(r"[\W_]", "", t)
    for part in candidates:
        if result and part["block"] != result[-1]["block"] and part["start"] < result[-1]["end"]:
            if normalized(part["text"]) == normalized(result[-1]["text"]):
                result[-1].setdefault("duplicate_candidates", []).append(part)
                continue
            part["flags"].append("block_boundary_conflict")
            result[-1]["flags"].append("block_boundary_conflict")
        part["id"] = f"s{len(result):05}"
        result.append(part)
    return result
