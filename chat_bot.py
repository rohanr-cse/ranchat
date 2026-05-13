import os
import telebot
import sqlite3
from telebot.types import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice

# ====================== YOUR SETTINGS ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

ADMIN_IDS = [7482620012]

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ====================== DATABASE ======================
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
USE_POSTGRES = bool(DATABASE_URL)
DB_PLACEHOLDER = "%s" if USE_POSTGRES else "?"

if USE_POSTGRES:
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required when DATABASE_URL is set") from exc

    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor().execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            gender TEXT,
            is_premium BOOLEAN DEFAULT FALSE
        )
        """
    )
    conn.commit()
else:
    conn = sqlite3.connect("bot_users.db", check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users
        (user_id INTEGER PRIMARY KEY, gender TEXT, is_premium INTEGER DEFAULT 0)
        """
    )
    conn.commit()

def db_fetchone(query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    return cur.fetchone()

def get_gender(user_id):
    row = db_fetchone(f"SELECT gender FROM users WHERE user_id={DB_PLACEHOLDER}", (user_id,))
    return row[0] if row else None

def is_premium(user_id):
    if user_id in ADMIN_IDS:
        return True
    row = db_fetchone(f"SELECT is_premium FROM users WHERE user_id={DB_PLACEHOLDER}", (user_id,))
    return bool(row and row[0])

def set_gender(user_id, gender):
    cur = conn.cursor()
    cur.execute(
        f"SELECT 1 FROM users WHERE user_id={DB_PLACEHOLDER}",
        (user_id,),
    )
    if cur.fetchone():
        cur.execute(
            f"UPDATE users SET gender={DB_PLACEHOLDER} WHERE user_id={DB_PLACEHOLDER}",
            (gender, user_id),
        )
    else:
        cur.execute(
            f"INSERT INTO users (user_id, gender) VALUES ({DB_PLACEHOLDER}, {DB_PLACEHOLDER})",
            (user_id, gender),
        )
    conn.commit()

def set_premium(user_id):
    cur = conn.cursor()
    premium_value = True if USE_POSTGRES else 1
    cur.execute(
        f"UPDATE users SET is_premium={DB_PLACEHOLDER} WHERE user_id={DB_PLACEHOLDER}",
        (premium_value, user_id),
    )
    conn.commit()

# ====================== STATE ======================
active_pair = {}
available = {'M': [], 'F': [], 'RANDOM': []}
seekers = {'M': [], 'F': [], 'RANDOM': []}
waiting_users = {}

# ====================== KEYBOARDS ======================
def get_main_keyboard(user_id):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🎲 Random Chat")
    kb.add("👨 Find Male", "👩 Find Female")
    if is_premium(user_id):
        kb.add("👤 Change Gender")
    return kb

chat_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
chat_menu.add("🔄 Next Chat", "❌ End Chat")

gender_menu = ReplyKeyboardMarkup(resize_keyboard=True)
gender_menu.add("Male", "Female")

# ====================== HELPERS ======================
def cleanup_user(user_id):
    waiting_users.pop(user_id, None)

def create_pair(user1, user2):
    if user1 == user2:
        return False
    cleanup_user(user1)
    cleanup_user(user2)
    active_pair[user1] = user2
    active_pair[user2] = user1
    bot.send_message(user1, "✅ Connected! Say hi 👋", reply_markup=chat_menu)
    bot.send_message(user2, "✅ Connected! Say hi 👋", reply_markup=chat_menu)
    return True

def end_chat(user_id):
    if user_id in active_pair:
        partner = active_pair.pop(user_id, None)
        if partner and partner in active_pair:
            active_pair.pop(partner, None)
        cleanup_user(user_id)
        if partner:
            cleanup_user(partner)
        bot.send_message(user_id, "💔 Chat ended.", reply_markup=get_main_keyboard(user_id))
        if partner:
            bot.send_message(partner, "💔 Partner ended the chat.", reply_markup=get_main_keyboard(partner))

def show_buy_premium(user_id):
    if is_premium(user_id):
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔓 Buy Lifetime Premium (50 ⭐)", callback_data="buy_premium"))
    bot.send_message(user_id,
        "🔒 Gender search requires Premium!\n"
        "One-time 50 Stars = unlimited gender chats + change gender\n\n"
        "🎲 Random Chat is always free & unlimited for everyone.",
        reply_markup=markup)

def mode_matches(mode, partner_gender):
    return mode == 'RANDOM' or mode == partner_gender

def can_pair_users(user_id, user_gender, user_mode, candidate_id, candidate_mode):
    if candidate_id == user_id:
        return False

    if candidate_id in active_pair:
        cleanup_user(candidate_id)
        return False

    candidate_gender = get_gender(candidate_id)
    if not candidate_gender:
        cleanup_user(candidate_id)
        return False

    return (
        mode_matches(user_mode, candidate_gender)
        and mode_matches(candidate_mode, user_gender)
    )

def find_waiting_partner(user_id, user_gender, user_mode):
    candidates = sorted(list(waiting_users.items()), key=lambda item: item[1] == 'RANDOM')

    for candidate_id, candidate_mode in candidates:
        if can_pair_users(user_id, user_gender, user_mode, candidate_id, candidate_mode):
            return candidate_id

    return None

def find_partner_with_preferences(user_id, mode):
    gender = get_gender(user_id)
    if not gender:
        bot.send_message(user_id, "Please set your gender first:", reply_markup=gender_menu)
        return

    if user_id in active_pair:
        bot.send_message(user_id, "End your current chat first.", reply_markup=chat_menu)
        return

    is_gender_mode = mode in ['M', 'F']
    if is_gender_mode and not is_premium(user_id):
        show_buy_premium(user_id)
        return

    cleanup_user(user_id)

    partner = find_waiting_partner(user_id, gender, mode)
    if partner is not None and create_pair(user_id, partner):
        return

    waiting_users[user_id] = mode
    wait_msg = "Waiting for match..." if mode == 'RANDOM' else f"Waiting for {'Male' if mode == 'M' else 'Female'}..."
    bot.send_message(user_id, wait_msg, reply_markup=get_main_keyboard(user_id))

def find_partner(user_id, mode):   # mode: 'RANDOM', 'M', 'F'
    return find_partner_with_preferences(user_id, mode)
    gender = get_gender(user_id)
    if not gender:
        bot.send_message(user_id, "Please set your gender first:", reply_markup=gender_menu)
        return

    is_gender_mode = (mode in ['M', 'F'])

    if is_gender_mode and not is_premium(user_id):
        show_buy_premium(user_id)
        return

    cleanup_user(user_id)

    # Add user to correct pool
    pool_key = 'RANDOM' if mode == 'RANDOM' else gender
    if pool_key not in available:
        available[pool_key] = []
    if user_id not in available[pool_key]:
        available[pool_key].append(user_id)

    paired = False

    # ====================== STRICT MATCHING LOGIC ======================
    if is_gender_mode:
        # Premium gender search → only match exact preferred gender
        preferred = mode

        # 1. Check exact gender pool
        if preferred in available and len(available[preferred]) > 0:
            for i in range(len(available[preferred])):
                candidate = available[preferred][i]
                if candidate != user_id:
                    partner = available[preferred].pop(i)
                    if create_pair(user_id, partner):
                        paired = True
                    break

        # 2. Check RANDOM pool but ONLY if the random user has the exact gender
        if not paired and 'RANDOM' in available and len(available['RANDOM']) > 0:
            for i in range(len(available['RANDOM'])):
                candidate = available['RANDOM'][i]
                if candidate != user_id and get_gender(candidate) == preferred:
                    partner = available['RANDOM'].pop(i)
                    if create_pair(user_id, partner):
                        paired = True
                    break

    else:
        # Random mode → anyone can match anyone
        for src in ['M', 'F', 'RANDOM']:
            if src in available and len(available[src]) > 0:
                for i in range(len(available[src])):
                    candidate = available[src][i]
                    if candidate != user_id:
                        partner = available[src].pop(i)
                        if create_pair(user_id, partner):
                            paired = True
                        break
                if paired:
                    break

    # Reverse seeker check
    if not paired:
        my_gender = gender
        if my_gender in seekers and len(seekers[my_gender]) > 0:
            for i in range(len(seekers[my_gender])):
                seeker = seekers[my_gender][i]
                if seeker != user_id:
                    partner = seekers[my_gender].pop(i)
                    if create_pair(user_id, partner):
                        paired = True
                    break

    # If still no pair → wait
    if not paired:
        seeker_key = mode if is_gender_mode else 'RANDOM'
        if seeker_key not in seekers:
            seekers[seeker_key] = []
        if user_id not in seekers[seeker_key]:
            seekers[seeker_key].append(user_id)

        wait_msg = "⏳ Waiting for match..." if mode == 'RANDOM' else f"⏳ Waiting for {'Male' if mode=='M' else 'Female'}..."
        bot.send_message(user_id, wait_msg, reply_markup=get_main_keyboard(user_id))

# ====================== HANDLERS ======================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.chat.id
    if not get_gender(user_id):
        bot.send_message(user_id, "👋 Welcome to Anonymous Chat!\nChoose your gender:", reply_markup=gender_menu)
    else:
        bot.send_message(user_id, "👋 Welcome back!", reply_markup=get_main_keyboard(user_id))

@bot.message_handler(func=lambda m: m.text in ["Male", "Female"])
def set_gender_handler(message):
    g = 'M' if message.text == "Male" else 'F'
    set_gender(message.chat.id, g)
    bot.send_message(message.chat.id, f"✅ Gender set to {message.text}", reply_markup=get_main_keyboard(message.chat.id))

@bot.message_handler(func=lambda m: m.text == "🎲 Random Chat")
def handle_random(message):
    find_partner(message.chat.id, 'RANDOM')

@bot.message_handler(func=lambda m: m.text == "👨 Find Male")
def handle_male(message):
    find_partner(message.chat.id, 'M')

@bot.message_handler(func=lambda m: m.text == "👩 Find Female")
def handle_female(message):
    find_partner(message.chat.id, 'F')

@bot.message_handler(func=lambda m: m.text == "👤 Change Gender")
def change_gender(message):
    if is_premium(message.chat.id):
        bot.send_message(message.chat.id, "Choose new gender:", reply_markup=gender_menu)
    else:
        bot.send_message(message.chat.id, "Only Premium users can change gender.")

@bot.message_handler(func=lambda m: m.text in ["🔄 Next Chat", "❌ End Chat"])
def chat_control(message):
    user_id = message.chat.id

    if user_id in active_pair:
        end_chat(user_id)
        return

    if user_id in waiting_users:
        cleanup_user(user_id)
        bot.send_message(user_id, "Search stopped.", reply_markup=get_main_keyboard(user_id))
        return

    bot.send_message(user_id, "No active chat.", reply_markup=get_main_keyboard(user_id))

@bot.message_handler(func=lambda m: m.chat.id in active_pair, content_types=['text'])
def relay(message):
    partner = active_pair[message.chat.id]
    bot.send_message(partner, f"💬 {message.text}")

# ====================== PAYMENT ======================
@bot.callback_query_handler(func=lambda call: call.data == "buy_premium")
def buy(call):
    user_id = call.from_user.id
    if is_premium(user_id):
        bot.answer_callback_query(call.id, "You already have Premium!")
        return
    prices = [LabeledPrice("Lifetime Premium", 50)]
    bot.send_invoice(
        call.message.chat.id,
        "Lifetime Premium",
        "Unlimited gender chats + change gender (one-time)",
        "lifetime_prem",
        provider_token="",
        currency="XTR",
        prices=prices
    )

@bot.pre_checkout_query_handler(func=lambda q: True)
def checkout(q):
    bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def success_pay(message):
    if message.successful_payment.invoice_payload == "lifetime_prem":
        set_premium(message.chat.id)
        bot.send_message(message.chat.id,
            "🎉 Lifetime Premium activated!\nYou can now use gender search and change gender.",
            reply_markup=get_main_keyboard(message.chat.id))

print("🤖 Bot is running with your token & admin ID...")
bot.infinity_polling()