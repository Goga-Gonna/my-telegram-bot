import os
import json
import time
import random
import telebot
import threading
from telebot import types
from datetime import datetime, timedelta
from datetime import datetime, timezone

USED_PROMO_FILE = 'used_promo.json'

def get_top_users_by_stars(top_n=10):
    return sorted(USERS.items(), key=lambda x: x[1].get('stars', 0), reverse=True)[:top_n]

def get_top_users_by_referrals(top_n=10):
    return sorted(USERS.items(), key=lambda x: len(x[1].get('referrals', [])), reverse=True)[:top_n]

def load_used_promo():
    try:
        with open(USED_PROMO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_used_promo(data):
    with open(USED_PROMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

USED_PROMO = load_used_promo()  # ← теперь Python знает эту функцию
PROMO_STATE = {}

TOKEN = '7400425001:AAHOaC6IsI7KAhFCRWq1Hk48Esc1rGkN4PI'
BOT_USERNAME = 'Nowsy_bot'  # твой username без @
ADMIN_ID = 1443474084  # <-- замени на свой Telegram ID
bot = telebot.TeleBot(TOKEN)

USERS_FILE = 'users.json'
TASKS_CONFIG_FILE = 'tasks_config.json'
TASKS_STATE_FILE = 'tasks_state.json'

CHANNELS = ['SigmaStore.ua', 'FootballZoneNewsWorld', 'SigmaCommunite', 'sigmenminecraft']
CHANNEL_LINKS = {
    'SigmaStore.ua': 'https://t.me/sigmastoreua',
    'FootballZoneNewsWorld': 'https://t.me/FootballZoneNewsWorld',
    'SigmaCommunite': 'https://t.me/SigmaCommunite',
    'sigmenminecraft': 'https://t.me/sigmenminecraft',
}

USERS = {}
GAMES = {}
BROADCAST_STATE = {}
PROMO_STATE = {}
FEEDBACK_STATE = {}
REPLY_STATE = {}  # admin_id -> user_id to reply


# Промокоды с бонусами и сроком действия
valid_promo_codes = {
    "FREE10": {"bonus": 10, "expires": "2025-12-31"},
    "BONUS20": {"bonus": 20, "expires": "2025-06-30"},
    "SUPER50": {"bonus": 50, "expires": "2025-07-31"},
}

# Новый словарь и переменная для кулдауна всех мини-игр и заданий
COOLDOWNS = {}  # user_id : timestamp последнего запуска мини-игр/заданий
COOLDOWN_SECONDS = 5400  # 1.5 часа в секундах

# Задания состояние — структура: {user_id: {task_id: {"completed": bool, "date": "YYYY-MM-DD"}}}
TASKS_STATE = {}
TASKS_CONFIG = {}

def load_json(file_path, default):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default

def save_json(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_users():
    global USERS
    USERS = load_json(USERS_FILE, {})

def save_users():
    save_json(USERS_FILE, USERS)

def load_tasks_config():
    global TASKS_CONFIG
    TASKS_CONFIG = load_json(TASKS_CONFIG_FILE, {"tasks": []})

def load_tasks_state():
    global TASKS_STATE
    TASKS_STATE = load_json(TASKS_STATE_FILE, {})

def save_tasks_state():
    save_json(TASKS_STATE_FILE, TASKS_STATE)

load_users()
load_tasks_config()
load_tasks_state()

def reset_daily_tasks_if_needed(user_id):
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    user_tasks = TASKS_STATE.get(str(user_id), {})
    changed = False
    for task in TASKS_CONFIG['tasks']:
        task_id = task['id']
        task_data = user_tasks.get(task_id)
        if not task_data or task_data.get('date') != today_str:
            user_tasks[task_id] = {"completed": False, "date": today_str}
            changed = True
    if changed:
        TASKS_STATE[str(user_id)] = user_tasks
        save_tasks_state()

def mark_task_completed(user_id, task_id):
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    TASKS_STATE.setdefault(str(user_id), {})
    TASKS_STATE[str(user_id)][task_id] = {"completed": True, "date": today_str}
    save_tasks_state()

def is_task_completed(user_id, task_id):
    user_tasks = TASKS_STATE.get(str(user_id), {})
    task_data = user_tasks.get(task_id)
    if task_data and task_data.get('completed'):
        # Проверяем дату для ежедневных заданий
        if task_id in ['daily_stars']:
            today_str = datetime.utcnow().strftime('%Y-%m-%d')
            return task_data.get('date') == today_str
        return True
    return False

def check_subscription(user_id):
    for channel in CHANNELS:
        try:
            member = bot.get_chat_member(f'@{channel}', user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception:
            return False
    return True

def register_user(user_id: int, referrer_id: int | None):
    user_id_str = str(user_id)
    if user_id_str not in USERS:
        USERS[user_id_str] = {
            'stars': 0,
            'referrals': [],
            'last_daily_star': 0,
            'referrer': None
        }
        if referrer_id and referrer_id != user_id:
            referrer_id_str = str(referrer_id)
            USERS[user_id_str]['referrer'] = referrer_id_str
            USERS.setdefault(referrer_id_str, {}).setdefault('referrals', [])
            if user_id_str not in USERS[referrer_id_str]['referrals']:
                USERS[referrer_id_str]['referrals'].append(user_id_str)
                USERS.setdefault(referrer_id_str, {}).setdefault('stars', 0)
                USERS[referrer_id_str]['stars'] += 10
        save_users()

def check_user_subscription_or_warn(message):
    if not check_subscription(message.from_user.id):
        bot.send_message(message.chat.id, "❗ Вы не выполнили условия. Сначала подпишитесь на все каналы!")
        return False
    return True

def check_cooldown(user_id, game_key):
    """Кулдаун для каждой игры/задания отдельно"""
    now = time.time()
    if user_id not in COOLDOWNS:
        COOLDOWNS[user_id] = {}
    last_time = COOLDOWNS[user_id].get(game_key, 0)
    if now - last_time < COOLDOWN_SECONDS:
        remaining = int((COOLDOWN_SECONDS - (now - last_time)) / 60)
        return False, remaining
    COOLDOWNS[user_id][game_key] = now
    return True, 0

def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('Бесплатные Звезды', 'Мини-Игры')
    markup.row('Жалоба/Предложения', 'Профиль')
    markup.row('🛍 Магазин', '🏆 Лидеры')  # ← добавили кнопку
    return markup

def free_stars_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('Получить ежедневные звезды', 'Пригласить друзей')
    markup.row('Задания', 'Назад в главное меню')
    return markup

def profile_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row('Статистика', 'Промокод')
    markup.row('Изменить профиль')
    markup.row('Назад в главное меню')
    return markup

def games_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('🎯 Угадай число (1–5)', '🎰 Рулетка')
    markup.row('Назад в главное меню')
    return markup

def purchase_confirmation_keyboard(item_key):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_purchase:{item_key}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_purchase")
    )
    return markup

# --- Обработчики команд и кнопок ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split()
    referrer_id = None
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
        except ValueError:
            pass
    register_user(user_id, referrer_id)
    reset_daily_tasks_if_needed(user_id)
    send_subscription_request(chat_id, user_id)

def send_subscription_request(chat_id, user_id):
    old_msg_id = USERS.get(str(user_id), {}).get('subscription_msg_id')
    old_chat_id = USERS.get(str(user_id), {}).get('subscription_chat_id')
    if old_msg_id and old_chat_id == chat_id:
        try:
            bot.delete_message(old_chat_id, old_msg_id)
        except Exception:
            pass

    markup = types.InlineKeyboardMarkup()
    for channel in CHANNELS:
        url = CHANNEL_LINKS.get(channel, f"https://t.me/{channel}")
        markup.add(types.InlineKeyboardButton(text=f"Канал @{channel}", url=url))
    markup.add(types.InlineKeyboardButton(text="Проверить подписку", callback_data="check_subs"))

    try:
        with open('subscribe.jpg', 'rb') as photo:
            msg = bot.send_photo(
                chat_id,
                photo,
                caption="📢 Чтобы пользоваться ботом, пожалуйста, подпишись на наши каналы:",
                reply_markup=markup
            )
    except:
        msg = bot.send_message(
            chat_id,
            "📢 Чтобы пользоваться ботом, пожалуйста, подпишись на наши каналы:",
            reply_markup=markup
        )

    USERS[str(user_id)] = USERS.get(str(user_id), {})
    USERS[str(user_id)]['subscription_msg_id'] = msg.message_id
    USERS[str(user_id)]['subscription_chat_id'] = chat_id
    save_users()

def get_user_level(stars: int) -> str:
    if stars < 50:
        return "Новичок"
    elif stars < 200:
        return "Опытный"
    else:
        return "Эксперт"

@bot.message_handler(func=lambda message: message.text == 'Статистика')
def profile_stats_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = str(message.from_user.id)
    user_data = USERS.get(user_id, {})

    stars = user_data.get('stars', 0)
    referrals_count = len(user_data.get('referrals', []))
    status = user_data.get('status', 'Обычный пользователь')
    level = get_user_level(stars)

    user_name = message.from_user.first_name or "друг"
    profile_text = (
        f"📊 Статистика профиля {user_name}:\n"
        f"⭐ Баланс звёзд: {stars}\n"
        f"👥 Приглашено друзей: {referrals_count}\n"
        f"🚩 Статус: {status}\n"
        f"🏆 Уровень: {level}"
    )
    bot.send_message(message.chat.id, profile_text)

@bot.message_handler(func=lambda message: message.text == '🏆 Лидеры')
def leaderboard_handler(message):
    top = get_top_users_by_stars()
    lines = ["⭐ Топ по звёздам:"]
    for i, (user_id, data) in enumerate(top, 1):
        name = data.get('name', f"User {user_id}")
        stars = data.get('stars', 0)
        lines.append(f"{i}. {name} — {stars} ⭐")

    top_refs = get_top_users_by_referrals()
    lines.append("\n👥 Топ по приглашениям:")
    for i, (user_id, data) in enumerate(top_refs, 1):
        name = data.get('name', f"User {user_id}")
        count = len(data.get('referrals', []))
        lines.append(f"{i}. {name} — {count} друзей")

    bot.send_message(message.chat.id, "\n".join(lines))

@bot.message_handler(func=lambda m: m.text == 'Изменить профиль')
def edit_profile_handler(message):
    bot.send_message(message.chat.id, "🖋 Напиши текст для био-профиля:")
    PROMO_STATE[message.from_user.id] = 'awaiting_bio'

@bot.message_handler(func=lambda m: PROMO_STATE.get(m.from_user.id) == 'awaiting_bio')
def receive_bio(message):
    USERS[str(message.from_user.id)]['bio'] = message.text
    save_users()
    PROMO_STATE.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "✅ Био-профиль обновлён!")

@bot.message_handler(content_types=['photo'])
def set_profile_avatar(message):
    if PROMO_STATE.get(message.from_user.id) == 'awaiting_avatar':
        USERS[str(message.from_user.id)]['avatar'] = message.photo[-1].file_id
        save_users()
        PROMO_STATE.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, "📷 Аватар обновлён!")

@bot.message_handler(func=lambda m: m.text == 'Установить аватар')
def ask_avatar(message):
    bot.send_message(message.chat.id, "📷 Пришлите фотографию для аватара:")
    PROMO_STATE[message.from_user.id] = 'awaiting_avatar'

@bot.message_handler(func=lambda m: m.text == '🛍 Магазин')
def shop_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    try:
        with open('shop.json', 'r', encoding='utf-8') as f:
            items = json.load(f)

        for item in items:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(f"Купить за {item['price']} ⭐", callback_data=f"buy_{item['id']}"))
            bot.send_message(message.chat.id, f"🎁 {item['name']}\n{item['description']}", reply_markup=markup)
    except Exception as e:
        bot.send_message(message.chat.id, "⚠️ Ошибка загрузки товаров.")
        print(f"Ошибка загрузки магазина: {e}")

