# user_bot.py

# ==============================================================================
# PART 1: IMPORTS, CONFIGURATION, AND CORE API FUNCTIONS
# ==============================================================================

import logging
import os
import asyncio
import requests
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import BadRequest
import database as db

# --- Configuration (গোপন তথ্যগুলো Railway-এর Variables থেকে আসবে) ---
try:
    USER_BOT_TOKEN = os.environ.get("USER_BOT_TOKEN")
    AD_WAIT_SECONDS = int(os.environ.get("AD_WAIT_SECONDS", 13))
    AD_LINKS = os.environ.get("AD_LINKS", "").split(',')
    SMS_API_KEY = os.environ.get("SMS_ACTIVATE_API_KEY")
    TELEGRAM_CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK", "https://t.me/telegram")
    # Welcome image URL (optional)
    WELCOME_IMAGE_URL = os.environ.get("WELCOME_IMAGE_URL", "https://i.ibb.co/example/welcome.jpg") # একটি উদাহরণ ছবি
except Exception as e:
    print(f"Error reading environment variables: {e}")
    # Provide default values if running locally without environment variables
    USER_BOT_TOKEN = "YOUR_LOCAL_TOKEN" # Local testing only

# --- Setup ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
user_temp_data = {}  # In-memory storage for temporary data like activation IDs

# --- 1secmail.com API Functions ( নির্ভরযোগ্য ইমেইল সিস্টেম) ---
async def create_email():
    """Generates a new random email address from 1secmail."""
    try:
        response = requests.get("https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1")
        response.raise_for_status()
        return response.json()[0]
    except requests.RequestException as e:
        logger.error(f"1secmail email creation error: {e}")
        return None

async def get_inbox(email):
    """Fetches the list of emails from the 1secmail inbox."""
    try:
        login, domain = email.split('@')
        url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"1secmail inbox fetch error: {e}")
        return []

async def get_message_details(email, message_id):
    """Fetches the full content of a specific email."""
    try:
        login, domain = email.split('@')
        url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={message_id}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"1secmail message read error: {e}")
        return None

# --- SMS-Activate.org API Functions (টেম্পোরারি নম্বর সিস্টেম) ---
async def get_number(service_code, country_code='0'):
    """Requests a number from SMS-Activate for a specific service."""
    if not SMS_API_KEY:
        logger.error("SMS_ACTIVATE_API_KEY is not set.")
        return {'error': 'Service not available'}
    url = f"https://api.sms-activate.org/stubs/handler_api.php?api_key={SMS_API_KEY}&action=getNumber&service={service_code}&country={country_code}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        parts = response.text.split(':')
        if parts[0] == "ACCESS_NUMBER":
            return {'status': 'success', 'id': parts[1], 'number': parts[2]}
        else:
            logger.error(f"SMS Activate getNumber error: {response.text}")
            return {'status': 'error', 'message': response.text}
    except requests.RequestException as e:
        logger.error(f"SMS Activate getNumber exception: {e}")
        return {'status': 'error', 'message': str(e)}

async def get_sms_status(activation_id):
    """Checks the status of an activation to see if an SMS has arrived."""
    url = f"https://api.sms-activate.org/stubs/handler_api.php?api_key={SMS_API_KEY}&action=getStatus&id={activation_id}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"SMS Activate getStatus exception: {e}")
        return "ERROR_GETTING_STATUS"

async def set_activation_status(activation_id, status):
    """Sets the status of an activation (e.g., cancel or report)."""
    url = f"https://api.sms-activate.org/stubs/handler_api.php?api_key={SMS_API_KEY}&action=setStatus&id={activation_id}&status={status}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"SMS Activate setStatus exception: {e}")
        return "ERROR_SETTING_STATUS"


# ==============================================================================
# END OF PART 1
# In the next part, we will add the keyboard layouts and the main /start command handler.
# ==============================================================================
# user_bot.py (Continued)

# ==============================================================================
# PART 2: KEYBOARD LAYOUTS AND MAIN COMMAND HANDLERS
# ==============================================================================

# --- Keyboard Layouts (বাটনগুলোর ডিজাইন) ---

