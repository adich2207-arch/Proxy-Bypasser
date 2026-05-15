import asyncio
import logging
import os
import signal

from aiohttp import web
from telegram import Update, ReplyKeyboardRemove
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

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
PHONE_NUMBER, OTP_CODE, PASSWORD = range(3)

# Temporary login sessions
login_sessions = {}

# Render injects PORT; default 8080
PORT = int(os.environ.get('PORT', 8080))


# ---------------------------------------------------------------------------
# Health-check server — required so Render marks deploy as "live"
# ---------------------------------------------------------------------------

async def health_handler(request):
    return web.Response(text="OK", status=200)


async def start_health_server():
    app = web.Application()
    app.router.add_get('/', health_handler)
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Health server listening on port {PORT}")
    return runner


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
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
        "/test - Test connection to bypasser bot\n"
        "/debug - Show debug information\n"
        "/help - Show this help message\n\n"
        f"*Bypasser Bot:* @{BYPASSER_BOT_USERNAME}",
        parse_mode='Markdown'
    )


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        await update.message.reply_text("❌ Not logged in. Use /login first.")
        return

    await update.message.reply_text("🧪 Testing connection to bypasser bot...")
    try:
        test_msg = await user_client.client.send_message(BYPASSER_BOT_USERNAME, "test")
        await update.message.reply_text(
            f"✅ Test message sent! Message ID: {test_msg.id}\n\n"
            f"Check if bypasser bot responds."
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        await update.message.reply_text("❌ Not logged in. Use /login first.")
        return

    await update.message.reply_text(
        f"🔍 *Debug Information*\n\n"
        f"Logged in: ✅ Yes\n"
        f"Bypasser bot: @{BYPASSER_BOT_USERNAME}\n"
        f"Bypasser bot ID: {user_client.bypasser_bot_id or '❌ Not found'}\n"
        f"Pending requests: {len(user_client.pending_requests)}\n"
        f"Timeout: {user_client.response_timeout}s",
        parse_mode='Markdown'
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_logged_in = await user_client.is_logged_in()

    if is_logged_in:
        user_info = await user_client.get_me()
        await update.message.reply_text(
            f"✅ *Status: Connected*\n\n"
            f"👤 Account: {user_info.first_name}\n"
            f"📱 Phone: {user_info.phone}\n"
            f"🤖 Bypasser: @{BYPASSER_BOT_USERNAME}\n"
            f"⏳ Pending requests: {len(user_client.pending_requests)}\n\n"
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
    if await user_client.is_logged_in():
        await update.message.reply_text("✅ Already logged in! Use /status to see details.")
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
    phone_number = update.message.text.strip()

    if not phone_number.startswith('+'):
        await update.message.reply_text(
            "❌ Please include country code with + sign.\nExample: +1234567890"
        )
        return PHONE_NUMBER

    try:
        await update.message.reply_text("📤 Sending verification code...")
        phone_code_hash = await user_client.login_with_phone(phone_number)
        login_sessions[update.effective_user.id] = {
            'phone_number': phone_number,
            'phone_code_hash': phone_code_hash
        }
        await update.message.reply_text(
            "✅ Verification code sent!\n\nPlease enter the code you received.\n\nSend /cancel to abort."
        )
        return OTP_CODE
    except Exception as e:
        logger.error(f"Error in receive_phone: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}\n\nPlease try again with /login")
        return ConversationHandler.END


async def receive_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user_id = update.effective_user.id

    if user_id not in login_sessions:
        await update.message.reply_text("❌ Session expired. Please start again with /login")
        return ConversationHandler.END

    session = login_sessions[user_id]

    try:
        await update.message.reply_text("🔄 Verifying code...")
        await user_client.verify_code(session['phone_number'], code, session['phone_code_hash'])
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
                "🔐 Two-factor authentication is enabled.\n\nPlease send your 2FA password.\n\nSend /cancel to abort."
            )
            return PASSWORD
        else:
            logger.error(f"Error in receive_otp: {e}")
            await update.message.reply_text(f"❌ Verification failed: {error_msg}\n\nPlease try again with /login")
            login_sessions.pop(user_id, None)
            return ConversationHandler.END


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    user_id = update.effective_user.id

    try:
        await update.message.delete()
    except Exception:
        pass

    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Verifying password...")
        await user_client.verify_password(password)
        login_sessions.pop(user_id, None)

        user_info = await user_client.get_me()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ *Login Successful!*\n\n👤 Logged in as: {user_info.first_name}\n\nYou can now send shortener links to bypass!",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in receive_password: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Authentication failed: {str(e)}\n\nPlease try again with /login"
        )
        login_sessions.pop(user_id, None)
        return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_sessions.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Login cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        await update.message.reply_text(
            "❌ Bot is not connected to any account.\n\nPlease use /login first."
        )
        return

    link = update.message.text.strip()

    if not (link.startswith('http://') or link.startswith('https://')):
        await update.message.reply_text("❌ Please send a valid URL starting with http:// or https://")
        return

    processing_msg = await update.message.reply_text(
        f"⏳ Processing your link...\nSending to @{BYPASSER_BOT_USERNAME}\n\n⏱️ Waiting for response..."
    )

    response_received = {'status': False}

    async def handle_response(message):
        try:
            response_received['status'] = True
            try:
                await processing_msg.delete()
            except Exception:
                pass

            if message.text:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"✅ *Bypassed Content:*\n\n{message.text}",
                    parse_mode='Markdown',
                    reply_to_message_id=update.message.message_id
                )
            elif message.media or message.document:
                await message.forward_to(update.effective_chat.id)
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ Content bypassed!",
                    reply_to_message_id=update.message.message_id
                )
        except Exception as e:
            logger.error(f"Error in handle_response: {e}", exc_info=True)
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Error processing response: {str(e)}"
                )
            except Exception:
                pass

    try:
        await user_client.send_to_bypasser(
            link, update.effective_chat.id, update.message.message_id, handle_response
        )
        await asyncio.sleep(30)

        if not response_received['status']:
            try:
                await processing_msg.edit_text(
                    "⏳ Still waiting for response from bypasser bot...\nThis may take a moment."
                )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error sending to bypasser: {e}", exc_info=True)
        try:
            await processing_msg.edit_text(f"❌ Error: {str(e)}\n\nPlease try again.")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def post_init(application: Application):
    try:
        if await user_client.is_logged_in():
            await user_client.start()
            logger.info("User client initialized and logged in")
        else:
            logger.warning("User client not logged in — use /login after deploy")
    except Exception as e:
        logger.error(f"Error initializing user client: {e}")


