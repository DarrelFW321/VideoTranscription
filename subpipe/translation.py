import json
import logging
import os
import re

import requests

from .common import digest, read_json, save_json

SYSTEM = '''Translate Japanese conversational subtitles into natural English. Preserve meaning,
tone, names, speaker references, and explicit dialogue without censoring or summarizing.
Use neighboring context, but translate ONLY each target's own content. Never add inferred
words to unclear speech. Translate a literal [inaudible] as [inaudible]. Preserve uncertainty.
Return ONLY a JSON object mapping each target id to its English string. No omitted or extra ids.
Do not translate context entries as additional targets. Keep the same names across the batch.'''


def parse_translation(text, ids):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != set(ids):
        raise ValueError("Translation changed segment IDs; refusing misaligned subtitles")
    if any(not isinstance(v, str) or not v.strip() for v in result.values()):
        raise ValueError("Translation contains empty or non-string values")
    if any(re.search(r"[\u3040-\u30ff]", v) for v in result.values()):
        raise ValueError("Translation still contains Japanese kana; review provider output")
    return result


class Provider:
    def __init__(self, config):
        self.config = config
        self.model = self.tokenizer = None

    def __call__(self, payload):
        try:
            return self.generate(payload)
        except RuntimeError as exc:
            if self.config["provider"] != "local" or not any(x in str(exc).lower() for x in ("cuda", "memory", "cudnn")):
                raise
            if self.config["device"] == "cpu":
                raise
            logging.exception("Translation GPU failed; reloading on CPU")
            self.model = None
            import gc
            import torch
            gc.collect()
            torch.cuda.empty_cache()
            self.config = dict(self.config, device="cpu")
        return self.generate(payload)

    def generate(self, payload):
        expected = {s["id"]: "English translation of this target" for s in payload["targets"]}
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "Translate the Japanese in targets into English. Context is for reference only.\n"
                     + json.dumps(payload, ensure_ascii=False)
                     + "\nReturn the following JSON structure, replacing each placeholder with its translation:\n"
                     + json.dumps(expected)}]
        if self.config["provider"] == "api":
            headers = {"Content-Type": "application/json"}
            key = os.getenv(self.config["api_key_env"])
            if key:
                headers["Authorization"] = f"Bearer {key}"
            response = requests.post(self.config["endpoint"], headers=headers, timeout=600,
                json={"model": self.config["api_model"], "messages": messages, "temperature": 0,
                      "response_format": {"type": "json_object"}})
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        if self.config["device"] == "auto":
            self.config = dict(self.config, device="cuda" if torch.cuda.is_available() else "cpu")
        if self.model is None:
            logging.info("Loading local translation model %s on %s", self.config["local_model"], self.config["device"])
            self.tokenizer = AutoTokenizer.from_pretrained(self.config["local_model"])
            device = self.config["device"]
            self.model = AutoModelForCausalLM.from_pretrained(self.config["local_model"],
                torch_dtype=torch.float16 if device.startswith("cuda") else torch.float32,
                low_cpu_mem_usage=True).to(device)
            self.model.eval()
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        if inputs.input_ids.shape[1] > 12000:
            raise ValueError("Translation context too large; reduce batch/context size")
        with torch.inference_mode():
            generated = self.model.generate(**inputs, max_new_tokens=1536, do_sample=False,
                                            temperature=None, top_p=None, top_k=None,
                                            pad_token_id=self.tokenizer.eos_token_id)
        return self.tokenizer.decode(generated[0, inputs.input_ids.shape[1]:], skip_special_tokens=True)


def translate(segments, config, folder, resume=False, provider=None):
    if config.get("provider") == "manual":
        from .manual_translation import run_manual
        return run_manual(segments, folder, config.get("manual_max_chars", 3500),
                          config.get("manual_batch_segments", 60), config.get("manual_context_segments", 2))
    if config.get("provider") == "google-web":
        from .google_web import translate_google
        return translate_google(segments, folder, resume, config.get("browser_visible", False),
                                input_format=config.get("browser_format", "json"),
                                batch_size=config["batch_segments"], context=config["context_segments"],
                                profile=config.get("browser_profile"), channel=config.get("browser_channel"),
                                stealth=config.get("browser_stealth", False))
    provider = provider or Provider(config)
    output = []
    batch, context = config["batch_segments"], config["context_segments"]
    if batch < 1 or context < 0:
        raise ValueError("Invalid translation batch/context")
    for start in range(0, len(segments), batch):
        targets = segments[start:start + batch]
        payload = {"glossary": config["glossary"],
                   "context_before": [{"id": s["id"], "ja": s["text"]} for s in segments[max(0, start-context):start]],
                   "previous_english": [{"id": s["id"], "en": s["text"]} for s in output[-context:]] if context else [],
                   "targets": [{"id": s["id"], "ja": s["text"]} for s in targets],
                   "context_after": [{"id": s["id"], "ja": s["text"]} for s in segments[start+batch:start+batch+context]]}
        fingerprint = digest({"schema": 2, "payload": payload, "config": config, "prompt": SYSTEM})
        path = folder / f"batch_{start:05}_{fingerprint[:16]}.json"
        if resume and path.exists():
            record = read_json(path)
            values = parse_translation(json.dumps(record["translations"]), [s["id"] for s in targets])
        else:
            logging.info("Translating captions %s–%s / %s", start+1, start+len(targets), len(segments))
            for attempt in range(3):
                request = dict(payload)
                if attempt:
                    request["format_reminder"] = "Previous output was invalid. Translate EVERY target, using EXACTLY these keys: " + ", ".join(s["id"] for s in targets)
                raw = provider(request)
                save_json(path.with_suffix(f".attempt{attempt}.raw.json"), {"payload": request, "response": raw})
                try:
                    values = parse_translation(raw, [s["id"] for s in targets])
                    break
                except (ValueError, TypeError):
                    if attempt == 2:
                        raise
                    logging.warning("Invalid translation structure; retrying batch")
            for s in targets:
                if s["text"] == "[inaudible]":
                    values[s["id"]] = "[inaudible]"
            save_json(path, {"fingerprint": fingerprint, "translations": values})
        for s in targets:
            output.append({**s, "japanese": s["text"], "text": values[s["id"]]})
    return output