def get_main_menu_keyboard(user_id):
    """Generates the main menu keyboard with the user's balance."""
    user = db.get_user(user_id)
    balance = user['balance'] if user else 0.0
    
    keyboard = [
        [InlineKeyboardButton(f"💰 আপনার ব্যালেন্স: {balance:.2f} ক্রেডিট", callback_data="account_menu")],
        [
            InlineKeyboardButton("✉️ টেম্পোরারি ইমেইল", callback_data="email_menu"),
            InlineKeyboardButton("📱 টেম্পোরারি নম্বর", callback_data="number_menu")
        ],
        [
            InlineKeyboardButton("💎 프리미엄 ও টপ-আপ", callback_data="premium_menu"),
            InlineKeyboardButton("🤝 রেফারেল", callback_data="referral_menu")
        ],
        [
            InlineKeyboardButton("📞 সাপোর্ট", callback_data="support_menu"),
            InlineKeyboardButton("📢 চ্যানেল", url=TELEGRAM_CHANNEL_LINK)
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_email_control_keyboard(ad_free_refresh=False):
    """Generates the control keyboard for an active email session."""
    if ad_free_refresh:
        # After the ad, the refresh button is ad-free.
        refresh_button = InlineKeyboardButton("🔄 আবার রিফ্রেশ করুন (Ad-Free)", callback_data="email_proceed_inbox_ad_free")
    else:
        # The first time, the refresh button will trigger an ad prompt.
        refresh_button = InlineKeyboardButton("🔄 ইনবক্স চেক করুন", callback_data="email_inbox_prompt")

    return InlineKeyboardMarkup([
        [refresh_button],
        [InlineKeyboardButton("🗑️ ইমেইলটি মুছুন", callback_data="email_delete_confirm")],
        [InlineKeyboardButton("↩️ মূল মেন্যুতে ফিরুন", callback_data="main_menu")]
    ])

# --- Main Command and Callback Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command. Registers the user and shows the main menu."""
    user = update.effective_user
    
    # Extract referral code from the start command if it exists (e.g., /start ref_code)
    referral_code = context.args[0] if context.args else None
    
    # Add user to the database if they don't exist
    db.add_user_if_not_exists(user.id, user.first_name, referral_code)
    
    text = f"👋 *স্বাগতম, {user.first_name}!* \n\nআপনার প্রয়োজনীয় সার্ভিসটি বেছে নিন।"
    keyboard = get_main_menu_keyboard(user.id)
    
    # Send message with an image if a URL is provided
    if update.message:
        if WELCOME_IMAGE_URL and "example.jpg" not in WELCOME_IMAGE_URL:
             try:
                await update.message.reply_photo(photo=WELCOME_IMAGE_URL, caption=text, reply_markup=keyboard, parse_mode='Markdown')
             except Exception as e:
                logger.warning(f"Could not send welcome photo, sending text instead. Error: {e}")
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

    elif update.callback_query:
        query = update.callback_query
        try:
            # Edit the existing message to show the main menu
            await query.answer()
            # If the current message has a photo, we need to edit its caption
            if query.message.photo:
                await query.edit_message_caption(caption=text, reply_markup=keyboard, parse_mode='Markdown')
            else:
                await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                # Ignore if the message is already what we want it to be
                pass
            else:
                logger.error(f"Error editing message to main menu: {e}")
                # If editing fails, send a new message
                await context.bot.send_message(chat_id=query.from_user.id, text=text, reply_markup=keyboard, parse_mode='Markdown')


async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles callbacks that should lead back to the main menu."""
    query = update.callback_query
    await start(update, context) # The start function is reused for showing the main menu

async def account_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the user's account details."""
    query = update.callback_query
    await query.answer()
    user = db.get_user(query.from_user.id)

    if not user:
        await query.edit_message_text("❌ আপনার তথ্য পাওয়া যায়নি। অনুগ্রহ করে /start চাপুন।")
        return

    text = (
        f"👤 *আমার অ্যাকাউন্ট*\n\n"
        f"**নাম:** {user['first_name']}\n"
        f"**ইউজার আইডি:** `{user['user_id']}`\n"
        f"**বর্তমান ব্যালেন্স:** {user['balance']:.2f} ক্রেডিট\n"
        f"**প্রিমিয়াম স্ট্যাটাস:** {'সক্রিয়' if user['is_premium'] else 'নিষ্ক্রিয়'}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ মূল মেন্যুতে ফিরুন", callback_data="main_menu")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


# ==============================================================================
# END OF PART 2
# In the next part, we will add the logic for the Email and Ad system.
# ==============================================================================
# user_bot.py (Continued)

# ==============================================================================
# PART 3: CORE FEATURES (EMAIL, NUMBER, CREDIT, REFERRAL) AND FINALIZATION
# ==============================================================================

# --- Ad System (বিজ্ঞাপন দেখানোর নির্ভরযোগ্য সিস্টেম) ---
async def show_ad_prompt(query: Update.callback_query, action: str):
    """Displays an ad prompt and schedules the appearance of the proceed button."""
    random_ad = random.choice(AD_LINKS) if AD_LINKS else "https://telegram.org"
    text = (
        f"⏳ কাজটি সম্পন্ন করতে, অনুগ্রহ করে নিচের বিজ্ঞাপনটি দেখুন।\n\n"
        f"**{AD_WAIT_SECONDS} সেকেন্ড পর** পরবর্তী ধাপের বাটনটি স্বয়ংক্রিয়ভাবে এখানে চলে আসবে।"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("👁️ বিজ্ঞাপন দেখুন (View Ad)", url=random_ad)]])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

    # Directly wait here (reliable for free hosting)
    await asyncio.sleep(AD_WAIT_SECONDS)

    if action == "generate_email":
        callback_data, button_text = "email_proceed_generate", "✅ এখন ইমেইল তৈরি করুন"
        cancel_callback = "email_menu"
    elif action == "check_inbox":
        callback_data, button_text = "email_proceed_inbox_ad_free", "✅ এখন ইনবক্স দেখুন"
        cancel_callback = "my_email_inbox"

    new_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ বিজ্ঞাপন দেখুন (View Ad)", url=random_ad)],
        [InlineKeyboardButton(button_text, callback_data=callback_data)],
        [InlineKeyboardButton("↩️ বাতিল করুন", callback_data=cancel_callback)]
    ])
    try:
        await query.edit_message_text(text, reply_markup=new_keyboard, parse_mode='Markdown')
    except BadRequest:
        logger.warning("Message to edit was not found (likely deleted by user).")