@bot.message_handler(func=lambda message: message.text == 'Жалоба/Предложения')
def feedback_request_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = message.from_user.id
    FEEDBACK_STATE[user_id] = True
    bot.send_message(message.chat.id, "✉️ Напишите сюда ваше сообщение. Я передам его администратору.")

@bot.message_handler(func=lambda message: FEEDBACK_STATE.get(message.from_user.id))
def handle_feedback_message(message):
    user_id = message.from_user.id
    FEEDBACK_STATE.pop(user_id, None)

    text = message.text
    user_tag = f"@{message.from_user.username}" if message.from_user.username else "без username"
    feedback_msg = (
        f"📩 Новое сообщение от пользователя {user_id} ({user_tag}):\n\n{text}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{user_id}"),
        types.InlineKeyboardButton("❌ Игнорировать", callback_data="ignore_feedback")
    )
    bot.send_message(ADMIN_ID, feedback_msg, reply_markup=markup)
    bot.send_message(message.chat.id, "✅ Спасибо за сообщение! Мы передадим его администратору.")

@bot.message_handler(func=lambda message: message.text == 'Промокод')
def promo_code_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    PROMO_STATE[message.from_user.id] = 'awaiting_promo_code'
    bot.send_message(message.chat.id, "🎟 Введите ваш промокод:")


