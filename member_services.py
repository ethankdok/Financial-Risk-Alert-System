from __future__ import annotations

import hashlib
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage as SmtpMessage
from datetime import UTC, datetime
from typing import Any, Callable

from flask_data_repository import DuplicateRecordError, FlaskDataRepository
from werkzeug.security import check_password_hash, generate_password_hash


def utc_now_str() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bool_int(value: Any, default: int = 1) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value else 0
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "on"} else 0


class MemberAuthService:
    """Member authentication boundary.

    Production should use Firebase/Identity Platform ID tokens. Local password
    auth is only for development and tests, and never stores member passwords in
    Firestore.
    """

    def __init__(self, repository: FlaskDataRepository, *, app_env: str = "development") -> None:
        self.repository = repository
        self.app_env = app_env.strip().lower()

    def local_password_enabled(self) -> bool:
        if self.app_env == "production":
            return False
        configured = os.getenv("MEMBER_ALLOW_LOCAL_PASSWORD_AUTH")
        if configured is not None:
            return configured.strip().lower() in {"1", "true", "yes", "on"}
        return self.app_env != "production" and self.repository.backend_name == "sqlite"

    def register_local(self, *, email: str, password: str, display_name: str) -> dict[str, Any]:
        if not self.local_password_enabled():
            raise RuntimeError("Local member password registration is disabled for this runtime.")
        clean_email = email.strip().lower()
        if "@" not in clean_email:
            raise ValueError("請輸入有效的 Email")
        if len(password) < 8:
            raise ValueError("密碼至少需要 8 個字元")
        now = utc_now_str()
        member = {
            "uid": f"local_{uuid.uuid4().hex}",
            "email": clean_email,
            "display_name": display_name.strip() or clean_email.split("@")[0],
            "account_status": "active",
            "auth_provider": "local_password",
            "created_at": now,
            "updated_at": now,
            "schema_version": 1,
        }
        created = self.repository.create_member(member)
        self.repository.set_member_password_hash(created["uid"], generate_password_hash(password))
        self.repository.save_notification_preferences(created["uid"], {"updated_at": now})
        return created

    def login_local(self, *, email: str, password: str) -> dict[str, Any] | None:
        if not self.local_password_enabled():
            raise RuntimeError("Local member password login is disabled for this runtime.")
        member = self.repository.get_member_by_email(email.strip().lower())
        if not member or member.get("account_status") != "active":
            return None
        password_hash = self.repository.get_member_password_hash(str(member["uid"]))
        if not password_hash or not check_password_hash(password_hash, password):
            return None
        return member

    def upsert_managed_identity(self, *, uid: str, email: str, display_name: str, provider: str) -> dict[str, Any]:
        now = utc_now_str()
        existing = self.repository.get_member(uid)
        fields = {
            "uid": uid,
            "email": email.strip().lower(),
            "display_name": display_name.strip() or email.split("@")[0],
            "account_status": "active",
            "auth_provider": provider,
            "updated_at": now,
            "schema_version": 1,
        }
        if existing:
            return self.repository.update_member(uid, fields) or {**existing, **fields}
        return self.repository.create_member({**fields, "created_at": now})

    def login_firebase_token(self, id_token: str) -> dict[str, Any]:
        project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT must be configured for managed member auth.")
        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token
        except ImportError as exc:  # pragma: no cover - dependency is transitive in deployed runtime
            raise RuntimeError("google-auth is required for Firebase member token verification.") from exc
        claims = google_id_token.verify_firebase_token(id_token, google_requests.Request(), audience=project_id)
        uid = str(claims.get("sub") or claims.get("user_id") or "")
        email = str(claims.get("email") or "")
        if not uid or not email:
            raise ValueError("Firebase token is missing uid or email.")
        return self.upsert_managed_identity(
            uid=uid,
            email=email,
            display_name=str(claims.get("name") or ""),
            provider="firebase",
        )


@dataclass(slots=True)
class EmailMessage:
    to_email: str
    subject: str
    body: str
    notification_type: str


class EmailProvider:
    name = "console"

    def send(self, message: EmailMessage) -> dict[str, Any]:
        return {"provider": self.name, "status": "dry_run", "message_id": None}

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "configured": True, "status": "dry_run"}


class ConsoleEmailProvider(EmailProvider):
    name = "console"


