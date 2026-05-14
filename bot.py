import asyncio
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from user_client import user_client
from config import BOT_TOKEN, validate_config, BYPASSER_BOT_USERNAME

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
PHONE_NUMBER, OTP_CODE, PASSWORD = range(3)

# Store login sessions temporarily
login_sessions = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    
    # Check if user client is logged in
    is_logged_in = await user_client.is_logged_in()
    
    if is_logged_in:
        user_info = await user_client.get_me()
        await update.message.reply_text(
            f"👋 Welcome {user.mention_html()}!\n\n"
            f"✅ Bot is connected to account: {user_info.first_name}\n\n"
            f"📎 Send me any shortener link and I'll bypass it for you!\n\n"
            f"Commands:\n"
            f"/start - Show this message\n"
            f"/login - Login with your Telegram account\n"
            f"/status - Check connection status\n"
            f"/help - Show help message",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"👋 Welcome {user.mention_html()}!\n\n"
            f"⚠️ Bot is not connected to any Telegram account.\n\n"
            f"Please use /login to connect your account first.\n\n"
            f"This is required to communicate with the bypasser bot (@{BYPASSER_BOT_USERNAME})",
            parse_mode='HTML'
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "1️⃣ First, login with your Telegram account using /login\n"
        "2️⃣ Send any shortener link to the bot\n"
        "3️⃣ The bot will forward it to the bypasser bot via your account\n"
        "4️⃣ You'll receive the bypassed content\n\n"
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/login - Login with your Telegram account\n"
        "/status - Check connection status\n"
        "/help - Show this help message\n\n"
        f"*Bypasser Bot:* @{BYPASSER_BOT_USERNAME}",
        parse_mode='Markdown'
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    is_logged_in = await user_client.is_logged_in()
    
    if is_logged_in:
        user_info = await user_client.get_me()
        pending_count = len(user_client.pending_requests)
        await update.message.reply_text(
            f"✅ *Status: Connected*\n\n"
            f"👤 Account: {user_info.first_name}\n"
            f"📱 Phone: {user_info.phone}\n"
            f"🤖 Bypasser: @{BYPASSER_BOT_USERNAME}\n"
            f"⏳ Pending requests: {pending_count}\n\n"
            f"Ready to bypass links!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *Status: Not Connected*\n\n"
            "Please use /login to connect your Telegram account.",
            parse_mode='Markdown'
        )


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the login conversation"""
    is_logged_in = await user_client.is_logged_in()
    
    if is_logged_in:
        await update.message.reply_text(
            "✅ You are already logged in!\n\n"
            "Use /status to see connection details."
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🔐 *Login Process*\n\n"
        "Please send your phone number with country code.\n"
        "Example: +1234567890\n\n"
        "Send /cancel to abort.",
        parse_mode='Markdown'
    )
    return PHONE_NUMBER


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive phone number and send OTP"""
    phone_number = update.message.text.strip()
    
    if not phone_number.startswith('+'):
        await update.message.reply_text(
            "❌ Please include country code with + sign.\n"
            "Example: +1234567890"
        )
        return PHONE_NUMBER
    
    try:
        await update.message.reply_text("📤 Sending verification code...")
        
        phone_code_hash = await user_client.login_with_phone(phone_number)
        
        # Store session data
        login_sessions[update.effective_user.id] = {
            'phone_number': phone_number,
            'phone_code_hash': phone_code_hash
        }
        
        await update.message.reply_text(
            "✅ Verification code sent!\n\n"
            "Please enter the code you received.\n\n"
            "Send /cancel to abort."
        )
        return OTP_CODE
        
    except Exception as e:
        logger.error(f"Error in receive_phone: {e}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}\n\n"
            "Please try again with /login"
        )
        return ConversationHandler.END


async def receive_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and verify OTP code"""
    code = update.message.text.strip()
    user_id = update.effective_user.id
    
    if user_id not in login_sessions:
        await update.message.reply_text(
            "❌ Session expired. Please start again with /login"
        )
        return ConversationHandler.END
    
    session = login_sessions[user_id]
    
    try:
        await update.message.reply_text("🔄 Verifying code...")
        
        await user_client.verify_code(
            session['phone_number'],
            code,
            session['phone_code_hash']
        )
        
        # Clean up session
        del login_sessions[user_id]
        
        user_info = await user_client.get_me()
        await update.message.reply_text(
            f"✅ *Login Successful!*\n\n"
            f"👤 Logged in as: {user_info.first_name}\n\n"
            f"You can now send shortener links to bypass!",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
        
    except Exception as e:
        error_msg = str(e)
        
        if "2FA_REQUIRED" in error_msg:
            await update.message.reply_text(
                "🔐 Two-factor authentication is enabled.\n\n"
                "Please send your 2FA password.\n\n"
                "Send /cancel to abort."
            )
            return PASSWORD
        else:
            logger.error(f"Error in receive_otp: {e}")
            await update.message.reply_text(
                f"❌ Verification failed: {error_msg}\n\n"
                "Please try again with /login"
            )
            # Clean up session
            if user_id in login_sessions:
                del login_sessions[user_id]
            return ConversationHandler.END


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and verify 2FA password"""
    password = update.message.text
    user_id = update.effective_user.id
    
    # Delete the password message for security
    await update.message.delete()
    
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔄 Verifying password..."
        )
        
        await user_client.verify_password(password)
        
        # Clean up session
        if user_id in login_sessions:
            del login_sessions[user_id]
        
        user_info = await user_client.get_me()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ *Login Successful!*\n\n"
                 f"👤 Logged in as: {user_info.first_name}\n\n"
                 f"You can now send shortener links to bypass!",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in receive_password: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Authentication failed: {str(e)}\n\n"
                 "Please try again with /login"
        )
        # Clean up session
        if user_id in login_sessions:
            del login_sessions[user_id]
        return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the login process"""
    user_id = update.effective_user.id
    if user_id in login_sessions:
        del login_sessions[user_id]
    
    await update.message.reply_text(
        "❌ Login cancelled.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle shortener links sent by users"""
    # Check if logged in
    is_logged_in = await user_client.is_logged_in()
    
    if not is_logged_in:
        await update.message.reply_text(
            "❌ Bot is not connected to any account.\n\n"
            "Please use /login first to connect your Telegram account."
        )
        return
    
    link = update.message.text.strip()
    
    # Basic URL validation
    if not (link.startswith('http://') or link.startswith('https://')):
        await update.message.reply_text(
            "❌ Please send a valid URL starting with http:// or https://"
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text(
        "⏳ Processing your link...\n"
        f"Sending to @{BYPASSER_BOT_USERNAME}\n\n"
        "⏱️ Waiting for response..."
    )
    
    # Track if response was received
    response_received = {'status': False}
    
    # Define callback for when bypasser responds
    async def handle_response(message):
        """Handle response from bypasser bot"""
        try:
            response_received['status'] = True
            logger.info(f"Processing response for user {update.effective_chat.id}")
            
            # Delete processing message
            try:
                await processing_msg.delete()
            except Exception as e:
                logger.warning(f"Could not delete processing message: {e}")
            
            # Forward the response to user
            if message.text:
                # Send text response
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ *Bypassed Content:*\n\n{message.text}",
                    parse_mode='Markdown',
                    reply_to_message_id=update.message.message_id
                )
                logger.info(f"Sent text response to user {update.effective_chat.id}")
            elif message.media:
                # Forward media messages
                await message.forward_to(update.effective_chat.id)
                logger.info(f"Forwarded media to user {update.effective_chat.id}")
            elif message.document:
                # Forward documents
                await message.forward_to(update.effective_chat.id)
                logger.info(f"Forwarded document to user {update.effective_chat.id}")
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ Content bypassed! (Check above)",
                    reply_to_message_id=update.message.message_id
                )
                
        except Exception as e:
            logger.error(f"Error handling response: {e}", exc_info=True)
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Error processing response: {str(e)}",
                    reply_to_message_id=update.message.message_id
                )
            except:
                pass
    
    # Send to bypasser bot
    try:
        await user_client.send_to_bypasser(
            link,
            update.effective_chat.id,
            update.message.message_id,
            handle_response
        )
        logger.info(f"Link sent to bypasser for user {update.effective_chat.id}")
        
        # Wait a bit and check if response was received
        await asyncio.sleep(30)  # Wait 30 seconds
        
        if not response_received['status']:
            try:
                await processing_msg.edit_text(
                    "⏳ Still waiting for response from bypasser bot...\n"
                    "This may take a moment."
                )
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error sending to bypasser: {e}", exc_info=True)
        try:
            await processing_msg.edit_text(
                f"❌ Error: {str(e)}\n\n"
                "Please try again or contact support."
            )
        except:
            pass


async def post_init(application: Application):
    """Initialize user client after bot starts"""
    try:
        await user_client.start()
        logger.info("User client initialized")
    except Exception as e:
        logger.error(f"Error initializing user client: {e}")


async def post_shutdown(application: Application):
    """Cleanup when bot stops"""
    try:
        await user_client.stop()
        logger.info("User client stopped")
    except Exception as e:
        logger.error(f"Error stopping user client: {e}")


def main():
    """Start the bot"""
    try:
        # Validate configuration
        validate_config()
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
        
        # Login conversation handler
        login_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('login', login_start)],
            states={
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)],
                OTP_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
            },
            fallbacks=[CommandHandler('cancel', cancel_login)],
        )
        
        # Add handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('status', status_command))
        application.add_handler(login_conv_handler)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
        
        # Start bot
        logger.info("Starting bot on Render...")
        logger.info("Bot is running and ready to receive messages")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise


if __name__ == '__main__':
    main()
