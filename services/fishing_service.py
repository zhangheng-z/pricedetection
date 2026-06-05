import json
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

    def update_alert_status(self, db_path: str, alert_id: int, status: str) -> None:
        if status not in self.ALERT_STATUSES:
            raise ValueError(f"Unsupported alert status: {status}")
        if not Database(db_path).update_alert_status(alert_id, status):
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
                message, llm_payload = self._build_reply_message(alert, llm, conversation_messages)
            else:
                self._log(f"[fishing] no existing conversation detected session={session_id}")
                message, llm_payload = self._build_initial_message(alert, llm)

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

    def _build_initial_message(self, alert: dict, llm: Optional[LLMClient]) -> tuple[str, dict]:
        if not llm:
            return ("你好，这个还在吗？页面这个价格是实际到手价吗？", {"source": "fallback"})

        prompt = PromptTemplates.FISHING_CHAT.format(
            product_name=alert.get("product_name", ""),
            official_price=alert.get("official_price", ""),
            listing_price=alert.get("price", ""),
            title=alert.get("title", ""),
            seller_name=alert.get("seller_name", ""),
            reason=alert.get("reason", ""),
            conversation="无",
        )
        payload = llm.chat_json(messages=[{"role": "user", "content": prompt}])
        if not isinstance(payload, dict):
            raise ValueError("Fishing LLM response must be a JSON object.")
        message = str(payload.get("message", "")).strip()
        if not message:
            raise ValueError("Fishing LLM response has empty message.")
        return (message, payload)

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
        conversation_lines = []
        for message in conversation_messages[-8:]:
            role = "卖家" if message.get("sender") == "seller" else "买家"
            conversation_lines.append(f"{role}：{message.get('content', '')}")

        if not llm:
            buyer_turns = sum(1 for message in conversation_messages if message.get("sender") == "buyer")
            if buyer_turns <= 1:
                return ("这个是页面标的规格吗？现在可以直接按这个价格拍吗？", {"source": "fallback", "should_stop": False})
            return ("好的，那现在拍下就是按这个价格发对吧？", {"source": "fallback", "should_stop": False})

        prompt = PromptTemplates.FISHING_CHAT.format(
            product_name=alert.get("product_name", ""),
            official_price=alert.get("official_price", ""),
            listing_price=alert.get("price", ""),
            title=alert.get("title", ""),
            seller_name=alert.get("seller_name", ""),
            reason=alert.get("reason", ""),
            conversation="\n".join(conversation_lines),
        )
        payload = llm.chat_json(messages=[{"role": "user", "content": prompt}])
        if not isinstance(payload, dict):
            raise ValueError("Fishing LLM response must be a JSON object.")
        message = str(payload.get("message", "")).strip()
        if not message:
            raise ValueError("Fishing LLM response has empty message.")
        return (message, payload)

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
