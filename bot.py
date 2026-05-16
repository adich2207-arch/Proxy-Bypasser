import asyncio
import logging
import os
import re
import signal
from datetime import datetime, timezone

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
from config import BOT_TOKEN, validate_config, BYPASSER_BOT_USERNAME, ADMIN_ID

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

PHONE_NUMBER, OTP_CODE, PASSWORD = range(3)
login_sessions = {}
PORT = int(os.environ.get('PORT', 8080))
AUTO_DELETE_DELAY = 10 * 60
DEVELOPER_USERNAME = "Mr_1X8"


# ---------------------------------------------------------------------------
# Stats (in-memory)
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.all_users = {}
        self.total_bypasses = 0
        self.bot_start_time = datetime.now(timezone.utc)

    def register_user(self, user):
        uid = user.id
        now = datetime.now(timezone.utc)
        if uid not in self.all_users:
            self.all_users[uid] = {
                'first_name': user.first_name,
                'username': user.username,
                'first_seen': now,
                'last_active': now,
                'bypass_count': 0,
            }
        else:
            self.all_users[uid]['last_active'] = now
            self.all_users[uid]['first_name'] = user.first_name
            self.all_users[uid]['username'] = user.username

    def record_bypass(self, user_id):
        self.total_bypasses += 1
        if user_id in self.all_users:
            self.all_users[user_id]['bypass_count'] += 1
            self.all_users[user_id]['last_active'] = datetime.now(timezone.utc)

    def active_today(self):
        now = datetime.now(timezone.utc)
        return sum(1 for u in self.all_users.values() if (now - u['last_active']).days == 0)

    def uptime(self):
        delta = datetime.now(timezone.utc) - self.bot_start_time
        h, rem = divmod(int(delta.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"


stats = Stats()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def auto_delete(bot, chat_id, message_id, delay=AUTO_DELETE_DELAY):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def schedule_delete(bot, chat_id, message_id, delay=AUTO_DELETE_DELAY):
    asyncio.create_task(auto_delete(bot, chat_id, message_id, delay))


def start_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🆘 Help", callback_data="help"),
        InlineKeyboardButton("👨‍💻 Developed By", url=f"https://t.me/{DEVELOPER_USERNAME}"),
    ]])


def is_admin(user_id):
    return ADMIN_ID is not None and user_id == ADMIN_ID


def strip_markdown(text):
    return re.sub(r'[*_`~]', '', text)


def format_bypass_response(text):
    text = strip_markdown(text)
    text = re.sub(r'(?i)powered\s*by\s*@\S+', 'Powered By @Bypasser_Max_bot', text)
    text = re.sub(r'(?i)@Nick_Bypass_Bot', '@Bypasser_Max_bot', text)

    lines = text.strip().splitlines()
    out = []
    for line in lines:
        s = line.strip()
        if re.match(r'(?i)original\s*link', s):
            parts = s.split(':', 1)
            rest = parts[1].strip() if len(parts) > 1 else s
            out.append(f"𝗢𝗿𝗶𝗴𝗶𝗻𝗮𝗹 𝗟𝗶𝗻𝗸 : {rest}")
        elif re.match(r'(?i)bypassed\s*link', s):
            parts = s.split(':', 1)
            rest = parts[1].strip() if len(parts) > 1 else s
            out.append(f"𝗕𝘆𝗽𝗮𝘀𝘀𝗲𝗱 𝗟𝗶𝗻𝗸 : {rest}")
        elif re.match(r'(?i)time\s*taken', s):
            parts = s.split(':', 1)
            rest = parts[1].strip() if len(parts) > 1 else s
            out.append(f"𝗧𝗶𝗺𝗲 𝗧𝗮𝗸𝗲𝗻 : {rest}")
        elif re.match(r'^[─\-]+$', s):
            out.append(line)
        elif re.match(r'(?i)powered\s*by', s):
            parts = s.split(' ', 2)
            username = parts[2] if len(parts) > 2 else ''
            out.append(f"𝗣𝗼𝘄𝗲𝗿𝗲𝗱 𝗕𝘆 {username}")
        else:
            out.append(line)
    return "\n".join(out)


