from typing import Optional, Dict, List
from llm.client import LLMClient
from llm.prompts import PRICE_JUDGE_TEMPLATE, SEARCH_KEYWORDS_TEMPLATE


SKU_RULES = {
    "CN_15D": {"version": "CN", "period": "15D", "official_price": 9.9},
    "CN_21D": {"version": "CN", "period": "21D", "official_price": 99.0},
    "CN_YEAR": {"version": "CN", "period": "YEAR", "official_price": 2498.0},
    "EN_21D": {"version": "EN", "period": "21D", "official_price": 39.9},
    "EN_YEAR": {"version": "EN", "period": "YEAR", "official_price": 2198.0},
}

PRICE_TOLERANCE = 0.5

TARGET_KEYWORDS = (
    "\u9002\u8da3",
    "\u9002\u8da3ai",
    "\u9002\u8da3\u8bc6\u5b57",
    "\u9002\u8da3\u4e2d\u6587",
    "\u9002\u8da3\u82f1\u6587",
    "\u9002\u8da3ai\u9605\u8bfb",
    "\u4e2d\u6587\u9605\u8bfb\u5361",
    "\u82f1\u6587\u9605\u8bfb\u5361",
    "ai\u8bc6\u5b57",
)

CN_KEYWORDS = ("\u4e2d\u6587", "\u4e2d\u6587\u9605\u8bfb")
CN_FALLBACK_KEYWORDS = ("\u8bc6\u5b57", "\u6c49\u5b57")
EN_KEYWORDS = ("\u82f1\u6587", "\u82f1\u8bed", "english", "\u82f1\u6587\u9605\u8bfb")
LOW_PRICE_BAIT_KEYWORDS = (
    "\u79c1\u804a",
    "\u5ba2\u670d",
    "\u62cd\u524d\u8054\u7cfb",
    "\u4f4e\u4ef7",
    "\u7279\u4ef7",
    "\u76f4\u5145",
    "\u4e00\u53e3\u4ef7",
    "\u6539\u4ef7",
    "\u5230\u8d26",
)

EXCLUDED_BRAND_KEYWORDS = ("\u8df3\u8df3\u8c61",)