# --- Email Feature Handlers ---
async def email_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'Temporary Email' menu."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # Check if user already has an email
    if user_id in user_temp_data and "email" in user_temp_data[user_id]:
        await my_email_inbox_handler(update, context)
        return

    price = db.get_setting('price_email_credit')
    text = (
        f"✉️ *টেম্পোরারি ইমেইল সার্ভিস*\n\n"
        f"আপনি বিজ্ঞাপন দেখে বিনামূল্যে একটি ইমেইল তৈরি করতে পারেন, অথবা বিজ্ঞাপন ছাড়া ব্যবহারের জন্য {price:.2f} ক্রেডিট খরচ করতে পারেন।"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 বিজ্ঞাপন দেখে করুন (ফ্রি)", callback_data="email_ad_prompt")],
        [InlineKeyboardButton(f"💳 {price:.2f} ক্রেডিট খরচ করুন", callback_data="email_pay_generate")],
        [InlineKeyboardButton("↩️ মূল মেন্যুতে ফিরুন", callback_data="main_menu")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')

async def my_email_inbox_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays the user's current email and inbox controls."""
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id in user_temp_data and "email" in user_temp_data[user_id]:
        email = user_temp_data[user_id]["email"]
        text = (
            f"📬 আপনার বর্তমান সক্রিয় ইমেইল:\n"
            f"```{email}```\n"
            f"_(কপি করতে উপরের ইমেইলটির উপর একবার ট্যাপ করুন)_\n\n---\n"
            f"*ইনবক্স দেখতে নিচের বাটনে ক্লিক করুন। (শুধুমাত্র প্রথমবার বিজ্ঞাপন দেখতে হবে)*"
        )
        await query.edit_message_text(text, reply_markup=get_email_control_keyboard(ad_free_refresh=False), parse_mode='Markdown')
    else:
        text = "⚠️ আপনার কোনো সক্রিয় ইমেইল নেই।\n\nপ্রথমে একটি নতুন ইমেইল তৈরি করুন।"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✉️ নতুন ইমেইল তৈরি করুন", callback_data="email_menu")],
            [InlineKeyboardButton("↩️ মূল মেন্যুতে ফিরুন", callback_data="main_menu")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def email_generation_logic(query: Update.callback_query):
    """The core logic for generating an email."""
    await query.edit_message_text("⏳ আপনার জন্য একটি নতুন ইমেইল তৈরি করা হচ্ছে...", parse_mode='Markdown')
    email = await create_email()
    if email:
        user_temp_data[query.from_user.id] = {"email": email}
        text = (
            f"✅ আপনার নতুন ইমেইল সফলভাবে তৈরি হয়েছে!\n\n"
            f"**আপনার ইমেইল ঠিকানা:**\n```{email}```\n"
            f"_(কপি করতে উপরের ইমেইলটির উপর একবার ট্যাপ করুন)_\n\n---"
        )
        await query.edit_message_text(text, reply_markup=get_email_control_keyboard(), parse_mode='Markdown')
    else:
        text = "❌ দুঃখিত, এই মুহূর্তে ইমেইল সার্ভিসটিতে সমস্যা চলছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ মূল মেন্যুতে ফিরুন", callback_data="main_menu")]])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')