@bot.message_handler(func=lambda message: PROMO_STATE.get(message.from_user.id) == 'awaiting_promo_code')
def receive_promo_code(message):
    promo = message.text.strip().upper()
    user_id = str(message.from_user.id)

    if promo not in valid_promo_codes:
        bot.send_message(message.chat.id, "❌ Неверный промокод.")
        PROMO_STATE.pop(message.from_user.id, None)
        return

    # Проверка срока действия
    expire_date = datetime.strptime(valid_promo_codes[promo]["expires"], "%Y-%m-%d").date()
    today = datetime.utcnow().date()
    if today > expire_date:
        bot.send_message(message.chat.id, "❌ Срок действия промокода истёк.")
        PROMO_STATE.pop(message.from_user.id, None)
        return

    # Проверка, использовал ли уже промокод
    if user_id in USED_PROMO and promo in USED_PROMO[user_id]:
        bot.send_message(message.chat.id, "❌ Вы уже использовали этот промокод.")
        PROMO_STATE.pop(message.from_user.id, None)
        return

    # Начисление бонуса
    bonus = valid_promo_codes[promo]["bonus"]
    USERS.setdefault(user_id, {})
    USERS[user_id]['stars'] = USERS[user_id].get('stars', 0) + bonus
    check_star_milestones(user_id)  # если используешь
    save_users()

    # Отмечаем промокод как использованный
    USED_PROMO.setdefault(user_id, [])
    USED_PROMO[user_id].append(promo)
    save_used_promo(USED_PROMO)

    # Отправка картинки, если есть подходящая
    image_path = f"promo_{bonus}.jpg"
    try:
        with open(image_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo, caption=f"✅ Промокод активирован! Вы получили {bonus} звёзд.")
    except Exception as e:
        bot.send_message(message.chat.id, f"✅ Промокод активирован! Вы получили {bonus} звёзд.")
        print(f"❌ Не удалось отправить картинку для {bonus} звёзд: {e}")

    PROMO_STATE.pop(message.from_user.id, None)

