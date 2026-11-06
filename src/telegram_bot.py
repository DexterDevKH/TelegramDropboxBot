"""
Telethon MTProto Client Wrapper & Resilient Operations
"""

import logging
from typing import Optional, Any
from telethon import TelegramClient
from telethon.sessions import MemorySession
from telethon.errors import MessageNotModifiedError, FloodWaitError

from src.config import AppConfig

logger = logging.getLogger("SyncEngine.Telegram")

class TelegramService:
    """Encapsulates Telethon client lifecycle and resilient messaging."""

    def __init__(self, config: AppConfig):
        self.config = config
        # Use MemorySession in ephemeral CI runners to avoid sqlite locking & unwanted file artifacts
        session = MemorySession() if config.is_github_actions else "bot_session"
        self.client = TelegramClient(session, config.telegram_api_id, config.telegram_api_hash)
        self.bot_username: str = "Unknown"

    async def start(self) -> str:
        """Starts the Telethon client with bot token authentication."""
        await self.client.start(bot_token=self.config.telegram_bot_token)
        me = await self.client.get_me()
        self.bot_username = me.username or "Bot"
        return self.bot_username

    async def disconnect(self) -> None:
        """Gracefully disconnects Telethon client."""
        if self.client.is_connected():
            await self.client.disconnect()

    async def safe_edit_message(
        self,
        target: Any,
        text: str,
        buttons: Any = None,
        link_preview: bool = False,
        message_id: Optional[int] = None,
    ) -> bool:
        """Safely edits message with automatic error suppression for unchanged text or rate limits."""
        try:
            if isinstance(target, (int, str)) and message_id:
                await self.client.edit_message(
                    target, message_id, text=text, buttons=buttons, link_preview=link_preview
                )
            elif hasattr(target, "edit"):
                await target.edit(text, buttons=buttons, link_preview=link_preview)
            elif hasattr(target, "chat_id") and hasattr(target, "id"):
                await self.client.edit_message(
                    target.chat_id, target.id, text=text, buttons=buttons, link_preview=link_preview
                )
            return True
        except MessageNotModifiedError:
            return True
        except FloodWaitError as e:
            logger.warning(f"Telegram FloodWait hit ({e.seconds}s) during message edit.")
            return False
        except Exception as exc:
            logger.debug(f"Non-critical message edit error: {exc}")
            return False

