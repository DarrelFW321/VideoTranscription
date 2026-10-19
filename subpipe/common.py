import hashlib
import json
import os
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def transcript_stem(path):
    """Infer legacy export names from media metadata, not a fixed recording ID."""
    path = Path(path)
    environment = path.parent / "environment.json"
    if environment.is_file():
        name = read_json(environment).get("audio", {}).get("format", {}).get("filename")
        if name:
            return Path(name).stem
    return path.parent.name if path.stem.startswith("transcript_") else path.stem
