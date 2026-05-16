import os
from dotenv import load_dotenv

load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Telegram API Configuration
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH')

# Bypasser Bot Configuration
BYPASSER_BOT_USERNAME = os.getenv('BYPASSER_BOT_USERNAME')

# Session Configuration
SESSION_NAME = os.getenv('SESSION_NAME', 'user_session')

# Admin Configuration — set your Telegram user ID in Render env vars
_admin_id = os.getenv('ADMIN_ID')
ADMIN_ID = int(_admin_id) if _admin_id else None


def validate_config():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is required")
    if not API_ID or API_ID == 0:
        raise ValueError("API_ID is required")
    if not API_HASH:
        raise ValueError("API_HASH is required")
    if not BYPASSER_BOT_USERNAME:
        raise ValueError("BYPASSER_BOT_USERNAME is required")
    if not ADMIN_ID:
        print("WARNING: ADMIN_ID not set — /admin and /users commands will be disabled")
    return True