@bot.message_handler(func=lambda message: message.text == 'Статус')
def status_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = str(message.from_user.id)
    user_data = USERS.get(user_id, {})
    stars = user_data.get('stars', 0)
    referrals = len(user_data.get('referrals', []))
    # Пример статуса, можно добавить уровни, VIP и т.п.
    status_text = (
        f"📌 Ваш статус:\n"
        f"⭐ Звёзд: {stars}\n"
        f"👥 Приглашено друзей: {referrals}\n"
        f"🎖 Уровень: {'Новичок' if stars < 50 else 'Продвинутый'}"
    )
    bot.send_message(message.chat.id, status_text)

@bot.message_handler(func=lambda message: PROMO_STATE.get(message.from_user.id) == 'awaiting_promo_code')
def receive_promo_code(message):
    promo = message.text.strip().upper()
    user_id = str(message.from_user.id)

    # Пример: простой список валидных промокодов
    valid_promo_codes = {
        "FREE10": 10,
        "BONUS20": 20
    }

    if promo in valid_promo_codes:
        bonus = valid_promo_codes[promo]
        USERS.setdefault(user_id, {})
        USERS[user_id]['stars'] = USERS[user_id].get('stars', 0) + bonus
        save_users()
        bot.send_message(message.chat.id, f"✅ Промокод активирован! Вы получили {bonus} звёзд.")
    else:
        bot.send_message(message.chat.id, "❌ Неверный промокод.")

    PROMO_STATE.pop(message.from_user.id, None)

