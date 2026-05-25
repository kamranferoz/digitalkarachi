"""Local Stable Diffusion image generator (Apple Silicon MPS).

Loaded lazily by generate_ai_images.py when --local is passed.

Default model: stabilityai/sdxl-turbo
  - Single-step inference (~3-8s on M1/M2/M3)
  - ~6.9GB safetensors download (one-time, cached under ~/.cache/huggingface)
  - Native 512x512; we generate 1024x576 with guidance_scale=0.0 and 1 step.

If you want higher quality at the cost of time, set:
  LOCAL_SD_MODEL=stabilityai/stable-diffusion-xl-base-1.0
  LOCAL_SD_STEPS=20
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

_PIPE = None
_DEVICE = None
_MODEL_ID = os.environ.get("LOCAL_SD_MODEL", "stabilityai/sdxl-turbo")
_STEPS = int(os.environ.get("LOCAL_SD_STEPS", "1"))
_GUIDANCE = float(os.environ.get("LOCAL_SD_GUIDANCE", "0.0"))
_RELOAD_EVERY = int(os.environ.get("LOCAL_SD_RELOAD_EVERY", "40"))
_CALL_COUNT = 0


def reset_pipeline(reason: str = "") -> None:
    """Drop cached pipeline so next call creates a clean instance."""
    global _PIPE
    if _PIPE is None:
        return
    if reason:
        print(f"[local-sd] resetting pipeline ({reason})", flush=True)
    _PIPE = None
    try:
        import gc
        gc.collect()
    except Exception:
        pass
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _pick_device() -> str:
    import torch  # local import — heavy
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _load_pipe():
    global _PIPE, _DEVICE
    if _PIPE is not None:
        return _PIPE
    import torch
    from diffusers import AutoPipelineForText2Image

    _DEVICE = _pick_device()
    dtype = torch.float16 if _DEVICE in ("mps", "cuda") else torch.float32
    print(f"[local-sd] loading {_MODEL_ID} on {_DEVICE} ({dtype})... (first run downloads ~7GB)",
          flush=True)
    t0 = time.time()
    pipe = AutoPipelineForText2Image.from_pretrained(
        _MODEL_ID,
        torch_dtype=dtype,
        variant="fp16" if dtype == torch.float16 else None,
        use_safetensors=True,
    )
    pipe = pipe.to(_DEVICE)
    # Memory saving — keeps M1 8GB safe-ish.
    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass
    print(f"[local-sd] pipeline ready in {time.time() - t0:.1f}s", flush=True)
    _PIPE = pipe
    return pipe


def generate(
    prompt: str,
    seed: int,
    width: int = 1024,
    height: int = 576,
    negative_prompt: Optional[str] = None,
) -> "object":
    """Return a PIL.Image. Raises on failure (caller handles fallback)."""
    global _CALL_COUNT
    import torch

    if _RELOAD_EVERY > 0 and _CALL_COUNT > 0 and _CALL_COUNT % _RELOAD_EVERY == 0:
        reset_pipeline("periodic refresh")

    pipe = _load_pipe()
    generator = torch.Generator(device="cpu").manual_seed(int(seed))
    kwargs = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_inference_steps": _STEPS,
        "guidance_scale": _GUIDANCE,
        "generator": generator,
    }
    # SDXL-Turbo doesn't use negative_prompt (guidance=0); base SDXL does.
    if negative_prompt and _GUIDANCE > 0:
        kwargs["negative_prompt"] = negative_prompt
    out = pipe(**kwargs)
    _CALL_COUNT += 1
    return out.images[0]


if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else (
        "futuristic quantum computer in a research lab, glowing qubits, "
        "cinematic photo, photoreal, sharp focus"
    )
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    out_path = sys.argv[3] if len(sys.argv) > 3 else "/tmp/local-sd-test.png"
    t0 = time.time()
    img = generate(prompt, seed)
    img.save(out_path)
    print(f"OK {img.size} {time.time() - t0:.1f}s → {out_path}")