async def post_shutdown(application: Application):
    try:
        await user_client.stop()
    except Exception as e:
        logger.error(f"Error stopping user client: {e}")


# ---------------------------------------------------------------------------
# Main — runs health server + bot together, handles SIGTERM cleanly
# ---------------------------------------------------------------------------

def main():
    validate_config()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    login_conv = ConversationHandler(
        entry_points=[CommandHandler('login', login_start)],
        states={
            PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)],
            OTP_CODE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp)],
            PASSWORD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel_login)],
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('status', status_command))
    application.add_handler(CommandHandler('test', test_command))
    application.add_handler(CommandHandler('debug', debug_command))
    application.add_handler(login_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    async def run():
        # Start health-check server first — Render checks this port to confirm deploy
        health_runner = await start_health_server()

        # Set up graceful shutdown on SIGTERM (Render sends this to stop the service)
        stop_event = asyncio.Event()

        def _handle_signal():
            logger.info("Received shutdown signal")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler for all signals
                pass

        try:
            async with application:
                await application.initialize()
                await application.start()
                await application.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True
                )
                logger.info("✅ Bot is running")
                # Wait here until a shutdown signal arrives
                await stop_event.wait()
        finally:
            logger.info("Shutting down...")
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            await health_runner.cleanup()
            logger.info("Shutdown complete")

    asyncio.run(run())


if __name__ == '__main__':
    main()