class SmtpEmailProvider(EmailProvider):
    name = "smtp"

    def __init__(
        self,
        *,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_email: str | None = None,
        use_tls: bool | None = None,
        use_ssl: bool | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.host = (host if host is not None else os.getenv("SMTP_HOST", "")).strip()
        self.port = int(port if port is not None else os.getenv("SMTP_PORT", "587"))
        self.username = (username if username is not None else os.getenv("SMTP_USERNAME", "")).strip()
        self.password = password if password is not None else os.getenv("SMTP_PASSWORD", "")
        self.from_email = (from_email if from_email is not None else os.getenv("EMAIL_FROM", "")).strip()
        self.use_tls = bool_int(os.getenv("SMTP_USE_TLS"), 1) == 1 if use_tls is None else use_tls
        self.use_ssl = bool_int(os.getenv("SMTP_USE_SSL"), 0) == 1 if use_ssl is None else use_ssl
        self.timeout_seconds = timeout_seconds

    def configured(self) -> bool:
        return bool(self.host and self.port and self.from_email)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "configured": self.configured(),
            "host_configured": bool(self.host),
            "port": self.port,
            "from_email_configured": bool(self.from_email),
            "username_configured": bool(self.username),
            "use_tls": self.use_tls,
            "use_ssl": self.use_ssl,
        }

    def send(self, message: EmailMessage) -> dict[str, Any]:
        if not self.configured():
            return {
                "provider": self.name,
                "status": "failed",
                "safe_error_detail": "SMTP_HOST, SMTP_PORT, and EMAIL_FROM must be configured.",
            }
        smtp_message = SmtpMessage()
        smtp_message["From"] = self.from_email
        smtp_message["To"] = message.to_email
        smtp_message["Subject"] = message.subject
        smtp_message.set_content(message.body)
        try:
            if self.use_ssl:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout_seconds, context=ssl.create_default_context()) as client:
                    self._login_if_configured(client)
                    client.send_message(smtp_message)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
                    if self.use_tls:
                        client.starttls(context=ssl.create_default_context())
                    self._login_if_configured(client)
                    client.send_message(smtp_message)
        except Exception as exc:
            return {
                "provider": self.name,
                "status": "failed",
                "safe_error_detail": f"{type(exc).__name__}: SMTP send failed.",
            }
        return {"provider": self.name, "status": "sent", "message_id": None}

    def _login_if_configured(self, client: smtplib.SMTP) -> None:
        if self.username and self.password:
            client.login(self.username, self.password)


def create_email_provider() -> EmailProvider:
    provider = os.getenv("EMAIL_PROVIDER", "console").strip().lower()
    if provider in {"", "console", "dry_run", "none"}:
        return ConsoleEmailProvider()
    if provider == "smtp":
        return SmtpEmailProvider()
    return ConsoleEmailProvider()


def notification_dedupe_key(member_uid: str, ticker: str, notification_type: str, evidence_identity: str) -> str:
    raw = "|".join([member_uid, ticker, notification_type, evidence_identity])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


EvidenceProvider = Callable[[str], dict[str, Any]]