@bot.message_handler(func=lambda message: message.text == 'Промокод')
def promo_code_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    PROMO_STATE[message.from_user.id] = 'awaiting_promo_code'
    bot.send_message(message.chat.id, "🎟 Введите ваш промокод:") 
@bot.message_handler(func=lambda message: message.text == 'Купить стикер пак')
def buy_sticker_pack(message):
    user_id = str(message.from_user.id)
    item_key = 'sticker_pack'
    item = SHOP.get(item_key)
    if not item:
        bot.send_message(message.chat.id, "❌ Товар не найден.")
        return

    user_stars = USERS.get(user_id, {}).get('stars', 0)
    if user_stars < item['price']:
        bot.send_message(message.chat.id, "❌ У вас недостаточно звёзд для покупки.")
        return

    bot.send_message(
        message.chat.id,
        f"Вы хотите купить {item['name']} за {item['price']} звёзд.\nПодтверждаете покупку?",
        reply_markup=purchase_confirmation_keyboard(item_key)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_') or call.data == 'ignore_feedback')
def handle_feedback_buttons(call):
    if call.data == 'ignore_feedback':
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return

    # Ответить
    user_id = int(call.data.split('_')[1])
    REPLY_STATE[call.from_user.id] = user_id
    bot.send_message(call.message.chat.id, f"💬 Введите сообщение для пользователя {user_id}:")

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_purchase:') or call.data == 'cancel_purchase')
def handle_purchase_confirmation(call):
    user_id = str(call.from_user.id)

    if call.data == 'cancel_purchase':
        bot.answer_callback_query(call.id, "Покупка отменена.")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        return

    item_key = call.data.split(':')[1]
    item = SHOP.get(item_key)
    if not item:
        bot.answer_callback_query(call.id, "Товар не найден.")
        return

    user_stars = USERS.get(user_id, {}).get('stars', 0)
    if user_stars < item['price']:
        bot.answer_callback_query(call.id, "Недостаточно звёзд.")
        return

    USERS[user_id]['stars'] -= item['price']
    save_users()

    if item_key == 'sticker_pack':
        sticker_set_name = item['value']
        bot.send_message(call.message.chat.id, f"Спасибо за покупку! Вот ссылка на стикер-пак: t.me/addstickers/{sticker_set_name}")

    bot.answer_callback_query(call.id, "Покупка успешно выполнена!")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
 
@bot.callback_query_handler(func=lambda call: call.data == "check_subs")
def callback_check_subs(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    if check_subscription(user_id):
        bot.answer_callback_query(call.id, "Подписка подтверждена! Спасибо!")

        user_data = USERS.get(str(user_id), {})
        msg_id = user_data.get('subscription_msg_id')
        if msg_id:
            try:
                bot.delete_message(chat_id, msg_id)
            except:
                pass
            USERS[str(user_id)].pop('subscription_msg_id', None)
            USERS[str(user_id)].pop('subscription_chat_id', None)
            save_users()

        user_name = call.from_user.first_name or "друг"
        facts = (
            " В нашем боте ты найдешь :\n"
            "• Бесплатные звезды/подарки.\n"
            "• Общение,Сливы Софтов и тд\n"
            "• Vip Чаты/Каналы с особым контентом.\n"
        )
        welcome_text = f"Приветствую тебя, {user_name}!\n\n{facts}"

        try:
            with open('welcome.jpg', 'rb') as photo:
                bot.send_photo(chat_id, photo, caption=welcome_text)
        except Exception as e:
            print(f"Ошибка при отправке welcome.jpg: {e}")

        bot.send_message(chat_id, "Главное меню:", reply_markup=main_menu_keyboard())

    else:
        not_subscribed = []
        for channel in CHANNELS:
            try:
                member = bot.get_chat_member(f'@{channel}', user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    not_subscribed.append(channel)
            except Exception:
                not_subscribed.append(channel)

        text = "Ты не подписан на следующие каналы:\n"
        text += '\n'.join([f"@{c}" for c in not_subscribed])
        text += "\n\nПожалуйста, подпишись и нажми кнопку ещё раз."

        bot.answer_callback_query(call.id, "Не подписан на все каналы")
        bot.send_message(chat_id, text)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy(call):
    user_id = str(call.from_user.id)
    item_id = int(call.data.split('_')[1])

    try:
        with open('shop.json', 'r', encoding='utf-8') as f:
            items = json.load(f)
        item = next((i for i in items if i['id'] == item_id), None)
        if not item:
            bot.answer_callback_query(call.id, "❌ Товар не найден.")
            return

        user = USERS.get(user_id, {})
        if user.get('stars', 0) < item['price']:
            bot.answer_callback_query(call.id, "⛔ Недостаточно звёзд.")
            return

        # Вычитаем звезды и сохраняем
        USERS[user_id]['stars'] -= item['price']
        save_users()

        msg = f"✅ Вы купили {item['name']}!"
        if 'link' in item:
            msg += f"\n🧷 Вот ваша ссылка: {item['link']}"
        else:
            msg += "\n📦 Мы свяжемся с вами при необходимости."
        bot.send_message(call.message.chat.id, msg)
        bot.answer_callback_query(call.id)

    except Exception as e:
        bot.send_message(call.message.chat.id, "⚠️ Произошла ошибка при покупке.")
        print(f"Ошибка покупки: {e}")

@bot.message_handler(commands=['broadcast'])
def start_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(message.chat.id, "📤 Отправьте сообщение (текст, фото или видео) для рассылки:")
    BROADCAST_STATE['step'] = 'awaiting_media'

@bot.message_handler(func=lambda message: message.text == 'Бесплатные Звезды')
def free_stars_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    reset_daily_tasks_if_needed(message.from_user.id)
    bot.send_message(message.chat.id, "Меню бесплатных звёзд:", reply_markup=free_stars_menu_keyboard())

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and REPLY_STATE.get(message.from_user.id))
def admin_reply_handler(message):
    target_user_id = REPLY_STATE.pop(message.from_user.id)
    try:
        bot.send_message(target_user_id, f"📬 Ответ от администратора:\n\n{message.text}")
        bot.send_message(message.chat.id, "✅ Ответ отправлен пользователю.")
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Не удалось отправить сообщение пользователю.")
        print(f"Ошибка при отправке ответа: {e}")

@bot.message_handler(func=lambda message: message.text == 'Получить ежедневные звезды')
def daily_stars_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = str(message.from_user.id)
    now = time.time()

    cooldown = 86400  # 24 часа в секундах
    last_claim = USERS.get(user_id, {}).get('last_daily_star', 0)
    if now - last_claim < cooldown:
        remaining = int((cooldown - (now - last_claim)) / 3600)
        bot.send_message(message.chat.id, f"⏳ Вы уже получали звёзды сегодня. Следующий приём через {remaining} часов.")
        return

    USERS.setdefault(user_id, {})
    USERS[user_id]['last_daily_star'] = now
    USERS[user_id]['stars'] = USERS[user_id].get('stars', 0) + 10
    save_users()
    # Помечаем задание выполненным
    mark_task_completed(user_id, "daily_stars")
    bot.send_message(message.chat.id, "🎉 Поздравляем! Вы получили 10 бесплатных звёзд сегодня!")

@bot.message_handler(func=lambda message: message.text == 'Пригласить друзей')
def invite_friends_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = message.from_user.id
    invite_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    bot.send_message(message.chat.id, f"🔗 Приглашайте друзей по ссылке:\n{invite_link}\n\nЗа каждого приглашённого вы получите 10 звёзд!")

@bot.message_handler(func=lambda message: message.text == 'Задания')
def tasks_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = message.from_user.id
    reset_daily_tasks_if_needed(user_id)

    user_tasks = TASKS_STATE.get(str(user_id), {})
    text_lines = ["📋 Ваши задания:\n"]
    for task in TASKS_CONFIG['tasks']:
        task_id = task['id']
        completed = user_tasks.get(task_id, {}).get('completed', False)
        status = "✅ Выполнено" if completed else "❌ Не выполнено"
        text_lines.append(f"{task['title']}: {status}\n{task['description']}\n")
    bot.send_message(message.chat.id, '\n'.join(text_lines))

@bot.message_handler(func=lambda message: message.text == 'Назад в главное меню')
def back_to_main_menu_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == 'Профиль')
def profile_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    bot.send_message(message.chat.id, "Вы в профиле. Выберите опцию:", reply_markup=profile_menu_keyboard())

@bot.message_handler(func=lambda message: message.text in ['Статистика', 'Назад в главное меню'])
def profile_submenu_handler(message):
    if not check_user_subscription_or_warn(message):
        return

    if message.text == 'Статистика':
        user_id = str(message.from_user.id)
        user_data = USERS.get(user_id, {})
        stars = user_data.get('stars', 0)
        referrals_count = len(user_data.get('referrals', []))
        user_name = message.from_user.first_name or "друг"
        bio = user_data.get('bio', 'не указано')
        status = user_data.get('status', 'обычный')
        level = user_data.get('level', 1)

        profile_text = (
            f"📊 Статистика профиля {user_name}:\n"
            f"⭐ Баланс звёзд: {stars}\n"
            f"👥 Приглашено друзей: {referrals_count}\n"
            f"💼 Статус: {status}\n"
            f"📈 Уровень: {level}\n"
            f"📝 Био: {bio}"
        )

        avatar = user_data.get('avatar')
        if avatar:
            bot.send_photo(message.chat.id, avatar, caption=profile_text)
        else:
            bot.send_message(message.chat.id, profile_text)

        bot.send_message(message.chat.id, profile_text)
    else:
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda message: message.text == 'Мини-Игры')
def games_menu_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    bot.send_message(message.chat.id, "Выберите мини-игру:", reply_markup=games_menu_keyboard())

