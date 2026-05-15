import asyncio
import logging
import os
import signal

from aiohttp import web
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

# Auto-delete delay in seconds (10 minutes)
AUTO_DELETE_DELAY = 10 * 60

# Developer username
DEVELOPER_USERNAME = "Mr_1X8"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def auto_delete(bot, chat_id, message_id, delay=AUTO_DELETE_DELAY):
    """Delete a message after `delay` seconds — silently ignores errors."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def schedule_delete(bot, chat_id, message_id, delay=AUTO_DELETE_DELAY):
    """Fire-and-forget auto-delete task."""
    asyncio.create_task(auto_delete(bot, chat_id, message_id, delay))


def clean_bypasser_response(text: str) -> str:
    """
    Extract only the bypassed link from the bypasser bot response
    and present it cleanly — no mention of the original bot.
    """
    import re

    bypassed_url = None

    # Look for "Bypassed Link:" line and grab the URL from it
    match = re.search(r'Bypassed Link[:\s]*✅?\s*(https?://\S+)', text, re.IGNORECASE)
    if match:
        bypassed_url = match.group(1).strip()

    # Fallback: grab the second URL in the message (first = original, second = bypassed)
    if not bypassed_url:
        urls = re.findall(r'https?://\S+', text)
        if len(urls) >= 2:
            bypassed_url = urls[1]
        elif len(urls) == 1:
            bypassed_url = urls[0]

    if bypassed_url:
        return (
            "✅ 𝗕𝘆𝗽𝗮𝘀𝘀𝗲𝗱 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆!\n\n"
            f"🔗 𝗗𝗶𝗿𝗲𝗰𝘁 𝗟𝗶𝗻𝗸:\n{bypassed_url}\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🗑 𝗧𝗵𝗶𝘀 𝗺𝗲𝘀𝘀𝗮𝗴𝗲 𝘄𝗶𝗹𝗹 𝗯𝗲 𝗱𝗲𝗹𝗲𝘁𝗲𝗱 𝗮𝘂𝘁𝗼𝗺𝗮𝘁𝗶𝗰𝗮𝗹𝗹𝘆."
        )

    # If we couldn't extract a URL, return a generic success message
    return "✅ 𝗕𝘆𝗽𝗮𝘀𝘀𝗲𝗱 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆!\n\nYour link has been bypassed."
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🆘 Help", callback_data="help"),
            InlineKeyboardButton("👨‍💻 Developed By", url=f"https://t.me/{DEVELOPER_USERNAME}"),
        ]
    ])


# ---------------------------------------------------------------------------
# Health-check server
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
    text = (
        f"👋 𝗛𝗲𝗹𝗹𝗼, {user.first_name}!\n\n"
        f"I am a 𝗟𝗶𝗻𝗸 𝗕𝘆𝗽𝗮𝘀𝘀𝗲𝗿 𝗕𝗼𝘁. I can bypass shortlinks and ad-gates for you.\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 𝗧𝗼 𝗯𝘆𝗽𝗮𝘀𝘀 𝗮 𝗹𝗶𝗻𝗸\n"
        f"Simply paste any shortlink here (one at a time).\n\n"
        f"🗑 𝗔𝘂𝘁𝗼-𝗱𝗲𝗹𝗲𝘁𝗲\n"
        f"All my replies are automatically deleted after a few minutes to keep your chat clean and private.\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Use /help to see all available commands."
    )
    sent = await update.message.reply_text(text, reply_markup=start_keyboard())
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 𝗛𝗲𝗹𝗽 & 𝗨𝘀𝗮𝗴𝗲\n\n"
        "🚀 𝗚𝗲𝘁𝘁𝗶𝗻𝗴 𝗦𝘁𝗮𝗿𝘁𝗲𝗱:\n"
        "Send any shortener link and the bot will instantly bypass it.\n\n"
        "⚙️ 𝗪𝗵𝗮𝘁 𝘆𝗼𝘂 𝗴𝗲𝘁:\n"
        "• Direct download / destination link\n"
        "• No ads or countdown\n"
        "• Fast processing\n\n"
        "📌 𝗧𝗶𝗽𝘀:\n"
        "• Make sure your link is valid\n"
        "• Use full URLs (avoid shortened copies inside apps)\n\n"
        "❗️ 𝗟𝗶𝗺𝗶𝘁𝗮𝘁𝗶𝗼𝗻𝘀:\n"
        "• Some shorteners may not be supported\n"
        "• Private or expired links won't work\n\n"
        "✨ 𝗝𝘂𝘀𝘁 𝗱𝗿𝗼𝗽 𝘆𝗼𝘂𝗿 𝗹𝗶𝗻𝗸 𝗮𝗻𝗱 𝗹𝗲𝘁 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗵𝗮𝗻𝗱𝗹𝗲 𝗲𝘃𝗲𝗿𝘆𝘁𝗵𝗶𝗻𝗴!"
    )
    sent = await update.message.reply_text(text)
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Help inline button press."""
    query = update.callback_query
    await query.answer()

    text = (
        "🆘 𝗛𝗲𝗹𝗽 & 𝗨𝘀𝗮𝗴𝗲\n\n"
        "🚀 𝗚𝗲𝘁𝘁𝗶𝗻𝗴 𝗦𝘁𝗮𝗿𝘁𝗲𝗱:\n"
        "Send any shortener link and the bot will instantly bypass it.\n\n"
        "⚙️ 𝗪𝗵𝗮𝘁 𝘆𝗼𝘂 𝗴𝗲𝘁:\n"
        "• Direct download / destination link\n"
        "• No ads or countdown\n"
        "• Fast processing\n\n"
        "📌 𝗧𝗶𝗽𝘀:\n"
        "• Make sure your link is valid\n"
        "• Use full URLs (avoid shortened copies inside apps)\n\n"
        "❗️ 𝗟𝗶𝗺𝗶𝘁𝗮𝘁𝗶𝗼𝗻𝘀:\n"
        "• Some shorteners may not be supported\n"
        "• Private or expired links won't work\n\n"
        "✨ 𝗝𝘂𝘀𝘁 𝗱𝗿𝗼𝗽 𝘆𝗼𝘂𝗿 𝗹𝗶𝗻𝗸 𝗮𝗻𝗱 𝗹𝗲𝘁 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗵𝗮𝗻𝗱𝗹𝗲 𝗲𝘃𝗲𝗿𝘆𝘁𝗵𝗶𝗻𝗴!"
    )
    sent = await query.message.reply_text(text)
    schedule_delete(context.bot, query.message.chat_id, sent.message_id)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_logged_in = await user_client.is_logged_in()

    if is_logged_in:
        user_info = await user_client.get_me()
        text = (
            f"✅ <b>Status: Connected</b>\n\n"
            f"👤 Account: {user_info.first_name}\n"
            f"📱 Phone: {user_info.phone}\n"
            f"🤖 Bypasser: @{BYPASSER_BOT_USERNAME}\n"
            f"⏳ Pending requests: {len(user_client.pending_requests)}\n\n"
            f"Ready to bypass links!"
        )
    else:
        text = (
            "❌ <b>Status: Not Connected</b>\n\n"
            "Please use /login to connect your Telegram account."
        )

    sent = await update.message.reply_text(text, parse_mode='HTML')
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        sent = await update.message.reply_text("❌ Not logged in. Use /login first.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return

    sent = await update.message.reply_text("🧪 Testing connection to bypasser bot...")
    try:
        test_msg = await user_client.client.send_message(BYPASSER_BOT_USERNAME, "test")
        await sent.edit_text(
            f"✅ Test message sent!\nMessage ID: {test_msg.id}\n\nCheck if bypasser bot responds."
        )
    except Exception as e:
        await sent.edit_text(f"❌ Error: {str(e)}")
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        sent = await update.message.reply_text("❌ Not logged in. Use /login first.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return

    text = (
        f"🔍 <b>Debug Information</b>\n\n"
        f"Logged in: ✅ Yes\n"
        f"Bypasser bot: @{BYPASSER_BOT_USERNAME}\n"
        f"Bypasser bot ID: {user_client.bypasser_bot_id or '❌ Not found'}\n"
        f"Pending requests: {len(user_client.pending_requests)}\n"
        f"Timeout: {user_client.response_timeout}s"
    )
    sent = await update.message.reply_text(text, parse_mode='HTML')
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


# ---------------------------------------------------------------------------
# Login conversation
# ---------------------------------------------------------------------------

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await user_client.is_logged_in():
        sent = await update.message.reply_text("✅ Already logged in! Use /status to see details.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return ConversationHandler.END

    await update.message.reply_text(
        "🔐 <b>Login Process</b>\n\n"
        "Please send your phone number with country code.\n"
        "Example: +1234567890\n\n"
        "Send /cancel to abort.",
        parse_mode='HTML'
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
            f"✅ <b>Login Successful!</b>\n\n"
            f"👤 Logged in as: {user_info.first_name}\n\n"
            f"You can now send shortener links to bypass!",
            parse_mode='HTML'
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
            text=f"✅ <b>Login Successful!</b>\n\n👤 Logged in as: {user_info.first_name}\n\nYou can now send shortener links to bypass!",
            parse_mode='HTML'
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


# ---------------------------------------------------------------------------
# Response formatter
# ---------------------------------------------------------------------------

def format_bypass_response(text: str) -> str:
    """
    Reformat the bypasser bot response with Unicode bold labels
    so it looks native to our bot.

    Expected input structure (lines may vary slightly):
        Original Link :✅ <url>
        Bypassed Link:✅ <url>
        Time Taken : X seconds
        ─────────────────
        Share and Support Bot, ...
        Powered By @Bypasser_Max_bot
    """
    import re

    lines = text.strip().splitlines()
    out = []

    for line in lines:
        stripped = line.strip()

        # Original Link line
        if re.match(r'(?i)original\s*link', stripped):
            # Extract the URL part after the colon
            parts = stripped.split(':', 1)
            rest = parts[1].strip() if len(parts) > 1 else stripped
            out.append(f"𝗢𝗿𝗶𝗴𝗶𝗻𝗮𝗹 𝗟𝗶𝗻𝗸 : {rest}")

        # Bypassed Link line
        elif re.match(r'(?i)bypassed\s*link', stripped):
            parts = stripped.split(':', 1)
            rest = parts[1].strip() if len(parts) > 1 else stripped
            out.append(f"𝗕𝘆𝗽𝗮𝘀𝘀𝗲𝗱 𝗟𝗶𝗻𝗸 : {rest}")

        # Time Taken line
        elif re.match(r'(?i)time\s*taken', stripped):
            parts = stripped.split(':', 1)
            rest = parts[1].strip() if len(parts) > 1 else stripped
            out.append(f"𝗧𝗶𝗺𝗲 𝗧𝗮𝗸𝗲𝗻 : {rest}")

        # Separator line — keep as-is
        elif re.match(r'^[─\-─]+$', stripped):
            out.append(line)

        # Powered By line — bold it
        elif re.match(r'(?i)powered\s*by', stripped):
            parts = stripped.split(' ', 2)
            username = parts[2] if len(parts) > 2 else ''
            out.append(f"𝗣𝗼𝘄𝗲𝗿𝗲𝗱 𝗕𝘆 {username}")

        # Everything else (share line etc.) — keep as-is
        else:
            out.append(line)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Link handler
# ---------------------------------------------------------------------------

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        sent = await update.message.reply_text(
            "❌ Bot is not connected to any account.\n\nPlease use /login first."
        )
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return

    link = update.message.text.strip()

    if not (link.startswith('http://') or link.startswith('https://')):
        sent = await update.message.reply_text(
            "❌ Please send a valid URL starting with http:// or https://"
        )
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return

    # Auto-delete the user's link message
    schedule_delete(context.bot, update.effective_chat.id, update.message.message_id)

    processing_msg = await update.message.reply_text(
        f"⏳ <b>Processing your link...</b>\n"
        f"Sending to bypasser bot\n\n"
        f"⏱️ Please wait...",
        parse_mode='HTML'
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
                # Replace bypasser bot username with ours
                clean_text = message.text.replace('@Nick_Bypass_Bot', '@Bypasser_Max_bot')

                # Reformat the message with Unicode bold headings
                formatted = format_bypass_response(clean_text)

                sent = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=formatted,
                    parse_mode='HTML'
                )
                schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
            elif message.media or message.document:
                fwd = await message.forward_to(update.effective_chat.id)
                if fwd:
                    schedule_delete(context.bot, update.effective_chat.id, fwd.id)
            else:
                sent = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ Content bypassed!"
                )
                schedule_delete(context.bot, update.effective_chat.id, sent.message_id)

        except Exception as e:
            logger.error(f"Error in handle_response: {e}", exc_info=True)
            try:
                sent = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"❌ Error processing response: {str(e)}"
                )
                schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
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
                    "⏳ <b>Still processing...</b>\n\nThe bypasser bot is taking longer than usual.",
                    parse_mode='HTML'
                )
                schedule_delete(context.bot, update.effective_chat.id, processing_msg.message_id)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Error sending to bypasser: {e}", exc_info=True)
        try:
            await processing_msg.edit_text(f"❌ Error: {str(e)}\n\nPlease try again.")
            schedule_delete(context.bot, update.effective_chat.id, processing_msg.message_id)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared — polling mode ready")
    except Exception as e:
        logger.warning(f"Could not clear webhook: {e}")

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
# Main
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
    application.add_handler(CallbackQueryHandler(help_callback, pattern='^help$'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    async def run():
        health_runner = await start_health_server()

        stop_event = asyncio.Event()

        def _handle_signal():
            logger.info("Received shutdown signal")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                pass

        try:
            async with application:
                await application.initialize()
                await application.start()

                for attempt in range(10):
                    try:
                        await application.updater.start_polling(
                            allowed_updates=Update.ALL_TYPES,
                            drop_pending_updates=True
                        )
                        logger.info("✅ Bot is running")
                        break
                    except Exception as e:
                        if "Conflict" in str(e) or "409" in str(e):
                            wait = (attempt + 1) * 5
                            logger.warning(f"Conflict: retrying in {wait}s... (attempt {attempt + 1}/10)")
                            await asyncio.sleep(wait)
                        else:
                            raise

                await stop_event.wait()
        finally:
            logger.info("Shutting down...")
            try:
                await application.updater.stop()
            except Exception:
                pass
            await application.stop()
            await application.shutdown()
            await health_runner.cleanup()
            logger.info("Shutdown complete")

    asyncio.run(run())


if __name__ == '__main__':
    main()
