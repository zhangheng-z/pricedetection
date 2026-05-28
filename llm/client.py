import json
from typing import Optional, List, Dict, Any
from config.loader import LLMConfig


class LLMClient:
    """统一 LLM 客户端，支持 OpenAI 兼容接口和 Anthropic SDK"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None

    def _get_openai_client(self):
        from openai import OpenAI
        return OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.api_base,
        )

    def _get_anthropic_client(self):
        import anthropic
        return anthropic.Anthropic(api_key=self.config.api_key)

    def _ensure_client(self):
        if self._client is None:
            if self.config.provider == "anthropic":
                self._client = self._get_anthropic_client()
            else:
                self._client = self._get_openai_client()
        return self._client

    def chat(self, messages: List[Dict[str, str]], system: Optional[str] = None) -> str:
        client = self._ensure_client()
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
        }

        if self.config.provider == "anthropic":
            kwargs["max_tokens"] = 4096
            if system:
                kwargs["system"] = system
            kwargs["messages"] = messages
            response = client.messages.create(**kwargs)
            return response.content[0].text
        else:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend(messages)
            kwargs["messages"] = msgs
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

    def chat_json(self, messages: List[Dict[str, str]], system: Optional[str] = None) -> dict:
        """调用 LLM 并解析返回 JSON，解析失败时抛出带有原文的异常"""
        text = self.chat(messages, system=system)
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError) as e:
            raise ValueError(
                f"Failed to parse LLM response as JSON (model={self.config.model}): {e}\nRaw text: {text[:500]}"
            ) from e