class NotificationService:
    def __init__(
        self,
        repository: FlaskDataRepository,
        *,
        evidence_provider: EvidenceProvider,
        email_provider: EmailProvider | None = None,
    ) -> None:
        self.repository = repository
        self.evidence_provider = evidence_provider
        self.email_provider = email_provider or ConsoleEmailProvider()

    @staticmethod
    def _email_header(value: Any) -> str:
        return str(value or "").replace("\r", " ").replace("\n", " ").strip()

    @staticmethod
    def build_email(member: dict[str, Any], ticker: str, evidence: dict[str, Any], notification_type: str) -> EmailMessage:
        company = evidence.get("company_name") or ticker
        severity = evidence.get("overall_severity") or evidence.get("evidence_readiness") or evidence.get("status") or "unknown"
        subject = NotificationService._email_header(f"[FinTrust] {company} {notification_type} alert")
        lines = [f"{member.get('display_name') or member.get('email')}，您好：", f"{company} 目前有新的 {notification_type} 通知。", f"狀態：{severity}"]
        if notification_type == "material_event":
            lines.extend([
                f"事件日期：{evidence.get('event_date') or 'unknown'} {evidence.get('event_time') or ''}".strip(),
                f"官方主旨：{evidence.get('title') or 'unknown'}",
                f"來源：{evidence.get('source_name') or 'official source'}",
                f"官方連結：{evidence.get('official_url') or evidence.get('source_url') or 'unavailable'}",
            ])
        elif notification_type == "investor_conference":
            lines.extend([
                f"法說會日期：{evidence.get('conference_date') or 'unknown'}",
                f"標題：{evidence.get('title') or 'unknown'}",
                f"來源：{evidence.get('source_name') or 'official source'}",
                f"官方文件：{evidence.get('document_url') or evidence.get('official_url') or evidence.get('source_url') or 'unavailable'}",
            ])
        elif notification_type == "narrative_shift":
            lines.extend([
                f"比較期間：{evidence.get('baseline_period') or 'unknown'} → {evidence.get('current_period') or 'unknown'}",
                f"JSD / Cosine：{evidence.get('metric_summary') or 'see FinTrust detail'}",
                f"主要變化：{evidence.get('changed_topics') or evidence.get('changed_terms') or 'see FinTrust detail'}",
            ])
        else:
            lines.append(f"Run ID：{evidence.get('run_id') or evidence.get('evidence_identity') or 'unknown'}")
        lines.extend([
            f"FinTrust：{evidence.get('fintrust_url') or '/official.html'}",
            "請回到系統查看官方資料、規則結果與來源限制；此通知不構成投資建議。",
        ])
        return EmailMessage(
            to_email=NotificationService._email_header(member["email"]),
            subject=subject,
            body="\n".join(lines),
            notification_type=notification_type,
        )

    @staticmethod
    def classify_evidence(evidence: dict[str, Any], preferences: dict[str, Any]) -> tuple[str, str] | None:
        identity = str(evidence.get("run_id") or evidence.get("evidence_identity") or evidence.get("updated_at") or "")
        severity = str(evidence.get("overall_severity") or "").lower()
        if bool_int(preferences.get("important_alerts")) and severity in {"high", "critical"}:
            return "important_alert", identity or severity
        if bool_int(preferences.get("material_event_alerts")) and int(evidence.get("material_event_count") or 0) > 0:
            return "material_event", identity or str(evidence.get("material_event_count"))
        if bool_int(preferences.get("conference_alerts")) and int(evidence.get("conference_count") or 0) > 0:
            return "investor_conference", identity or str(evidence.get("conference_count"))
        if bool_int(preferences.get("narrative_shift_alerts")) and evidence.get("narrative_shift"):
            return "narrative_shift", identity or "narrative_shift"
        return None

    @staticmethod
    def _notification_items(evidence: dict[str, Any], preferences: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
        explicit_items = evidence.get("notification_items")
        if isinstance(explicit_items, list):
            output = []
            for item in explicit_items:
                if not isinstance(item, dict):
                    continue
                notification_type = str(item.get("notification_type") or "")
                evidence_identity = str(item.get("evidence_identity") or item.get("event_id") or item.get("run_id") or "")
                if notification_type and evidence_identity:
                    output.append((notification_type, evidence_identity, {**evidence, **item}))
            return output
        decision = NotificationService.classify_evidence(evidence, preferences)
        return [(decision[0], decision[1], evidence)] if decision else []

    @staticmethod
    def _preference_allows(notification_type: str, preferences: dict[str, Any], *, digest_frequency: str | None = None) -> bool:
        preference_key = {
            "important_alert": "important_alerts",
            "material_event": "material_event_alerts",
            "investor_conference": "conference_alerts",
            "narrative_shift": "narrative_shift_alerts",
        }.get(notification_type)
        if preference_key and not bool_int(preferences.get(preference_key)):
            return False
        if notification_type == "important_alert":
            return True
        member_digest = str(preferences.get("digest_frequency") or "daily").strip().lower()
        if member_digest == "off":
            return False
        if digest_frequency and member_digest != digest_frequency:
            return False
        return member_digest in {"daily", "weekly"}

    def process_member(self, member_uid: str, *, digest_frequency: str | None = None) -> list[dict[str, Any]]:
        member = self.repository.get_member(member_uid)
        if not member or member.get("account_status") != "active":
            return []
        preferences = self.repository.get_notification_preferences(member_uid)
        if not bool_int(preferences.get("email_enabled")):
            return []

        results: list[dict[str, Any]] = []
        for watch in self.repository.list_watchlist(member_uid):
            if not bool_int(watch.get("alert_enabled")):
                continue
            ticker = str(watch["ticker"])
            evidence = self.evidence_provider(ticker)
            for notification_type, evidence_identity, item in self._notification_items(evidence, preferences):
                if not self._preference_allows(notification_type, preferences, digest_frequency=digest_frequency):
                    continue
                dedupe_key = notification_dedupe_key(member_uid, ticker, notification_type, evidence_identity)
                now = utc_now_str()
                existing = self.repository.find_notification_by_dedupe_key(dedupe_key)
                if existing:
                    results.append(self.repository.append_notification_history({
                        "member_uid": member_uid,
                        "ticker": ticker,
                        "notification_type": notification_type,
                        "dedupe_key": f"{dedupe_key}:suppressed:{now}",
                        "subject": existing.get("subject", "Duplicate suppressed"),
                        "body": "Duplicate notification suppressed.",
                        "status": "suppressed_duplicate",
                        "provider_status": "suppressed_duplicate",
                        "created_at": now,
                        "metadata": {"original_dedupe_key": dedupe_key, "evidence_identity": evidence_identity},
                    }))
                    continue

                message = self.build_email(member, ticker, item, notification_type)
                provider_result = self.email_provider.send(message)
                status = "sent" if provider_result.get("status") in {"sent", "dry_run"} else "failed"
                results.append(self.repository.append_notification_history({
                    "member_uid": member_uid,
                    "ticker": ticker,
                    "notification_type": notification_type,
                    "dedupe_key": dedupe_key,
                    "subject": message.subject,
                    "body": message.body,
                    "status": status,
                    "provider_status": str(provider_result.get("status") or ""),
                    "safe_error_detail": provider_result.get("safe_error_detail"),
                    "created_at": now,
                    "sent_at": now if status == "sent" else None,
                    "metadata": {
                        "provider": provider_result.get("provider"),
                        "evidence_identity": evidence_identity,
                        "delivery_frequency": preferences.get("digest_frequency"),
                    },
                }))
        return results

    def process_all_members(self, limit: int = 500, *, digest_frequency: str | None = None) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for member in self.repository.list_members(limit=limit):
            output.extend(self.process_member(str(member["uid"]), digest_frequency=digest_frequency))
        return output
