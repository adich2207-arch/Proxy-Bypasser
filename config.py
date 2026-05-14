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

# Validate required configuration
def validate_config():
    """Validate that all required configuration is present"""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is required in .env file")
    if not API_ID or API_ID == 0:
        raise ValueError("API_ID is required in .env file")
    if not API_HASH:
        raise ValueError("API_HASH is required in .env file")
    if not BYPASSER_BOT_USERNAME:
        raise ValueError("BYPASSER_BOT_USERNAME is required in .env file")
    return True