async def inbox_processing_logic(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE):
    """The core logic for fetching and displaying inbox messages."""
    user_id = query.from_user.id
    if user_id in user_temp_data and "email" in user_temp_data[user_id]:
        email = user_temp_data[user_id]['email']
        await query.edit_message_text(f"⏳ `{email}`-এর ইনবক্স চেক করা হচ্ছে...", parse_mode='Markdown')
        inbox_messages = await get_inbox(email)
        
        email_text = (f"📬 আপনার বর্তমান সক্রিয় ইমেইল:\n```{email}```\n"
                      f"_(কপি করতে উপরের ইমেইলটির উপর একবার ট্যাপ করুন)_\n\n---")
        
        if not inbox_messages:
            final_text = email_text + "\n📭 আপনার ইনবক্স খালি।"
            await query.edit_message_text(final_text, reply_markup=get_email_control_keyboard(ad_free_refresh=True), parse_mode='Markdown')
        else:
            final_text = email_text + f"\n✅ ইনবক্সে *{len(inbox_messages)}* টি নতুন মেসেজ পাওয়া গেছে। সেগুলো নিচে পাঠানো হলো:"
            await query.edit_message_text(final_text, reply_markup=get_email_control_keyboard(ad_free_refresh=True), parse_mode='Markdown')
            for msg in inbox_messages:
                details = await get_message_details(email, msg['id'])
                if details:
                    message_text = (f"📧 **From:** {details.get('from', 'N/A')}\n"
                                    f"**Subject:** {details.get('subject', 'N/A')}\n"
                                    f"**Date:** {details.get('date', 'N/A')}\n\n"
                                    f"---\n{details.get('textBody', '...')}")
                    await context.bot.send_message(chat_id=user_id, text=message_text, parse_mode='HTML')
    else:
        await query.edit_message_text("❌ আপনার কোনো সক্রিয় ইমেইল নেই।", reply_markup=get_main_menu_keyboard(), parse_mode='Markdown')

# --- Placeholder Handlers for other features ---
async def number_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("এই ফিচারটি শীঘ্রই আসছে!", show_alert=True)

async def premium_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("এই ফিচারটি শীঘ্রই আসছে!", show_alert=True)

async def referral_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("এই ফিচারটি শীঘ্রই আসছে!", show_alert=True)
    
async def support_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("এই ফিচারটি শীঘ্রই আসছে!", show_alert=True)


# --- Universal Button Handler ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The main router for all callback queries."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # Main Navigation
    if data == "main_menu":
        await start(update, context)
    elif data == "account_menu":
        await account_menu_handler(update, context)
    
    # Placeholder Menus
    elif data == "number_menu":
        await number_menu_handler(update, context)
    elif data == "premium_menu":
        await premium_menu_handler(update, context)
    elif data == "referral_menu":
        await referral_menu_handler(update, context)
    elif data == "support_menu":
        await support_menu_handler(update, context)

    # Email Menu Navigation
    elif data == "email_menu":
        await email_menu_handler(update, context)
    elif data == "my_email_inbox":
        await my_email_inbox_handler(update, context)

    # Email Actions (Ad-based and Credit-based)
    elif data == "email_ad_prompt":
        await show_ad_prompt(query, "generate_email")
    elif data == "email_proceed_generate":
        await email_generation_logic(query)
    elif data == "email_pay_generate":
        user = db.get_user(user_id)
        price = db.get_setting('price_email_credit')
        if user and user['balance'] >= price:
            db.update_balance(user_id, -price)
            await email_generation_logic(query)
        else:
            await query.answer("❌ আপনার অ্যাকাউন্টে পর্যাপ্ত ক্রেডিট নেই।", show_alert=True)
            await premium_menu_handler(update, context) # Redirect to top-up

    # Inbox Actions
    elif data == "email_inbox_prompt":
        await show_ad_prompt(query, "check_inbox")
    elif data == "email_proceed_inbox_ad_free":
        await inbox_processing_logic(query, context)

    # Email Deletion
    elif data == "email_delete_confirm":
        text = "🤔 আপনি কি সত্যিই আপনার বর্তমান ইমেইলটি মুছে ফেলতে চান?"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✔️ হ্যাঁ, মুছুন", callback_data="email_delete_confirmed")],
            [InlineKeyboardButton("❌ না, থাক", callback_data="my_email_inbox")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard)
    elif data == "email_delete_confirmed":
        if user_id in user_temp_data:
            del user_temp_data[user_id]
        text = "🗑️ আপনার ইমেইল সফলভাবে মুছে ফেলা হয়েছে।"
        await query.edit_message_text(text, reply_markup=get_main_menu_keyboard(user_id), parse_mode='Markdown')


def main() -> None:
    """Initializes and runs the bot."""
    # Ensure DATABASE_URL is set
    if not os.environ.get('DATABASE_URL'):
        logger.error("FATAL: DATABASE_URL environment variable is not set.")
        return

    application = Application.builder().token(USER_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("User Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()

# ==============================================================================
# END OF PART 3
# The user_bot.py file is now complete.
# ==============================================================================