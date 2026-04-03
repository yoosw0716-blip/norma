from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _list_env(name: str) -> tuple[str, ...]:
    value = os.getenv(name, "")
    items = [item.strip() for item in value.split(",") if item.strip()]
    return tuple(items)


@dataclass(frozen=True)
class Settings:
    slack_bot_token: str
    slack_app_token: str
    gemini_api_key: str
    vertex_api_key: str
    vertex_project_id: str
    vertex_location: str
    openclaw_base_url: str
    openclaw_api_key: str
    openclaw_model: str
    pdf_root: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    max_completion_tokens: int
    allow_direct_messages: bool
    allow_channel_mentions: bool
    allowed_channel_ids: tuple[str, ...]
    channel_disabled_message: str
    quantum_notice_db_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_app_token=os.getenv("SLACK_APP_TOKEN", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            vertex_api_key=os.getenv("VERTEX_API_KEY", ""),
            vertex_project_id=os.getenv("VERTEX_PROJECT_ID", ""),
            vertex_location=os.getenv("VERTEX_LOCATION", "asia-northeast3"),
            openclaw_base_url=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
            openclaw_api_key=os.getenv("OPENCLAW_API_KEY", ""),
            openclaw_model=os.getenv("OPENCLAW_MODEL", "qwen3:14b"),
            pdf_root=os.getenv("PDF_ROOT", "./data/pdfs"),
            chunk_size=_int_env("CHUNK_SIZE", 1200),
            chunk_overlap=_int_env("CHUNK_OVERLAP", 200),
            top_k=_int_env("TOP_K", 5),
            max_completion_tokens=_int_env("MAX_COMPLETION_TOKENS", 900),
            allow_direct_messages=_bool_env("ALLOW_DIRECT_MESSAGES", False),
            allow_channel_mentions=_bool_env("ALLOW_CHANNEL_MENTIONS", True),
            allowed_channel_ids=_list_env("ALLOWED_CHANNEL_IDS"),
            channel_disabled_message=os.getenv(
                "CHANNEL_DISABLED_MESSAGE",
                "이 채널에서는 회사 규정에 대해 답변할 수 없습니다. 회사 규정 문의는 봇 DM으로 보내주세요.",
            ),
            quantum_notice_db_path=os.getenv(
                "QUANTUM_NOTICE_DB_PATH",
                "/home/norma/quantum_notice_app/data/quantum_notices.db",
            ),
        )

    def validate(self) -> None:
        missing = []
        if not self.slack_bot_token:
            missing.append("SLACK_BOT_TOKEN")
        if not self.slack_app_token:
            missing.append("SLACK_APP_TOKEN")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")