def help_text():
    return (
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


def admin_panel_text():
    total = len(stats.all_users)
    active = stats.active_today()
    bypasses = stats.total_bypasses
    uptime = stats.uptime()
    top_users = sorted(stats.all_users.items(), key=lambda x: x[1]['bypass_count'], reverse=True)[:5]
    top_text = ""
    for i, (uid, data) in enumerate(top_users, 1):
        name = data['first_name'] or 'Unknown'
        uname = f"@{data['username']}" if data['username'] else f"ID:{uid}"
        top_text += f"  {i}. {name} ({uname}) — {data['bypass_count']} bypasses\n"
    if not top_text:
        top_text = "  No data yet.\n"
    return (
        f"🛡 𝗔𝗱𝗺𝗶𝗻 𝗣𝗮𝗻𝗲𝗹\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 𝗨𝘀𝗲𝗿 𝗦𝘁𝗮𝘁𝘀\n"
        f"• Total users: {total}\n"
        f"• Active today: {active}\n\n"
        f"🔗 𝗕𝘆𝗽𝗮𝘀𝘀 𝗦𝘁𝗮𝘁𝘀\n"
        f"• Total bypasses: {bypasses}\n\n"
        f"⏱ 𝗨𝗽𝘁𝗶𝗺𝗲: {uptime}\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 𝗧𝗼𝗽 𝟱 𝗨𝘀𝗲𝗿𝘀\n"
        f"{top_text}\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"Use /users to see full user list."
    )


def admin_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👥 All Users", callback_data="admin_users"),
        InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh"),
    ]])


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
    stats.register_user(user)
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
    sent = await update.message.reply_text(help_text())
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sent = await query.message.reply_text(help_text())
    schedule_delete(context.bot, query.message.chat_id, sent.message_id)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_logged_in = await user_client.is_logged_in()
    if is_logged_in:
        user_info = await user_client.get_me()
        text = (
            f"✅ 𝗦𝘁𝗮𝘁𝘂𝘀: 𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗲𝗱\n\n"
            f"👤 Account: {user_info.first_name}\n"
            f"📱 Phone: {user_info.phone}\n"
            f"🤖 Bypasser: @{BYPASSER_BOT_USERNAME}\n"
            f"⏳ Pending: {len(user_client.pending_requests)}\n\n"
            f"Ready to bypass links!"
        )
    else:
        text = "❌ 𝗦𝘁𝗮𝘁𝘂𝘀: 𝗡𝗼𝘁 𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗲𝗱\n\nPlease use /login to connect your Telegram account."
    sent = await update.message.reply_text(text)
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        sent = await update.message.reply_text("❌ Not logged in. Use /login first.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return
    sent = await update.message.reply_text("🧪 Testing connection to bypasser bot...")
    try:
        test_msg = await user_client.client.send_message(BYPASSER_BOT_USERNAME, "test")
        await sent.edit_text(f"✅ Test message sent! ID: {test_msg.id}")
    except Exception as e:
        await sent.edit_text(f"❌ Error: {str(e)}")
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await user_client.is_logged_in():
        sent = await update.message.reply_text("❌ Not logged in. Use /login first.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return
    text = (
        f"🔍 𝗗𝗲𝗯𝘂𝗴 𝗜𝗻𝗳𝗼\n\n"
        f"Logged in: ✅ Yes\n"
        f"Bypasser: @{BYPASSER_BOT_USERNAME}\n"
        f"Bypasser ID: {user_client.bypasser_bot_id or '❌ Not found'}\n"
        f"Pending: {len(user_client.pending_requests)}\n"
        f"Timeout: {user_client.response_timeout}s"
    )
    sent = await update.message.reply_text(text)
    schedule_delete(context.bot, update.effective_chat.id, sent.message_id)


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    await update.message.reply_text(admin_panel_text(), reply_markup=admin_keyboard())


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized.")
        return
    if not stats.all_users:
        await update.message.reply_text("No users yet.")
        return

    sorted_users = sorted(stats.all_users.items(), key=lambda x: x[1]['last_active'], reverse=True)
    lines = [f"👥 𝗔𝗹𝗹 𝗨𝘀𝗲𝗿𝘀 ({len(sorted_users)} total)\n"]
    for uid, data in sorted_users:
        name = data['first_name'] or 'Unknown'
        uname = f"@{data['username']}" if data['username'] else f"ID:{uid}"
        last = data['last_active'].strftime('%d %b %H:%M')
        lines.append(f"• {name} ({uname})\n  Last active: {last} | Bypasses: {data['bypass_count']}")

    full_text = "\n".join(lines)
    if len(full_text) <= 4096:
        await update.message.reply_text(full_text)
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 4096:
                await update.message.reply_text(chunk)
                chunk = line
            else:
                chunk += "\n" + line
        if chunk:
            await update.message.reply_text(chunk)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    if query.data == "admin_refresh":
        await query.edit_message_text(admin_panel_text(), reply_markup=admin_keyboard())

    elif query.data == "admin_users":
        if not stats.all_users:
            await query.message.reply_text("No users yet.")
            return
        sorted_users = sorted(stats.all_users.items(), key=lambda x: x[1]['last_active'], reverse=True)
        lines = [f"👥 𝗔𝗹𝗹 𝗨𝘀𝗲𝗿𝘀 ({len(sorted_users)} total)\n"]
        for uid, data in sorted_users:
            name = data['first_name'] or 'Unknown'
            uname = f"@{data['username']}" if data['username'] else f"ID:{uid}"
            last = data['last_active'].strftime('%d %b %H:%M')
            lines.append(f"• {name} ({uname})\n  Last active: {last} | Bypasses: {data['bypass_count']}")
        full_text = "\n".join(lines)
        if len(full_text) <= 4096:
            await query.message.reply_text(full_text)
        else:
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 4096:
                    await query.message.reply_text(chunk)
                    chunk = line
                else:
                    chunk += "\n" + line
            if chunk:
                await query.message.reply_text(chunk)


# ---------------------------------------------------------------------------
# Login conversation
# ---------------------------------------------------------------------------

async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await user_client.is_logged_in():
        sent = await update.message.reply_text("✅ Already logged in! Use /status to see details.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return ConversationHandler.END
    await update.message.reply_text(
        "🔐 𝗟𝗼𝗴𝗶𝗻 𝗣𝗿𝗼𝗰𝗲𝘀𝘀\n\n"
        "Please send your phone number with country code.\n"
        "Example: +1234567890\n\n"
        "Send /cancel to abort."
    )
    return PHONE_NUMBER


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone_number = update.message.text.strip()
    if not phone_number.startswith('+'):
        await update.message.reply_text("❌ Please include country code with + sign.\nExample: +1234567890")
        return PHONE_NUMBER
    try:
        await update.message.reply_text("📤 Sending verification code...")
        phone_code_hash = await user_client.login_with_phone(phone_number)
        login_sessions[update.effective_user.id] = {
            'phone_number': phone_number,
            'phone_code_hash': phone_code_hash
        }
        await update.message.reply_text("✅ Code sent!\n\nEnter the code you received.\n\nSend /cancel to abort.")
        return OTP_CODE
    except Exception as e:
        logger.error(f"Error in receive_phone: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}\n\nTry again with /login")
        return ConversationHandler.END


async def receive_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    user_id = update.effective_user.id
    if user_id not in login_sessions:
        await update.message.reply_text("❌ Session expired. Start again with /login")
        return ConversationHandler.END
    session = login_sessions[user_id]
    try:
        await update.message.reply_text("🔄 Verifying code...")
        await user_client.verify_code(session['phone_number'], code, session['phone_code_hash'])
        del login_sessions[user_id]
        user_info = await user_client.get_me()
        await update.message.reply_text(
            f"✅ 𝗟𝗼𝗴𝗶𝗻 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹!\n\n"
            f"👤 Logged in as: {user_info.first_name}\n\n"
            f"You can now send shortener links to bypass!"
        )
        return ConversationHandler.END
    except Exception as e:
        error_msg = str(e)
        if "2FA_REQUIRED" in error_msg:
            await update.message.reply_text("🔐 2FA enabled.\n\nSend your 2FA password.\n\nSend /cancel to abort.")
            return PASSWORD
        else:
            logger.error(f"Error in receive_otp: {e}")
            await update.message.reply_text(f"❌ Verification failed: {error_msg}\n\nTry again with /login")
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
            text=f"✅ 𝗟𝗼𝗴𝗶𝗻 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹!\n\n👤 Logged in as: {user_info.first_name}\n\nYou can now send shortener links!"
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in receive_password: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Authentication failed: {str(e)}\n\nTry again with /login"
        )
        login_sessions.pop(user_id, None)
        return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login_sessions.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Login cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Link handler
# ---------------------------------------------------------------------------

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats.register_user(user)

    if not await user_client.is_logged_in():
        sent = await update.message.reply_text("❌ Bot is not connected.\n\nPlease use /login first.")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return

    link = update.message.text.strip()
    if not (link.startswith('http://') or link.startswith('https://')):
        sent = await update.message.reply_text("❌ Please send a valid URL starting with http:// or https://")
        schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        return

    schedule_delete(context.bot, update.effective_chat.id, update.message.message_id)

    processing_msg = await update.message.reply_text(
        "⏳ 𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝘆𝗼𝘂𝗿 𝗹𝗶𝗻𝗸...\n\n⏱️ Please wait..."
    )

    response_received = {'status': False}

    async def handle_response(message):
        try:
            response_received['status'] = True
            stats.record_bypass(update.effective_user.id)
            try:
                await processing_msg.delete()
            except Exception:
                pass
            if message.text:
                formatted = format_bypass_response(message.text)
                sent = await context.bot.send_message(chat_id=update.effective_chat.id, text=formatted)
                schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
            elif message.media or message.document:
                fwd = await message.forward_to(update.effective_chat.id)
                if fwd:
                    schedule_delete(context.bot, update.effective_chat.id, fwd.id)
            else:
                sent = await context.bot.send_message(chat_id=update.effective_chat.id, text="✅ Content bypassed!")
                schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
        except Exception as e:
            logger.error(f"Error in handle_response: {e}", exc_info=True)
            try:
                sent = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Error: {str(e)}")
                schedule_delete(context.bot, update.effective_chat.id, sent.message_id)
            except Exception:
                pass

    try:
        await user_client.send_to_bypasser(link, update.effective_chat.id, update.message.message_id, handle_response)
        await asyncio.sleep(30)
        if not response_received['status']:
            try:
                await processing_msg.edit_text("⏳ 𝗦𝘁𝗶𝗹𝗹 𝗽𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴...\n\nThe bypasser is taking longer than usual.")
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
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CommandHandler('users', users_command))
    application.add_handler(login_conv)
    application.add_handler(CallbackQueryHandler(help_callback, pattern='^help$'))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern='^admin_'))
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
