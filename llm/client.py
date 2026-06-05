import json
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from config.loader import LLMConfig


@dataclass
class TokenUsageStats:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def snapshot(self) -> dict:
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class LLMClient:
    """统一 LLM 客户端，支持 OpenAI 兼容接口和 Anthropic SDK"""
    _usage_stats = TokenUsageStats()

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
            self.record_usage(response)
            return response.content[0].text
        else:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend(messages)
            kwargs["messages"] = msgs
            response = client.chat.completions.create(**kwargs)
            self.record_usage(response)
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

    @classmethod
    def reset_usage(cls) -> None:
        cls._usage_stats = TokenUsageStats()

    @classmethod
    def usage_snapshot(cls) -> dict:
        return cls._usage_stats.snapshot()

    @classmethod
    def usage_summary(cls) -> str:
        stats = cls.usage_snapshot()
        return (
            f"LLM token usage: requests={stats['requests']}, "
            f"prompt={stats['prompt_tokens']}, completion={stats['completion_tokens']}, "
            f"total={stats['total_tokens']}"
        )

    @classmethod
    def record_usage(cls, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        prompt_tokens = cls._usage_value(usage, "prompt_tokens", "input_tokens")
        completion_tokens = cls._usage_value(usage, "completion_tokens", "output_tokens")
        total_tokens = cls._usage_value(usage, "total_tokens")
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        if prompt_tokens == 0 and completion_tokens == 0 and total_tokens == 0:
            return

        cls._usage_stats.requests += 1
        cls._usage_stats.prompt_tokens += prompt_tokens
        cls._usage_stats.completion_tokens += completion_tokens
        cls._usage_stats.total_tokens += total_tokens

    @staticmethod
    def _usage_value(usage: Any, *names: str) -> int:
        for name in names:
            if isinstance(usage, dict):
                value = usage.get(name)
            else:
                value = getattr(usage, name, None)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
        return 0