# --- Мини-игра "Угадай число" ---
@bot.message_handler(func=lambda message: message.text == '🎯 Угадай число (1–5)')
def start_guess_game(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = message.from_user.id
    ok, remain = check_cooldown(user_id, 'guess_number')
    if not ok:
        bot.send_message(message.chat.id, f"⏳ Подождите {remain} минут перед следующей игрой.")
        return
    GAMES[user_id] = random.randint(1, 5)
    bot.send_message(message.chat.id, "🔢 Я загадал число от 1 до 5. Попробуй угадать!")

@bot.message_handler(func=lambda message: message.from_user.id in GAMES)
def guess_game_handler(message):
    user_id = message.from_user.id
    try:
        guess = int(message.text)
    except ValueError:
        bot.send_message(message.chat.id, "❗ Пожалуйста, отправьте число от 1 до 5.")
        return

    number = GAMES.get(user_id)
    if guess == number:
        USERS.setdefault(str(user_id), {})
        USERS[str(user_id)]['stars'] = USERS[str(user_id)].get('stars', 0) + 10
        save_users()
        bot.send_message(message.chat.id, "🎉 Поздравляю! Вы угадали число и получили 10 звёзд!")
        mark_task_completed(user_id, 'guess_number')
    else:
        bot.send_message(message.chat.id, f"❌ Неверно, загаданное число было {number}. Попробуйте ещё раз через 1,5 часа.")
    GAMES.pop(user_id, None)

# --- Мини-игра "Рулетка" ---
@bot.message_handler(func=lambda message: message.text == '🎰 Рулетка')
def start_roulette_game(message):
    if not check_user_subscription_or_warn(message):
        return
    user_id = message.from_user.id
    ok, remain = check_cooldown(user_id, 'roulette_play')
    if not ok:
        bot.send_message(message.chat.id, f"⏳ Подождите {remain} минут перед следующей игрой.")
        return

    prize = random.choices([0, 10, 20], weights=[50, 40, 10], k=1)[0]

    def send_result():
        if prize == 0:
            bot.send_message(message.chat.id, "😞 Вы проиграли. Попробуйте ещё раз через 1,5 часа.")
        else:
            USERS.setdefault(str(user_id), {})
            USERS[str(user_id)]['stars'] = USERS[str(user_id)].get('stars', 0) + prize
            save_users()
            bot.send_message(message.chat.id, f"🎉 Поздравляем! Вы выиграли {prize} звёзд!")
        mark_task_completed(user_id, 'roulette_play')

    video_path = 'win.mp4' if prize > 0 else 'lose.mp4'
    try:
        with open(video_path, 'rb') as video:
            bot.send_video(message.chat.id, video)
    except Exception as e:
        bot.send_message(message.chat.id, "⚠️ Не удалось отправить видео.")

    # Отложенное сообщение через 4 секунды
    threading.Timer(4.0, send_result).start()

@bot.message_handler(func=lambda message: True)
def fallback_handler(message):
    if not check_user_subscription_or_warn(message):
        return
    bot.send_message(message.chat.id, "❓ Команда не распознана. Пожалуйста, используйте меню.", reply_markup=main_menu_keyboard())

# --- Логика рассылки для админа ---
@bot.message_handler(func=lambda message: BROADCAST_STATE.get('step') == 'awaiting_media' and message.from_user.id == ADMIN_ID)
def handle_broadcast_media(message):
    if message.content_type in ['text', 'photo', 'video']:
        BROADCAST_STATE['step'] = 'awaiting_confirm'
        BROADCAST_STATE['media'] = message
        bot.send_message(message.chat.id, "Подтвердите рассылку? (Да/Нет)")
    else:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте текст, фото или видео.")

@bot.message_handler(func=lambda message: BROADCAST_STATE.get('step') == 'awaiting_confirm' and message.from_user.id == ADMIN_ID)
def handle_broadcast_confirm(message):
    if message.text.lower() == 'да':
        BROADCAST_STATE['step'] = None
        media = BROADCAST_STATE.get('media')
        if media:
            count = 0
            for user_id_str in USERS.keys():
                try:
                    uid = int(user_id_str)
                    if media.content_type == 'text':
                        bot.send_message(uid, media.text)
                    elif media.content_type == 'photo':
                        bot.send_photo(uid, media.photo[-1].file_id, caption=media.caption)
                    elif media.content_type == 'video':
                        bot.send_video(uid, media.video.file_id, caption=media.caption)
                    count += 1
                except Exception as e:
                    print(f"Ошибка при рассылке пользователю {user_id_str}: {e}")
            bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Отправлено сообщений: {count}")
        else:
            bot.send_message(ADMIN_ID, "Ошибка: медиа для рассылки не найдено.")
    elif message.text.lower() == 'нет':
        BROADCAST_STATE['step'] = None
        bot.send_message(ADMIN_ID, "Рассылка отменена.")
    else:
        bot.send_message(ADMIN_ID, "Пожалуйста, ответьте 'Да' или 'Нет'.")

# --- Дополнительная логика: отслеживаем приглашения (рефералы) для задания "invite_friend" ---
# В функции register_user уже добавлена логика начисления рефералов.
# Помечаем задание выполненным, если у пользователя есть хотя бы 1 реферал.

def check_invite_task_completion(user_id):
    user_data = USERS.get(str(user_id), {})
    referrals = user_data.get('referrals', [])
    if referrals:
        mark_task_completed(user_id, 'invite_friend')

# Вызовем при каждой команде, где возможно обновление
@bot.message_handler(func=lambda message: True)
def catch_all_handler(message):
    user_id = message.from_user.id
    if not check_user_subscription_or_warn(message):
        return

    # Обновляем статус задания "invite_friend"
    check_invite_task_completion(user_id)
    # Отправляем fallback, если не было обработано
    # Чтобы избежать конфликтов с другими обработчиками,
    # пропускаем, если текст совпал с командами выше.
    known_cmds = ['Бесплатные Звезды', 'Получить ежедневные звезды', 'Пригласить друзей',
                  'Задания', 'Назад в главное меню', 'Профиль', 'Статистика',
                  'Мини-Игры', '🎯 Угадай число (1–5)', '🎰 Рулетка']
    if message.text not in known_cmds:
        bot.send_message(message.chat.id, "❓ Команда не распознана. Пожалуйста, используйте меню.", reply_markup=main_menu_keyboard())

print("Бот запущен...")
bot.infinity_polling()
