from typing import Optional
from llm.client import LLMClient
from llm.prompts import PRICE_JUDGE_TEMPLATE, SEARCH_KEYWORDS_TEMPLATE


class PriceJudge:
    """价格违规判定 + 搜索词生成"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    def is_below_official(self, price: float, official_price: float) -> bool:
        return price < official_price

    def is_suspiciously_low(self, price: float, official_price: float) -> bool:
        return price < official_price * 0.5

    async def llm_confirm_violation(
        self, title: str, price: float, product_name: str, official_price: float
    ) -> dict:
        if not self.llm:
            if self.is_suspiciously_low(price, official_price):
                return {"judgment": "suspicious", "reason": "价格低于官方价50%以上，疑似引流"}
            return {"judgment": "violation", "reason": f"价格{price}低于官方价{official_price}"}

        system = "你是一个电商价格合规分析师，严格按规则判断。"
        user = PRICE_JUDGE_TEMPLATE.format(
            product_name=product_name,
            official_price=official_price,
            title=title,
            price=price,
            description="",
        )
        try:
            result = self.llm.chat_json(
                messages=[{"role": "user", "content": user}],
                system=system,
            )
            return result
        except Exception as e:
            print(f"LLM judgment error: {e}, using fallback rules")
            if self.is_suspiciously_low(price, official_price):
                return {"judgment": "suspicious", "reason": "LLM不可用，规则判定为疑似引流"}
            return {"judgment": "violation", "reason": f"LLM不可用，规则判定价格违规"}

    def judge(self, price: float, official_price: float) -> str:
        """纯规则快速判断（不带 LLM）"""
        if not self.is_below_official(price, official_price):
            return "normal"
        if self.is_suspiciously_low(price, official_price):
            return "suspicious"
        return "violation"

    async def generate_keywords(self, product_name: str, official_price: float, count: int = 5) -> list:
        if not self.llm:
            return []

        system = "你是一个电商运营专家。只返回关键词列表，逗号分隔，不要多余内容。"
        user = SEARCH_KEYWORDS_TEMPLATE.format(
            product_name=product_name,
            official_price=official_price,
            count=count,
        )
        try:
            text = self.llm.chat(
                messages=[{"role": "user", "content": user}],
                system=system,
            )
            parts = [k.strip() for k in text.replace("，", ",").split(",")]
            return [p for p in parts if p]
        except Exception:
            return []