class PriceJudge:
    """价格违规判定 + 搜索词生成"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    def is_below_official(self, price: float, official_price: float) -> bool:
        return price < official_price - PRICE_TOLERANCE

    def is_suspiciously_low(self, price: float, official_price: float) -> bool:
        return price < official_price * 0.5

    def analyze_listing(
        self,
        title: str,
        price: float,
        product_name: str = "",
        official_price: float = 0,
        spec_text: str = "",
    ) -> Dict[str, object]:
        text = self._normalize_text(" ".join([title or "", spec_text or ""]))
        spec_only_text = self._normalize_text(spec_text or "")
        evidence: List[str] = []

        if any(keyword in text for keyword in EXCLUDED_BRAND_KEYWORDS):
            return self._analysis_result(
                decision="IGNORE",
                risk_level="LOW",
                price_judgement_type="UNKNOWN",
                reason="\u547d\u4e2d\u6392\u9664\u54c1\u724c\u8df3\u8df3\u8c61",
                evidence=["\u6392\u9664\u54c1\u724c\uff1a\u8df3\u8df3\u8c61"],
            )

        if not self._is_target_product(text):
            return self._analysis_result(
                decision="IGNORE",
                risk_level="LOW",
                price_judgement_type="UNKNOWN",
                reason="\u975e\u9002\u8da3AI\u9605\u8bfb\u76f8\u5173\u5546\u54c1",
                evidence=[],
            )
        evidence.append("\u547d\u4e2d\u9002\u8da3AI\u9605\u8bfb\u76f8\u5173\u8bcd")

        if self._looks_like_marked_15d_experience_price(text):
            return self._analysis_result(
                decision="REVIEW",
                risk_level="MEDIUM",
                price_judgement_type="MULTI_SKU_SINGLE_PRICE",
                reason="\u6587\u672c\u4e2d\u6ce8\u660e\u6807\u4ef7\u4e3a\u9002\u8da3\u4e2d\u6587/\u82f1\u8bed15\u5929\u4f53\u9a8c\u5361\u4ef7\u683c\uff0c\u4e0d\u81ea\u52a8\u5f52\u5c5e2\u5e74\u5361SKU",
                evidence=["\u547d\u4e2d\uff1a\u6ce8\u660e\u6807\u4ef7\u4e3a15\u5929\u4f53\u9a8c\u5361\u4ef7\u683c"],
            )

        spec_version_candidates = self._detect_versions(spec_only_text)
        spec_period_candidates = self._detect_periods(spec_only_text)
        version_candidates = spec_version_candidates or self._detect_versions(text)
        period_candidates = spec_period_candidates or self._detect_periods(text)
        sku_candidates = self._build_sku_candidates(version_candidates, period_candidates)

        for version in version_candidates:
            evidence.append(f"\u7248\u672c\u5019\u9009\uff1a{version}")
        for period in period_candidates:
            evidence.append(f"\u5468\u671f\u5019\u9009\uff1a{period}")
        if spec_period_candidates:
            evidence.append("\u5468\u671f\u4f18\u5148\u6765\u6e90\uff1a\u5df2\u9009\u89c4\u683c")
        evidence.append(f"\u4ef7\u683c\uff1a{price}")

        has_bait_words = any(word in text for word in LOW_PRICE_BAIT_KEYWORDS)
        lowest_known_price = min(
            rule["official_price"]
            for rule in SKU_RULES.values()
            if float(rule["official_price"]) > 0
        )

        if len(version_candidates) != 1:
            return self._analysis_result(
                decision="REVIEW",
                risk_level="MEDIUM",
                price_judgement_type="MULTI_SKU_SINGLE_PRICE",
                version_candidates=version_candidates,
                period_candidates=period_candidates,
                sku_candidates=sku_candidates,
                reason="\u7248\u672c\u4e0d\u552f\u4e00\u6216\u65e0\u6cd5\u786e\u8ba4\uff0c\u4e0d\u81ea\u52a8\u5f52\u5c5eSKU",
                evidence=evidence,
            )

        if len(period_candidates) != 1:
            decision = "SUSPECTED" if price < lowest_known_price and has_bait_words else "REVIEW"
            return self._analysis_result(
                decision=decision,
                risk_level="HIGH" if decision == "SUSPECTED" else "MEDIUM",
                price_judgement_type="LOW_PRICE_BAIT" if decision == "SUSPECTED" else "MULTI_SKU_SINGLE_PRICE",
                version_candidates=version_candidates,
                period_candidates=period_candidates,
                sku_candidates=sku_candidates,
                reason="\u5468\u671f\u4e0d\u552f\u4e00\u6216\u65e0\u6cd5\u786e\u8ba4\uff0c\u4e0d\u5f3a\u884c\u5224\u65ad\u5177\u4f53SKU",
                evidence=evidence,
            )

        if len(sku_candidates) != 1:
            return self._analysis_result(
                decision="REVIEW",
                risk_level="MEDIUM",
                price_judgement_type="UNKNOWN",
                version_candidates=version_candidates,
                period_candidates=period_candidates,
                sku_candidates=sku_candidates,
                reason="\u7248\u672c\u548c\u5468\u671f\u53ef\u8bc6\u522b\uff0c\u4f46\u672a\u547d\u4e2d\u5df2\u77e5SKU\u89c4\u683c",
                evidence=evidence,
            )

        sku_id = sku_candidates[0]
        sku_price = float(SKU_RULES[sku_id]["official_price"])
        if price > 0 and self.is_below_official(price, sku_price):
            return self._analysis_result(
                decision="VIOLATION",
                risk_level="HIGH",
                price_judgement_type="VIOLATION_CONFIRMED",
                version_candidates=version_candidates,
                period_candidates=period_candidates,
                sku_candidates=sku_candidates,
                reason=f"\u660e\u786eSKU {sku_id} \u4ef7\u683c {price} \u4f4e\u4e8e\u6807\u51c6\u4ef7 {sku_price}",
                evidence=evidence,
            )

        return self._analysis_result(
            decision="NORMAL",
            risk_level="LOW",
            price_judgement_type="EXACT_SKU_PRICE",
            version_candidates=version_candidates,
            period_candidates=period_candidates,
            sku_candidates=sku_candidates,
            reason=f"\u660e\u786eSKU {sku_id} \u4ef7\u683c\u672a\u4f4e\u4e8e\u6807\u51c6\u4ef7 {sku_price}",
            evidence=evidence,
        )

    def _analysis_result(self, **kwargs) -> Dict[str, object]:
        result = {
            "decision": "UNKNOWN",
            "risk_level": "LOW",
            "price_judgement_type": "UNKNOWN",
            "version_candidates": [],
            "period_candidates": [],
            "sku_candidates": [],
            "confidence": 0.5,
            "reason": "",
            "evidence": [],
        }
        result.update(kwargs)
        return result

    def _normalize_text(self, text: str) -> str:
        return (text or "").lower().replace(" ", "")

    def _is_target_product(self, text: str) -> bool:
        return any(keyword in text for keyword in TARGET_KEYWORDS)

    def _looks_like_marked_15d_experience_price(self, text: str) -> bool:
        return (
            "\u6ce8" in text
            and "\u6807\u4ef7" in text
            and "\u4f53\u9a8c\u5361\u4ef7\u683c" in text
            and any(token in text for token in ("\u82f1\u8bed15\u5929", "\u82f1\u658715\u5929", "\u82f1\u8bed\u5341\u4e94\u5929", "\u82f1\u6587\u5341\u4e94\u5929"))
            and any(token in text for token in ("\u9002\u8da3\u4e2d\u6587", "\u4e2d\u658715\u5929", "\u4e2d\u6587\u5341\u4e94\u5929"))
        )

    def _detect_versions(self, text: str) -> List[str]:
        versions = []
        has_en = any(keyword in text for keyword in EN_KEYWORDS)
        if any(keyword in text for keyword in CN_KEYWORDS):
            versions.append("CN")
        elif not has_en and any(keyword in text for keyword in CN_FALLBACK_KEYWORDS):
            versions.append("CN")
        if has_en:
            versions.append("EN")
        return versions

    def _detect_periods(self, text: str) -> List[str]:
        periods = []
        if any(token in text for token in ("7\u5929", "7\u65e5", "7day", "7days", "\u4e03\u5929")):
            periods.append("7D")
        if any(token in text for token in ("15\u5929", "15\u65e5", "15day", "15days", "\u5341\u4e94\u5929", "\u534a\u6708")):
            periods.append("15D")
        if any(token in text for token in ("21\u5929", "21\u65e5", "21day", "21days", "\u4e8c\u5341\u4e00\u5929", "\u4e09\u5468")):
            periods.append("21D")
        if any(
            token in text
            for token in (
                "\u5e74\u5361",
                "\u5e74\u4f1a\u5458",
                "\u4e00\u5e74",
                "1\u5e74",
                "\u4e24\u5e74",
                "2\u5e74",
                "12\u4e2a\u6708",
                "365\u5929",
            )
        ):
            periods.append("YEAR")
        return periods

    def _build_sku_candidates(self, versions: List[str], periods: List[str]) -> List[str]:
        candidates = []
        for sku_id, rule in SKU_RULES.items():
            if rule["version"] in versions and rule["period"] in periods:
                candidates.append(sku_id)
        return candidates

    def format_analysis_reason(self, analysis: Dict[str, object]) -> str:
        evidence = analysis.get("evidence") or []
        evidence_text = "\uff1b".join(str(item) for item in evidence[:5])
        return (
            f"type={analysis.get('price_judgement_type')}; "
            f"risk={analysis.get('risk_level')}; "
            f"sku={','.join(analysis.get('sku_candidates') or [])}; "
            f"reason={analysis.get('reason')}; "
            f"evidence={evidence_text}"
        )

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
