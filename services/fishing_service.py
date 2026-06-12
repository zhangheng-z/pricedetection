import json
import re
from dataclasses import dataclass
from typing import Callable, Optional

from agents.xianyu_agent import XianyuAgent
from config.loader import AccountConfig, ConfigLoader, ProductConfig, Settings
from llm.client import LLMClient
from llm.prompts import PromptTemplates
from storage.database import Database


@dataclass
class FishingStartResult:
    session_id: int
    alert_id: int
    message: str
    auto_sent: bool
    status: str


@dataclass
class ReplyCheckSummary:
    checked: int = 0
    updated: int = 0
    waiting: int = 0
    failed: int = 0


@dataclass
class FishingRuleDecision:
    message: str = ""
    tag: str = ""
    status: str = ""
    reason: str = ""
    should_stop: bool = False
    product_type: str = ""
    payment_status: str = ""


@dataclass
class ProductTypeDecision:
    product_type: str = "uncertain"
    confidence: str = "low"
    reason: str = ""
    source: str = "local_rule"
    message: str = ""


class FishingService:
    MAX_AUTO_REPLY_ROUNDS = 2
    SELLER_REPLY_TIMEOUT_SECONDS = 60
    ALERT_STATUSES = {
        "pending",
        "fishing",
        "waiting_seller",
        "seller_replied",
        "manual_required",
        "failed",
        "evidence_collected",
        "resolved",
    }

    def __init__(
        self,
        config_loader: Optional[ConfigLoader] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.config_loader = config_loader or ConfigLoader()
        self.log_callback = log_callback
        self._active_agents: dict[int, XianyuAgent] = {}

    def list_alerts(self, db_path: str) -> list[dict]:
        return Database(db_path).list_fishable_alerts()

    def list_messages(self, db_path: str, listing_id: int) -> list[dict]:
        return Database(db_path).list_fishing_messages_by_listing(listing_id)

    PRODUCT_TYPES = {
        "",
        "gray_account",
        "channel_resale",
        "personal_transfer",
        "short_term_low_price",
        "uncertain",
    }

    def update_alert_status(self, db_path: str, alert_id: int, status: str, product_type: str = "") -> None:
        if status not in self.ALERT_STATUSES:
            raise ValueError(f"Unsupported alert status: {status}")
        if product_type not in self.PRODUCT_TYPES:
            raise ValueError(f"Unsupported product type: {product_type}")
        if not Database(db_path).update_alert_status_and_product_type(alert_id, status, product_type):
            raise ValueError(f"Alert not found: {alert_id}")

    def delete_alert(self, db_path: str, alert_id: int) -> None:
        if not Database(db_path).delete_alert(alert_id):
            raise ValueError(f"Alert not found: {alert_id}")

    async def check_waiting_replies(
        self,
        db_path: str,
        limit: int = 10,
        headless: bool = False,
    ) -> ReplyCheckSummary:
        alerts = [
            alert
            for alert in self.list_alerts(db_path)
            if alert.get("status") == "waiting_seller"
        ][:limit]
        summary = ReplyCheckSummary()
        for alert in alerts:
            alert_id = int(alert.get("alert_id") or 0)
            if not alert_id:
                continue
            try:
                result = await self.start_fishing(
                    db_path=db_path,
                    alert_id=alert_id,
                    auto_send=True,
                    headless=headless,
                )
                summary.checked += 1
                if result.status == "waiting_seller":
                    summary.waiting += 1
                else:
                    summary.updated += 1
            except Exception as exc:
                summary.checked += 1
                summary.failed += 1
                self._log(f"[fishing] reply check failed alert={alert_id}: {exc}")
        return summary

    async def start_fishing(
        self,
        db_path: str,
        alert_id: int,
        account_id: str = "",
        auto_send: bool = False,
        headless: bool = False,
    ) -> FishingStartResult:
        db = Database(db_path)
        alert = db.get_fishing_alert(alert_id)
        if not alert:
            raise ValueError(f"Alert not found: {alert_id}")
        if alert["platform"] != "xianyu":
            raise ValueError(f"Only xianyu fishing is supported now: {alert['platform']}")
        if not alert.get("url"):
            raise ValueError("Listing URL is empty.")

        settings: Settings = self.config_loader.load_settings()
        account = self._select_account(account_id)
        session_id = db.create_fishing_session(
            alert_id=alert["alert_id"],
            listing_id=alert["listing_id"],
            platform=alert["platform"],
            account_id=account.id,
        )
        db.update_alert_status(alert_id, "fishing")
        db.update_fishing_session_status(session_id, "opening", "opening_detail")

        agent = None
        try:
            llm = LLMClient(settings.llm) if settings.llm.api_key else None
            product_type = self._build_initial_plan(alert, llm)
            self._log(
                f"[fishing] product type alert={alert_id}: "
                f"type={product_type.product_type}, confidence={product_type.confidence}, "
                f"source={product_type.source}, reason={product_type.reason}"
            )
            db.update_alert_product_type(
                alert_id,
                product_type.product_type,
                self._initial_payment_status(product_type.product_type),
            )
            if product_type.product_type == "personal_transfer":
                reason = f"个人闲置转让型：{product_type.reason or '商品信息体现个人闲置转让特征'}"
                db.update_alert_status_and_reason(
                    alert_id,
                    "resolved",
                    reason,
                    product_type="personal_transfer",
                )
                db.update_fishing_session_status(
                    session_id,
                    "resolved",
                    "personal_transfer",
                    finished=True,
                )
                return FishingStartResult(
                    session_id=session_id,
                    alert_id=alert_id,
                    message="",
                    auto_sent=auto_send,
                    status="resolved",
                )

            agent = self._build_agent(db, alert, account, settings, llm, headless)
            self._log(f"[fishing] opening listing alert={alert_id} session={session_id}")
            page = await agent.start_chat_for_listing(alert["url"])
            db.update_fishing_session_status(session_id, "chat_opened", "chat_opened")

            self._log(f"[fishing] reading existing conversation session={session_id}")
            existing_messages = await agent.read_chat_messages(page, save_diagnostics=True)
            conversation_messages = self._normalize_dialogue_messages(existing_messages)
            if self._sync_recognized_history(
                db=db,
                listing_id=alert["listing_id"],
                session_id=session_id,
                recognized_messages=conversation_messages,
            ):
                self._log(
                    f"[fishing] warning: database messages did not match recognized history; "
                    f"rebuilt listing messages listing={alert['listing_id']} session={session_id}"
                )

            if alert.get("status") == "waiting_seller" and self._last_dialogue_sender(conversation_messages) == "buyer":
                self._log(f"[fishing] listing is waiting for seller; checking reply for 60 seconds session={session_id}")
                known_contents = {
                    str(message.get("content", "")).strip()
                    for message in conversation_messages
                    if str(message.get("content", "")).strip()
                }
                seller_messages = await agent.wait_for_seller_messages(
                    page,
                    known_contents,
                    timeout_seconds=self.SELLER_REPLY_TIMEOUT_SECONDS,
                )
                seller_messages = self._normalize_dialogue_messages(seller_messages)
                if not seller_messages:
                    db.update_alert_status(alert_id, "waiting_seller")
                    db.update_fishing_session_status(session_id, "waiting_seller", "waiting_seller_reply")
                    await agent.close_fishing_browser()
                    return FishingStartResult(
                        session_id=session_id,
                        alert_id=alert_id,
                        message="",
                        auto_sent=auto_send,
                        status="waiting_seller",
                    )
                db.update_alert_status(alert_id, "seller_replied")
                db.update_fishing_session_status(session_id, "seller_replied", "seller_replied_after_wait")
                for seller_message in seller_messages:
                    content = seller_message["content"]
                    conversation_messages.append(seller_message)
                    db.save_fishing_message(alert["listing_id"], session_id, "seller", content)
                    self._log(f"[fishing] seller replied session={session_id}: {content}")

            if conversation_messages:
                self._log(
                    f"[fishing] existing conversation detected session={session_id}, "
                    f"messages={len(conversation_messages)}"
                )
                decision = self._classify_dialogue_by_rules(alert, conversation_messages)
                if decision.should_stop:
                    db.update_alert_status_and_reason(
                        alert_id,
                        decision.status,
                        decision.reason,
                        product_type=decision.product_type,
                        payment_status=decision.payment_status,
                    )
                    db.update_fishing_session_status(session_id, decision.status, decision.tag, finished=True)
                    self._log(
                        f"[fishing] rule decision session={session_id}: "
                        f"tag={decision.tag}, status={decision.status}, reason={decision.reason}"
                    )
                    await agent.close_fishing_browser()
                    return FishingStartResult(
                        session_id=session_id,
                        alert_id=alert_id,
                        message="",
                        auto_sent=auto_send,
                        status=decision.status,
                    )
                message, llm_payload = self._build_reply_message(alert, llm, conversation_messages)
            else:
                self._log(f"[fishing] no existing conversation detected session={session_id}")
                message, llm_payload = self._build_initial_message(alert, product_type)

            should_stop = bool(llm_payload.get("should_stop")) if isinstance(llm_payload, dict) else False
            if should_stop:
                self._log(
                    f"[fishing] LLM decided evidence is collected before send session={session_id}: "
                    f"{llm_payload.get('reason', '')}"
                )

            self._log(f"[fishing] sending next message session={session_id}: {message}")
            ok = await agent.send_chat_message(page, message) if auto_send else await agent.fill_chat_message(page, message)
            if not ok:
                raise RuntimeError("未找到可输入的聊天框")

            final_status = "message_sent" if auto_send else "message_filled"
            db.save_fishing_message(alert["listing_id"], session_id, "buyer", message)
            conversation_messages.append({"sender": "buyer", "content": message})
            db.update_fishing_session_status(
                session_id,
                "message_sent" if auto_send else "message_filled",
                "next_message_sent" if auto_send else "next_message_filled",
            )
            if should_stop:
                final_status = "evidence_collected"
                db.update_alert_status(alert_id, "evidence_collected")
                db.update_fishing_session_status(session_id, "evidence_collected", "final_message_sent")
            elif auto_send:
                final_status = await self._run_auto_dialogue(
                    db=db,
                    session_id=session_id,
                    alert=alert,
                    llm=llm,
                    agent=agent,
                    page=page,
                    sent_messages=[message],
                    conversation_messages=conversation_messages,
                )
            if final_status == "waiting_seller":
                await agent.close_fishing_browser()
            else:
                self._active_agents[session_id] = agent
            self._log(
                f"[fishing] {'sent' if auto_send else 'filled'} next message "
                f"session={session_id}: {message}"
            )
            return FishingStartResult(
                session_id=session_id,
                alert_id=alert_id,
                message=message,
                auto_sent=auto_send,
                status=final_status,
            )
        except Exception as exc:
            if agent:
                await agent.close_fishing_browser()
            db.update_alert_status(alert_id, "failed")
            db.update_fishing_session_status(session_id, "failed", "failed", str(exc), finished=True)
            raise

    async def close_session(self, session_id: int) -> None:
        agent = self._active_agents.pop(session_id, None)
        if agent:
            await agent.close_fishing_browser()

    def _build_initial_message(self, alert: dict, plan: ProductTypeDecision) -> tuple[str, dict]:
        message = self._normalize_chat_message_style(plan.message)
        if not message:
            message = self._build_initial_message_by_rules(alert)
        if not message:
            message = "这个价格是一年还是两年，需要换号吗"
        return (
            message,
            {
                "source": plan.source,
                "product_type": plan.product_type,
                "confidence": plan.confidence,
                "reason": plan.reason,
                "should_stop": False,
            },
        )

    async def _run_auto_dialogue(
        self,
        db: Database,
        session_id: int,
        alert: dict,
        llm: Optional[LLMClient],
        agent: XianyuAgent,
        page,
        sent_messages: list[str],
        conversation_messages: list[dict],
    ) -> str:
        known_contents = {
            str(message.get("content", "")).strip()
            for message in conversation_messages
            if str(message.get("content", "")).strip()
        }
        known_contents.update(sent_messages)
        final_status = "message_sent"

        for round_index in range(1, self.MAX_AUTO_REPLY_ROUNDS + 1):
            self._log(
                f"[fishing] waiting seller reply round {round_index}/{self.MAX_AUTO_REPLY_ROUNDS} "
                f"session={session_id}"
            )
            db.update_fishing_session_status(session_id, "waiting_seller", f"waiting_seller_round_{round_index}")
            seller_messages = await agent.wait_for_seller_messages(
                page,
                known_contents,
                timeout_seconds=self.SELLER_REPLY_TIMEOUT_SECONDS,
            )
            if not seller_messages:
                self._log(f"[fishing] no seller reply detected session={session_id}")
                db.update_alert_status(alert["alert_id"], "waiting_seller")
                db.update_fishing_session_status(session_id, "waiting_seller", "waiting_seller_reply")
                return "waiting_seller"

            db.update_alert_status(alert["alert_id"], "seller_replied")
            db.update_fishing_session_status(session_id, "seller_replied", f"seller_replied_round_{round_index}")
            new_seller_messages = []
            for seller_message in seller_messages:
                content = str(seller_message.get("content", "")).strip()
                if not content or content in known_contents:
                    continue
                known_contents.add(content)
                new_seller_messages.append({"sender": "seller", "content": content})
                conversation_messages.append({"sender": "seller", "content": content})
                db.save_fishing_message(alert["listing_id"], session_id, "seller", content)
                self._log(f"[fishing] seller replied session={session_id}: {content}")

            if not new_seller_messages:
                db.update_alert_status(alert["alert_id"], "waiting_seller")
                db.update_fishing_session_status(session_id, "waiting_seller", "waiting_seller_reply")
                return "waiting_seller"

            decision = self._classify_dialogue_by_rules(alert, conversation_messages)
            if decision.should_stop:
                db.update_alert_status_and_reason(
                    alert["alert_id"],
                    decision.status,
                    decision.reason,
                    product_type=decision.product_type,
                    payment_status=decision.payment_status,
                )
                db.update_fishing_session_status(session_id, decision.status, decision.tag, finished=True)
                self._log(
                    f"[fishing] rule decision session={session_id}: "
                    f"tag={decision.tag}, status={decision.status}, reason={decision.reason}"
                )
                return decision.status

            reply, reply_payload = self._build_reply_message(alert, llm, conversation_messages)
            should_stop = bool(reply_payload.get("should_stop")) if isinstance(reply_payload, dict) else False
            if should_stop:
                self._log(f"[fishing] LLM decided to stop session={session_id}: {reply_payload.get('reason', '')}")
            self._log(f"[fishing] sending reply round {round_index} session={session_id}: {reply}")
            if not await agent.send_chat_message(page, reply):
                db.update_alert_status(alert["alert_id"], "manual_required")
                db.update_fishing_session_status(session_id, "manual_required", "reply_send_failed")
                return "manual_required"

            known_contents.add(reply)
            sent_messages.append(reply)
            conversation_messages.append({"sender": "buyer", "content": reply})
            db.save_fishing_message(alert["listing_id"], session_id, "buyer", reply)
            if should_stop:
                db.update_alert_status(alert["alert_id"], "evidence_collected")
                db.update_fishing_session_status(session_id, "evidence_collected", f"final_reply_sent_round_{round_index}")
                return "evidence_collected"
            db.update_fishing_session_status(session_id, "dialogue_replied", f"reply_sent_round_{round_index}")
            final_status = "dialogue_replied"

        db.update_fishing_session_status(session_id, final_status, "max_auto_rounds_reached")
        return final_status

    def _normalize_dialogue_messages(self, messages: list[dict]) -> list[dict]:
        result = []
        seen = set()
        for message in messages:
            sender = str(message.get("sender", "")).strip() or "seller"
            content = str(message.get("content", "")).strip()
            if sender not in {"buyer", "seller"} or not content:
                continue
            key = (sender, content)
            if key in seen:
                continue
            seen.add(key)
            result.append({"sender": sender, "content": content})
        return result

    def _last_dialogue_sender(self, messages: list[dict]) -> str:
        for message in reversed(messages):
            sender = str(message.get("sender", "")).strip()
            if sender in {"buyer", "seller"}:
                return sender
        return ""

    def _sync_recognized_history(
        self,
        db: Database,
        listing_id: int,
        session_id: int,
        recognized_messages: list[dict],
    ) -> bool:
        stored_messages = [
            {"sender": message.get("sender", ""), "content": message.get("content", "")}
            for message in db.list_fishing_messages_by_listing(listing_id)
            if message.get("sender") in {"buyer", "seller"}
        ]
        if stored_messages == recognized_messages:
            return False
        db.replace_fishing_messages_for_listing(listing_id, session_id, recognized_messages)
        return True

    def _build_reply_message(
        self,
        alert: dict,
        llm: Optional[LLMClient],
        conversation_messages: list[dict],
    ) -> tuple[str, dict]:
        rule_decision = self._build_follow_up_by_rules(alert, conversation_messages)
        if rule_decision.message:
            return (
                rule_decision.message,
                {
                    "source": "local_rule",
                    "intent": rule_decision.reason,
                    "should_stop": False,
                },
            )

        if not llm:
            buyer_turns = sum(1 for message in conversation_messages if message.get("sender") == "buyer")
            if buyer_turns <= 1:
                return ("这个价格是一年还是两年，需要换号吗", {"source": "fallback", "should_stop": False})
            return ("使用中需要换号吗", {"source": "fallback", "should_stop": False})

        prompt = PromptTemplates.FISHING_CHAT.format(
            listing_price=alert.get("price", ""),
            title=alert.get("title", ""),
            question=self._latest_dialogue_content(conversation_messages, "buyer"),
            seller_reply=self._latest_dialogue_content(conversation_messages, "seller"),
        )
        payload = llm.chat_json(messages=[{"role": "user", "content": prompt}])
        if not isinstance(payload, dict):
            raise ValueError("Fishing LLM response must be a JSON object.")
        message = str(payload.get("follow_up_message", "")).strip()
        tag = str(payload.get("tag", "")).strip()
        if not message and tag == "need_ask_change_account":
            message = "使用中需要换账号吗"
        if not message and tag in {"need_manual_review", "suspicious_low_price_no_change"}:
            message = "这个价格是一年还是两年，需要换账号吗"
        if not message:
            raise ValueError("Fishing LLM response has empty follow_up_message.")
        message = self._normalize_chat_message_style(message)
        payload["follow_up_message"] = message
        return (message, payload)

    def _build_initial_message_by_rules(self, alert: dict) -> str:
        price = self._alert_price(alert)
        if price <= 0:
            return ""

        price_text = self._format_price_text(price)
        duration = self._title_duration_state(alert.get("title", ""))
        if self._looks_like_short_term(alert.get("title", "")):
            return f"{price_text}是多久的，需要换账号吗"
        if price < 1000:
            if duration == "one_year":
                return f"{price_text}是一年吗，需要换账号吗"
            if duration == "two_year":
                return f"{price_text}是两年吗，需要换账号吗"
            return f"{price_text}是一年还是两年，需要换账号吗"

        if duration == "one_year":
            return f"{price_text}是一年还是两年，需要换账号吗"
        return f"{price_text}是两年吗，需要换账号吗"

    def _initial_payment_status(self, product_type: str) -> str:
        return "unpaid" if product_type == "channel_resale" else ""

    def _build_initial_plan(self, alert: dict, llm: Optional[LLMClient]) -> ProductTypeDecision:
        if llm:
            prompt = PromptTemplates.FISHING_INITIAL_CHAT.format(
                product_name=alert.get("product_name", ""),
                listing_price=self._format_price_text(self._alert_price(alert)),
                title=alert.get("title", ""),
                reason=alert.get("reason", ""),
            )
            try:
                payload = llm.chat_json(messages=[{"role": "user", "content": prompt}])
            except Exception as exc:
                self._log(f"[fishing] product type LLM failed, fallback to local rule: {exc}")
                payload = {}
            if isinstance(payload, dict):
                product_type = str(payload.get("product_type", "")).strip()
                if product_type in {
                    "gray_account",
                    "personal_transfer",
                    "channel_resale",
                    "short_term_low_price",
                    "uncertain",
                }:
                    message = self._normalize_chat_message_style(str(payload.get("message", "")).strip())
                    return ProductTypeDecision(
                        product_type=product_type,
                        confidence=str(payload.get("confidence", "low")).strip() or "low",
                        reason=str(payload.get("reason", "")).strip(),
                        source="llm",
                        message=message,
                    )

        return self._classify_product_type_by_rules(alert)

    def _classify_product_type_by_rules(self, alert: dict) -> ProductTypeDecision:
        text = f"{alert.get('title', '')}\n{alert.get('reason', '')}"
        value = re.sub(r"\s+", "", str(text or "").lower())
        price = self._alert_price(alert)
        message = self._build_initial_message_by_rules(alert)

        personal_patterns = (
            "自用",
            "闲置",
            "转让",
            "用不上",
            "不用了",
            "剩余",
            "转手",
            "出掉",
            "回血",
        )
        if any(pattern in value for pattern in personal_patterns):
            return ProductTypeDecision(
                product_type="personal_transfer",
                confidence="medium",
                reason="标题或原因包含个人闲置转让特征",
                message="",
            )

        if self._looks_like_short_term(value):
            return ProductTypeDecision(
                product_type="short_term_low_price",
                confidence="medium",
                reason="标题或原因包含短期低价时长特征",
                message=message,
            )

        gray_patterns = (
            "换号",
            "共享",
            "售后",
            "15天",
            "十五天",
            "半个月",
            "直登",
            "账号",
        )
        if price < 1000 and (any(pattern in value for pattern in gray_patterns) or self._looks_like_long_term(value)):
            return ProductTypeDecision(
                product_type="gray_account",
                confidence="medium",
                reason="低价长期商品，疑似灰产账号型",
                message=message,
            )

        channel_patterns = (
            "渠道",
            "库存",
            "货源",
            "外流",
            "不用换号",
            "无需换号",
        )
        if price >= 1000 and (any(pattern in value for pattern in channel_patterns) or self._looks_like_long_term(value)):
            return ProductTypeDecision(
                product_type="channel_resale",
                confidence="medium",
                reason="一千元以上长期商品，疑似渠道贩卖型",
                message=message,
            )

        return ProductTypeDecision(reason="商品信息不足，无法预判类型", message=message)

    def _build_follow_up_by_rules(self, alert: dict, conversation_messages: list[dict]) -> FishingRuleDecision:
        seller_text = self._seller_text(conversation_messages)
        if not seller_text:
            return FishingRuleDecision()

        duration = self._duration_from_text(seller_text)
        change = self._account_change_state(seller_text)

        if change == "unknown":
            return FishingRuleDecision(message="使用中需要换账号吗", reason="补问是否需要换账号")
        if duration == "unknown":
            return FishingRuleDecision(message="这个价格是一年还是两年", reason="补问价格对应年份")
        return FishingRuleDecision()

    def _classify_dialogue_by_rules(self, alert: dict, conversation_messages: list[dict]) -> FishingRuleDecision:
        seller_text = self._seller_text(conversation_messages)
        if not seller_text:
            return FishingRuleDecision()

        price = self._alert_price(alert)
        duration = self._duration_from_text(seller_text)
        change = self._account_change_state(seller_text)

        if change == "need_change":
            return FishingRuleDecision(
                tag="gray_account",
                status="resolved",
                reason="灰产账号类型：卖家确认使用过程中需要换号",
                should_stop=True,
                product_type="gray_account",
            )
        if change == "no_change":
            return FishingRuleDecision(
                tag="manual_payment_required",
                status="manual_required",
                reason="需要人工付款：卖家确认一直不用换账号",
                should_stop=True,
                product_type="channel_resale",
                payment_status="unpaid",
            )
        return FishingRuleDecision()

    def _alert_price(self, alert: dict) -> float:
        try:
            return float(alert.get("price") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _format_price_text(self, price: float) -> str:
        return f"{float(price):g}"

    def _normalize_chat_message_style(self, message: str) -> str:
        value = str(message or "").strip()
        value = re.sub(r"[？?。.!！]+", "", value)
        value = re.sub(r"[，,、；;]+", "，", value)
        return value.strip(" ，,、；;")

    def _seller_text(self, conversation_messages: list[dict]) -> str:
        return "\n".join(
            str(message.get("content", "")).strip()
            for message in conversation_messages
            if message.get("sender") == "seller" and str(message.get("content", "")).strip()
        )

    def _latest_dialogue_content(self, conversation_messages: list[dict], sender: str) -> str:
        for message in reversed(conversation_messages):
            if message.get("sender") != sender:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                return content
        return ""

    def _title_duration_state(self, title: str) -> str:
        has_one = self._has_one_year(title)
        has_two = self._has_two_year(title)
        if has_one and not has_two:
            return "one_year"
        if has_two and not has_one:
            return "two_year"
        return "unknown"

    def _duration_from_text(self, text: str) -> str:
        if self._has_two_year(text):
            return "two_year"
        if self._has_one_year(text):
            return "one_year"
        return "unknown"

    def _has_one_year(self, text: str) -> bool:
        value = str(text or "")
        return bool(re.search(r"(?<![两二2])(?:一|1)\s*年", value))

    def _has_two_year(self, text: str) -> bool:
        value = str(text or "")
        return bool(re.search(r"(?:两|二|2)\s*年", value))

    def _looks_like_short_term(self, text: str) -> bool:
        value = re.sub(r"\s+", "", str(text or "").lower())
        if any(pattern in value for pattern in ("短期", "体验", "月卡", "周卡", "天卡")):
            return True
        return bool(re.search(r"(?:[1-9]|1[0-9]|2[0-9]|3[01]|七|十五|二十一|21|15|7)天", value))

    def _looks_like_long_term(self, text: str) -> bool:
        value = re.sub(r"\s+", "", str(text or "").lower())
        return any(pattern in value for pattern in ("年卡", "一年", "1年", "两年", "二年", "2年", "长期"))

    def _account_change_state(self, text: str) -> str:
        value = re.sub(r"\s+", "", str(text or "").lower())
        no_change_patterns = (
            "不用换号",
            "不用换账号",
            "不需要换号",
            "不需要换账号",
            "无需换号",
            "无需换账号",
            "不用换",
            "不换号",
            "不换账号",
            "无需更换",
            "不需要更换",
            "一直用",
            "一直不用换",
            "同一个账号",
            "固定账号",
        )
        if any(pattern in value for pattern in no_change_patterns):
            return "no_change"

        need_change_patterns = (
            "需要换号",
            "需要换账号",
            "要换号",
            "要换账号",
            "得换号",
            "得换账号",
            "换号",
            "换账号",
            "更换账号",
            "定期换",
            "售后换",
            "到期换",
            "用不了换",
            "15天",
            "十五天",
            "半个月",
        )
        if any(pattern in value for pattern in need_change_patterns):
            return "need_change"
        if re.search(r"(每|隔|[0-9一二三四五六七八九十]+天).*换", value):
            return "need_change"
        return "unknown"

    def _build_agent(
        self,
        db: Database,
        alert: dict,
        account: AccountConfig,
        settings: Settings,
        llm: Optional[LLMClient],
        headless: bool,
    ) -> XianyuAgent:
        product = ProductConfig(
            name=alert.get("product_name") or "unknown",
            official_price=float(alert.get("official_price") or 0),
            keywords=[],
            platforms=["xianyu"],
        )
        return XianyuAgent(
            db=db,
            product=product,
            account=account,
            llm_client=llm,
            headless=headless,
            proxy=account.proxy or None,
            anti_risk=settings.anti_risk,
        )

    def _select_account(self, account_id: str = "") -> AccountConfig:
        accounts = self.config_loader.load_accounts()
        candidates = [
            account
            for account in accounts
            if account.platform == "xianyu" and account.status == "active"
        ]
        if account_id:
            for account in candidates:
                if account.id == account_id:
                    return account
            raise ValueError(f"Active xianyu account not found: {account_id}")
        for account in candidates:
            if account.type == "search":
                return account
        if candidates:
            return candidates[0]
        raise ValueError("No active xianyu account configured.")

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)
