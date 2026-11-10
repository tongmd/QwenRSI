"""A frozen local Hugging Face Qwen model proposes actual source edits."""

import hashlib
import json
import re
import time
from pathlib import Path

SYSTEM = """You improve a small C agent controller. Return ONLY a JSON object with keys
\"explanation\" and \"source\". source is complete freestanding C containing exactly the public
functions int policy(const int *s) and int select_candidate(const int *s).
No includes, macros, globals, assembly, system calls or external libraries. Use bounded integer
operations, no recursion or unbounded loops. policy reads s[0..6]: inspected, patched, verified,
last_error, patch_attempts, steps_left, steps_used. Actions: 0 inspect, 1 patch, 2 test, 3 finish,
4 abort. Success requires inspect, a successful patch, a passing test, then finish.
Patch can fail transiently. A test may detect a regression and invalidate patched state.
select_candidate reads s[0..3]: parent solved count, candidate solved count, parent total steps,
candidate total steps on identical development tasks; return 1 to nominate candidate, 0 otherwise.
You may improve both functions, including the selection procedure, but cannot modify evaluation.
The model weights remain frozen. We measure improvements to the controller, not model training.
"""


def extract_proposal(text):
    # Some models emit a <think> section even with thinking disabled.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    dec = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[match.start() :])
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("source"), str):
            if len(obj["source"]) > 16000:
                raise ValueError("Proposal exceeds source size limit")
            return obj
    raise ValueError("Model response does not contain a JSON source proposal")


class LocalQwen:
    def __init__(self, model, device="cuda:0", max_new_tokens=1536):
        import torch
        from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForImageTextToText, AutoTokenizer

        self.path, self.device, self.max_new_tokens = model, device, max_new_tokens
        torch.manual_seed(0)
        self.tokenizer = AutoTokenizer.from_pretrained(model)
        config = AutoConfig.from_pretrained(model)
        cls = (
            AutoModelForImageTextToText
            if getattr(config, "model_type", "") == "qwen3_5"
            else AutoModelForCausalLM
        )
        self.model = cls.from_pretrained(model, dtype=torch.bfloat16, device_map=device).eval()
        for p in self.model.parameters():
            p.requires_grad_(False)
        self.identity = {
            "model": model,
            "config_commit": getattr(self.model.config, "_commit_hash", None),
            "class": type(self.model).__name__,
            "device": device,
            "weights_frozen": True,
        }

    def generate(self, messages, record_path):
        import torch

        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        start = time.time()
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        response = self.tokenizer.decode(output[0, inputs.input_ids.shape[1] :], skip_special_tokens=True)
        record = {
            "identity": self.identity,
            "messages": messages,
            "response": response,
            "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "input_tokens": inputs.input_ids.shape[1],
            "output_tokens": output.shape[1] - inputs.input_ids.shape[1],
            "elapsed_seconds": time.time() - start,
        }
        Path(record_path).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return response

    def propose(self, source, development, history, record_path):
        from qwenrsi.benchmark import failure_packet, summary

        request = {
            "current_source": source,
            "development": summary(development),
            "failures": failure_packet(development),
            "previous_attempts": history[-4:],
            "request": "Propose a better controller. Improve selection when useful. Return JSON.",
        }
        response = self.generate(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(request)}],
            record_path,
        )
        return extract_proposal(response)
