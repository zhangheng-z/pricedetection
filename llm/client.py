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
    _usage_db_path = "data/price_monitor.db"
    VECTORENGINE_API_BASE = "https://api.vectorengine.ai/v1"
    VECTORENGINE_PRIMARY_MODEL = "deepseek-v4-flash"
    VECTORENGINE_FALLBACK_MODEL = "gpt-5.4-mini"
    VECTORENGINE_FAILURE_THRESHOLD = 3

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client = None
        self._vectorengine_primary_failures = 0
        self._vectorengine_use_fallback = False

    def _get_openai_client(self):
        from openai import OpenAI
        return OpenAI(
            api_key=self.config.api_key,
            base_url=self._openai_base_url(),
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
            "model": self.current_model(),
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
            response = self.create_openai_chat_completion(**kwargs)
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
                f"Failed to parse LLM response as JSON (model={self.current_model()}): {e}\nRaw text: {text[:500]}"
            ) from e

    def current_model(self) -> str:
        if self._is_vectorengine_enabled():
            if self._vectorengine_use_fallback:
                return self.VECTORENGINE_FALLBACK_MODEL
            return self.VECTORENGINE_PRIMARY_MODEL
        return self.config.model

    def create_openai_chat_completion(self, **kwargs: Any) -> Any:
        client = self._ensure_client()
        kwargs["model"] = kwargs.get("model") or self.current_model()
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception:
            if not self._should_retry_with_vectorengine_fallback(kwargs["model"]):
                raise
            kwargs["model"] = self.VECTORENGINE_FALLBACK_MODEL
            response = client.chat.completions.create(**kwargs)
            self._vectorengine_use_fallback = True
        if kwargs["model"] == self.VECTORENGINE_PRIMARY_MODEL:
            self._vectorengine_primary_failures = 0
        return response

    def _openai_base_url(self) -> str:
        if self._is_vectorengine_enabled():
            return self.VECTORENGINE_API_BASE
        return self.config.api_base

    def _is_vectorengine_enabled(self) -> bool:
        if self.config.provider == "anthropic":
            return False
        api_base = str(self.config.api_base or "").rstrip("/")
        return (
            "api.vectorengine.ai" in api_base
            or self.config.model in {
                self.VECTORENGINE_PRIMARY_MODEL,
                self.VECTORENGINE_FALLBACK_MODEL,
            }
        )

    def _should_retry_with_vectorengine_fallback(self, model: str) -> bool:
        if not self._is_vectorengine_enabled() or model != self.VECTORENGINE_PRIMARY_MODEL:
            return False
        self._vectorengine_primary_failures += 1
        if self._vectorengine_primary_failures < self.VECTORENGINE_FAILURE_THRESHOLD:
            return False
        self._vectorengine_use_fallback = True
        return True

    @classmethod
    def reset_usage(cls) -> None:
        cls._usage_stats = TokenUsageStats()

    @classmethod
    def configure_usage_storage(cls, db_path: str) -> None:
        if db_path:
            cls._usage_db_path = db_path

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
        cls._save_usage_to_database(prompt_tokens, completion_tokens, total_tokens)

    @classmethod
    def _save_usage_to_database(
        cls,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        try:
            from storage.database import Database

            Database(cls._usage_db_path).save_llm_token_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        except Exception as exc:
            print(f"Failed to save LLM token usage: {exc}", flush=True)

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
