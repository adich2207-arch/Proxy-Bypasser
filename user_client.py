import logging
import os
import time

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

from config import API_ID, API_HASH, SESSION_NAME, BYPASSER_BOT_USERNAME

logger = logging.getLogger(__name__)


class UserClient:
    """Manages the user's Telegram client for interacting with bypasser bot"""

    def __init__(self):
        # Build the session object — no network calls here, just object creation
        string_session = os.environ.get('STRING_SESSION', '').strip()
        if string_session:
            logger.info("Using STRING_SESSION from environment variable")
            session = StringSession(string_session)
        else:
            logger.warning(
                "STRING_SESSION not set — using file-based session. "
                "This will NOT persist across Render redeploys."
            )
            session = SESSION_NAME

        # TelegramClient creation is safe here — it does NOT connect yet
        self.client = TelegramClient(session, API_ID, API_HASH)
        self.pending_requests = {}   # timestamp -> (user_chat_id, callback)
        self.last_request_time = {}  # user_chat_id -> timestamp
        self.response_timeout = 60   # seconds
        self.bypasser_bot_id = None
        self._handler_registered = False

    async def start(self):
        """Connect, verify auth, resolve bypasser entity, register event handler"""
        if not self.client.is_connected():
            await self.client.connect()

        if not await self.client.is_user_authorized():
            logger.warning("User client not authorized — waiting for /login")
            return False

        logger.info("User client started successfully")
        self._log_session_string()

        try:
            entity = await self.client.get_entity(BYPASSER_BOT_USERNAME)
            self.bypasser_bot_id = entity.id
            logger.info(f"Found bypasser bot: {entity.id} (@{entity.username})")
        except Exception as e:
            logger.error(f"Could not find bypasser bot @{BYPASSER_BOT_USERNAME}: {e}")

        self._register_event_handler()
        return True

    def _log_session_string(self):
        """Print session string to logs — copy it into STRING_SESSION env var on Render"""
        try:
            session_string = self.client.session.save()
            if session_string:
                logger.info("=" * 60)
                logger.info("COPY THIS → set as STRING_SESSION env var on Render so session survives redeploys:")
                logger.info(session_string)
                logger.info("=" * 60)
        except Exception as e:
            logger.warning(f"Could not export session string: {e}")

    def _register_event_handler(self):
        """Register Telethon event handler (idempotent — only registers once)"""
        if self._handler_registered:
            logger.info("Event handler already registered, skipping")
            return

        logger.info("Registering event handler for bypasser bot responses")

        @self.client.on(events.NewMessage(incoming=True))
        async def handle_bypasser_response(event):
            try:
                sender = await event.get_sender()
                sender_username = getattr(sender, 'username', None)
                logger.info(f"📨 Incoming message from {sender_username or sender.id}")

                target = BYPASSER_BOT_USERNAME.lower().lstrip('@')
                if sender_username and sender_username.lower() == target:
                    logger.info("✅ Message is from bypasser bot")

                    if self.pending_requests:
                        oldest_ts = min(self.pending_requests.keys())
                        user_chat_id, callback = self.pending_requests[oldest_ts]
                        logger.info(f"Dispatching response to user {user_chat_id}")
                        try:
                            await callback(event.message)
                            logger.info(f"✅ Callback executed for user {user_chat_id}")
                        except Exception as e:
                            logger.error(f"❌ Callback error: {e}", exc_info=True)
                        self.pending_requests.pop(oldest_ts, None)
                        self.last_request_time.pop(user_chat_id, None)
                    else:
                        logger.warning("⚠️ Response received but no pending requests")
                else:
                    logger.debug(f"Ignoring message from {sender_username or sender.id}")
            except Exception as e:
                logger.error(f"Error in event handler: {e}", exc_info=True)

        self._handler_registered = True
        logger.info("✅ Event handler registered")

    async def login_with_phone(self, phone_number):
        """Send OTP to phone number, return phone_code_hash"""
        if not self.client.is_connected():
            await self.client.connect()
        result = await self.client.send_code_request(phone_number)
        logger.info(f"OTP sent to {phone_number}")
        return result.phone_code_hash

    async def verify_code(self, phone_number, code, phone_code_hash):
        """Verify OTP code"""
        try:
            await self.client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
            logger.info("Signed in successfully")
            self._log_session_string()
            self._register_event_handler()
            return True
        except SessionPasswordNeededError:
            raise Exception("2FA_REQUIRED")

    async def verify_password(self, password):
        """Verify 2FA password"""
        await self.client.sign_in(password=password)
        logger.info("Signed in with 2FA successfully")
        self._log_session_string()
        self._register_event_handler()
        return True

    async def is_logged_in(self):
        """Return True if the user session is authorized"""
        try:
            if not self.client.is_connected():
                await self.client.connect()
            return await self.client.is_user_authorized()
        except Exception as e:
            logger.error(f"Error checking login status: {e}")
            return False

    async def send_to_bypasser(self, link, user_chat_id, original_msg_id, response_callback):
        """Forward a link to the bypasser bot and register the response callback"""
        # Clean up expired requests
        now = time.time()
        expired = [ts for ts in list(self.pending_requests)
                   if now - ts > self.response_timeout]
        for ts in expired:
            logger.warning(f"Request timed out (ts={ts})")
            del self.pending_requests[ts]

        message = await self.client.send_message(BYPASSER_BOT_USERNAME, link)
        logger.info(f"Sent link to bypasser (msg_id={message.id}): {link}")

        ts = time.time()
        self.pending_requests[ts] = (user_chat_id, response_callback)
        self.last_request_time[user_chat_id] = ts
        logger.info(f"Total pending requests: {len(self.pending_requests)}")
        return True

    async def get_me(self):
        """Return the logged-in user's info"""
        try:
            return await self.client.get_me()
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return None

    async def stop(self):
        """Disconnect the Telethon client"""
        try:
            if self.client.is_connected():
                await self.client.disconnect()
        except Exception:
            pass
        logger.info("User client stopped")


# Global singleton — safe to create at import time (no network calls in __init__)
user_client = UserClient()
