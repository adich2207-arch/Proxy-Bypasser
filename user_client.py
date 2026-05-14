import asyncio
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH, SESSION_NAME, BYPASSER_BOT_USERNAME
import logging

logger = logging.getLogger(__name__)


class UserClient:
    """Manages the user's Telegram client for interacting with bypasser bot"""
    
    def __init__(self):
        # Create event loop if it doesn't exist (fixes Python 3.10+ compatibility)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        self.pending_requests = {}  # Maps message_id -> (user_chat_id, original_message_id)
        self.response_handlers = {}  # Maps user_chat_id -> callback function
        
    async def start(self):
        """Start the user client"""
        await self.client.start()
        logger.info("User client started successfully")
        
        # Set up message handler for bypasser bot responses
        @self.client.on(events.NewMessage(from_users=BYPASSER_BOT_USERNAME))
        async def handle_bypasser_response(event):
            """Handle responses from the bypasser bot"""
            logger.info(f"Received response from bypasser bot: {event.message.id}")
            
            # Find the corresponding user request
            for msg_id, (user_chat_id, original_msg_id) in list(self.pending_requests.items()):
                # Check if this response is for this request (simple approach)
                # In production, you might need more sophisticated matching
                if user_chat_id in self.response_handlers:
                    callback = self.response_handlers[user_chat_id]
                    await callback(event.message)
                    
                    # Clean up
                    del self.pending_requests[msg_id]
                    if user_chat_id in self.response_handlers:
                        del self.response_handlers[user_chat_id]
                    break
    
    async def login_with_phone(self, phone_number):
        """
        Initiate login process with phone number
        Returns: phone_code_hash needed for verification
        """
        try:
            await self.client.connect()
            result = await self.client.send_code_request(phone_number)
            logger.info(f"Code sent to {phone_number}")
            return result.phone_code_hash
        except Exception as e:
            logger.error(f"Error sending code: {e}")
            raise
    
    async def verify_code(self, phone_number, code, phone_code_hash):
        """
        Verify the OTP code
        Returns: True if successful, raises exception otherwise
        """
        try:
            await self.client.sign_in(phone_number, code, phone_code_hash=phone_code_hash)
            logger.info("Successfully logged in")
            return True
        except SessionPasswordNeededError:
            # 2FA is enabled
            raise Exception("2FA_REQUIRED")
        except Exception as e:
            logger.error(f"Error verifying code: {e}")
            raise
    
    async def verify_password(self, password):
        """Verify 2FA password if required"""
        try:
            await self.client.sign_in(password=password)
            logger.info("Successfully logged in with 2FA")
            return True
        except Exception as e:
            logger.error(f"Error verifying password: {e}")
            raise
    
    async def is_logged_in(self):
        """Check if user is already logged in"""
        try:
            await self.client.connect()
            return await self.client.is_user_authorized()
        except Exception as e:
            logger.error(f"Error checking login status: {e}")
            return False
    
    async def send_to_bypasser(self, link, user_chat_id, original_msg_id, response_callback):
        """
        Send link to bypasser bot and register callback for response
        
        Args:
            link: The shortener link to bypass
            user_chat_id: The chat ID of the user who sent the request
            original_msg_id: The message ID of the user's request
            response_callback: Async function to call when response is received
        """
        try:
            # Send message to bypasser bot
            message = await self.client.send_message(BYPASSER_BOT_USERNAME, link)
            logger.info(f"Sent link to bypasser bot: {link}")
            
            # Register the request
            self.pending_requests[message.id] = (user_chat_id, original_msg_id)
            self.response_handlers[user_chat_id] = response_callback
            
            return True
        except Exception as e:
            logger.error(f"Error sending to bypasser bot: {e}")
            raise
    
    async def get_me(self):
        """Get information about the logged-in user"""
        try:
            return await self.client.get_me()
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return None
    
    async def stop(self):
        """Stop the user client"""
        await self.client.disconnect()
        logger.info("User client stopped")


# Global instance
user_client = UserClient()
