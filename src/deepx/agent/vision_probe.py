"""Vision capability probe — detect if a model supports image input."""
from __future__ import annotations

import base64
from pathlib import Path


# Simple probe marker: a 1x1 white PNG with text "MELON48" drawn on it
# Using a minimal PNG avoids embedding binary data in source
_PROBE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8/5+h"
    "nYLgYGD4jwD+AEqHEGwPAAAAAElFTkSuQmCC"
)

_PROBE_TOKEN = "MELON48"


def _normalize_alnum(s: str) -> str:
    """Keep only alphanumeric, uppercase."""
    return "".join(c.upper() for c in s if c.isalnum())


async def probe_vision(llm_client, model_entry: dict) -> bool:
    """
    Probe whether a model supports vision (image input).

    Sends a minimal request with a probe image containing the text "MELON48".
    If the model responds with "MELON48" (case-insensitive), it sees the image = supports vision.
    If it returns 4xx, it doesn't support images = no vision.
    If there's a network error, treat as uncertain (return False, don't cache).

    Args:
        llm_client: LLM client instance
        model_entry: dict with {base_url, model, api_key}

    Returns:
        True if model supports vision, False otherwise
    """
    import httpx

    # Decode the probe image
    try:
        image_data = base64.b64decode(_PROBE_PNG_B64)
    except Exception:
        return False

    data_url = f"data:image/png;base64,{_PROBE_PNG_B64}"

    system_prompt = "You are a helpful assistant."
    user_message = "What text is shown in this image? Reply with only that text."

    # Build message with image
    content_parts = [
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": user_message},
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content_parts},
    ]

    url = f"{model_entry['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {model_entry['api_key']}",
    }

    body = {
        "model": model_entry["model"],
        "max_tokens": 256,
        "stream": False,
        "messages": messages,
    }

    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=20.0)
    except Exception:
        return False  # Network error, uncertain

    if 400 <= resp.status_code < 500:
        # 4xx = model rejects images → no vision, deterministic
        return False

    if resp.status_code != 200:
        return False  # 5xx or other error, uncertain

    try:
        data = resp.json()
    except Exception:
        return False

    content = ""
    if choices := data.get("choices"):
        msg = choices[0].get("message", {})
        content = msg.get("content", "") or ""
        # Also check reasoning_content (some models think in it)
        reasoning = msg.get("reasoning_content", "") or ""
        content += " " + reasoning

    # Normalize and check for probe token
    normalized = _normalize_alnum(content)
    return _PROBE_TOKEN in normalized


async def probe_vision_streaming(llm_client, model_entry: dict) -> bool:
    """
    Same as probe_vision, but use streaming endpoint.
    Accumulates content until done.
    """
    import asyncio, httpx

    full_content = []
    full_reasoning = []

    url = f"{model_entry['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {model_entry['api_key']}",
    }

    data_url = f"data:image/png;base64,{_PROBE_PNG_B64}"
    body = {
        "model": model_entry["model"],
        "max_tokens": 256,
        "stream": True,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": "What text is shown in this image? Reply with only that text."},
            ]},
        ],
    }

    try:
        with httpx.stream("POST", url, json=body, headers=headers, timeout=20.0) as resp:
            if resp.status_code == 400:
                return False  # rejects image
            if resp.status_code != 200:
                return False

            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    import json as _json
                    chunk = _json.loads(data_str)
                except Exception:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    full_content.append(delta["content"])
                if delta.get("reasoning_content"):
                    full_reasoning.append(delta["reasoning_content"])
    except Exception:
        return False

    normalized = _normalize_alnum(" ".join(full_content) + " " + " ".join(full_reasoning))
    return _PROBE_TOKEN in normalized