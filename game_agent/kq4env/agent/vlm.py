"""Thin OpenAI-compatible VLM client for any /v1/chat/completions endpoint."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from openai import OpenAI
from PIL import Image

from kq4env.config import RESOLUTION


@dataclass
class VLMConfig:
    """Configuration for the VLM endpoint."""

    model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    temperature: float = 0.3
    timeout: float = 120.0
    max_tokens: int = 512
    use_structured: bool = True


class VLMClient:
    """Send single-turn chat completions with optional image input.

    Works with vLLM, ollama (/v1/ compat), Together, OpenRouter, or any
    OpenAI-compatible endpoint.
    """

    def __init__(self, config: VLMConfig | None = None) -> None:
        self.config = config or VLMConfig()
        self._client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

    def chat(
        self,
        system_prompt: str,
        user_text: str,
        image: Image.Image | None = None,
        guided_json: dict | None = None,
    ) -> str:
        """Send a single-turn message and return the assistant's text.

        Args:
            system_prompt: System message content.
            user_text: User message text.
            image: Optional PIL image (resized to game resolution before encoding).
            guided_json: Optional JSON schema for vLLM structured generation.

        Returns:
            The assistant's response text.
        """
        user_content: list[dict] = []

        if image is not None:
            resized = image.resize(RESOLUTION, Image.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )

        user_content.append({"type": "text", "text": user_text})

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        kwargs: dict = {}
        if guided_json is not None:
            kwargs["extra_body"] = {"guided_json": guided_json}

        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            **kwargs,
        )
        return response.choices[0].message.content or ""
