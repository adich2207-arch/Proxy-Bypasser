import asyncio
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH, SESSION_NAME, BYPASSER_BOT_USERNAME
import logging
import time

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
        self.pending_requests = {}  # Maps timestamp -> (user_chat_id, callback)
        self.last_request_time = {}  # Maps user_chat_id -> timestamp
        self.response_timeout = 60  # seconds
        
    async def start(self):
        """Start the user client"""
        await self.client.start()
        logger.info("User client started successfully")
        
        # Set up message handler for bypasser bot responses
        @self.client.on(events.NewMessage(from_users=BYPASSER_BOT_USERNAME))
        async def handle_bypasser_response(event):
            """Handle responses from the bypasser bot"""
            logger.info(f"Received response from bypasser bot: {event.message.id}")
            logger.info(f"Response text: {event.message.text[:100] if event.message.text else 'Media message'}")
            
            # Find the most recent pending request (FIFO approach)
            if self.pending_requests:
                # Get the oldest pending request
                oldest_timestamp = min(self.pending_requests.keys())
                user_chat_id, callback = self.pending_requests[oldest_timestamp]
                
                logger.info(f"Matching response to user {user_chat_id}")
                
                try:
                    # Call the callback with the response
                    await callback(event.message)
                    logger.info(f"Successfully sent response to user {user_chat_id}")
                except Exception as e:
                    logger.error(f"Error in callback: {e}")
                
                # Clean up
                del self.pending_requests[oldest_timestamp]
                if user_chat_id in self.last_request_time:
                    del self.last_request_time[user_chat_id]
            else:
                logger.warning("Received response but no pending requests found")
    
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
            # Clean up old expired requests
            current_time = time.time()
            expired = [ts for ts, (uid, _) in self.pending_requests.items() 
                      if current_time - ts > self.response_timeout]
            for ts in expired:
                logger.warning(f"Request timed out for timestamp {ts}")
                del self.pending_requests[ts]
            
            # Send message to bypasser bot
            message = await self.client.send_message(BYPASSER_BOT_USERNAME, link)
            logger.info(f"Sent link to bypasser bot: {link} (message_id: {message.id})")
            
            # Register the request with current timestamp
            timestamp = time.time()
            self.pending_requests[timestamp] = (user_chat_id, response_callback)
            self.last_request_time[user_chat_id] = timestamp
            
            logger.info(f"Registered request for user {user_chat_id} at timestamp {timestamp}")
            logger.info(f"Total pending requests: {len(self.pending_requests)}")
            
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
