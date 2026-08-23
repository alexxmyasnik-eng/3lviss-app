"""
Telegram-бот обратной связи и приёма заявок.
Библиотека: aiogram 3.x

Что умеет:
1. /start — приветствие + правила.
2. Пользователь отправляет кружок/гс/видео/фото как ВЫПОЛНЕНИЕ ЗАДАНИЯ —
   уходит админу с юзернеймом/ником и кнопками "Выдать 💎" / "Отказать".
   - Выдать 💎: админ вводит сумму -> баланс и счётчик заданий растут,
     пользователю приходит уведомление.
   - Отказать: админ вводит причину -> пользователю приходит уведомление,
     счётчик заданий НЕ растёт.
3. Любые другие сообщения (текст, документы) пересылаются админу как раньше,
   ответ — через reply в Telegram.
4. У пользователей есть кнопки "👤 Профиль" (баланс + кол-во заданий) и
   "🛒 Магазин" (подарки за 💎). Покупка подарка уходит уведомлением админу.
5. Админ-панель (/admin): бан (временный/навсегда), разбан, список забаненных,
   список балансов всех, ручная выдача 💎 любому пользователю.

Установка зависимостей:
    pip install aiogram==3.* aiohttp

Переменные окружения (задаются на хостинге, например Render):
    BOT_TOKEN  — токен бота от @BotFather
    ADMIN_ID   — числовой Telegram ID администратора
    PORT       — порт для веб-сервера (Render подставляет автоматически)

Запуск:
    python feedback_bot.py

ВАЖНО ПРО RENDER:
Render Web Service ждёт, что приложение откроет HTTP-порт, иначе деплой
падает по таймауту, а сервис засыпает при неактивности. Поэтому здесь
поднят простой aiohttp-сервер на "/", который:
  - открывает порт (чтобы Render не убивал деплой по таймауту);
  - отвечает 200 OK на пинги cron-job.org (чтобы инстанс не засыпал).
На cron-job.org настрой пинг GET-запросом на твой URL каждые 5 минут.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any

from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

# ==================== НАСТРОЙКИ (ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ) ====================

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
PORT = int(os.environ.get("PORT", 10000))

DATA_FILE = "data.json"

# =============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()

# message_id (пересланного/оповещённого сообщения у админа) -> user_id
# используется для classic reply-ответов на обычные (не-задачные) сообщения
forwarded_map: dict[int, int] = {}

# Впишите ссылку на вступление прямо в текст ниже (вручную).
WELCOME_TEXT = (
    "Привет! Добро пожаловать 👋\n"
    "Это не просто бот, а твой личный анонимный чат с Администратором.\n"
    "📌 Что делать дальше:\n"
    "Подай заявку на вступление в закрытый канал по ссылке ниже.\n"
    "Дальше бот - ваша личная переписка с Администратором\n"
    "В закрытом канале будут выходить задания, а все выполненные фото/видео отчеты ты будешь отправлять прямо в этот чат. Всё полностью анонимно.\n"
    "🔗 Ссылка на приватный канал: https://t.me/+w_L1inSVwUc2YTU1"
)

SHOP_ITEMS = [
    {"stars": 15, "price": 30},
    {"stars": 25, "price": 50},
    {"stars": 50, "price": 100},
    {"stars": 100, "price": 175},
]

# ==================== ХРАНИЛИЩЕ ДАННЫХ (JSON-файл) ====================

_data_lock = asyncio.Lock()


def _load_data() -> dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"users": {}}


def _save_data(data: dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def get_user(user_id: int, username: str | None = None, full_name: str | None = None) -> dict[str, Any]:
    """Возвращает запись пользователя, создавая её при первом обращении."""
    async with _data_lock:
        data = _load_data()
        uid = str(user_id)
        if uid not in data["users"]:
            data["users"][uid] = {
                "username": username,
                "full_name": full_name,
                "balance": 0,
                "completed": 0,
                "ban_until": None,  # None | "forever" | timestamp (float)
                "ban_reason": None,
            }
            _save_data(data)
        else:
            # обновляем актуальные username/full_name
            changed = False
            if username is not None and data["users"][uid].get("username") != username:
                data["users"][uid]["username"] = username
                changed = True
            if full_name is not None and data["users"][uid].get("full_name") != full_name:
                data["users"][uid]["full_name"] = full_name
                changed = True
            if changed:
                _save_data(data)
        return data["users"][uid]


async def update_user(user_id: int, **fields: Any) -> None:
    async with _data_lock:
        data = _load_data()
        uid = str(user_id)
        if uid not in data["users"]:
            data["users"][uid] = {
                "username": None,
                "full_name": None,
                "balance": 0,
                "completed": 0,
                "ban_until": None,
                "ban_reason": None,
            }
        data["users"][uid].update(fields)
        _save_data(data)


async def add_balance(user_id: int, amount: int, add_completed: bool = False) -> int:
    async with _data_lock:
        data = _load_data()
        uid = str(user_id)
        if uid not in data["users"]:
            data["users"][uid] = {
                "username": None,
                "full_name": None,
                "balance": 0,
                "completed": 0,
                "ban_until": None,
                "ban_reason": None,
            }
        data["users"][uid]["balance"] = data["users"][uid].get("balance", 0) + amount
        if add_completed:
            data["users"][uid]["completed"] = data["users"][uid].get("completed", 0) + 1
        _save_data(data)
        return data["users"][uid]["balance"]


async def get_all_users() -> dict[str, Any]:
    async with _data_lock:
        data = _load_data()
        return data["users"]


def ban_status(user: dict[str, Any]) -> tuple[bool, str]:
    """Возвращает (забанен_ли_сейчас, человекочитаемый текст статуса)."""
    ban_until = user.get("ban_until")
    if ban_until is None:
        return False, "не забанен"
    if ban_until == "forever":
        return True, "забанен навсегда"
    if isinstance(ban_until, (int, float)):
        if time.time() < ban_until:
            remaining = int(ban_until - time.time())
            mins = remaining // 60
            secs = remaining % 60
            return True, f"забанен ещё на {mins} мин {secs} сек"
        return False, "не забанен"
    return False, "не забанен"


# ==================== FSM СОСТОЯНИЯ АДМИНА ====================

class AdminStates(StatesGroup):
    waiting_task_amount = State()   # ввод суммы 💎 по конкретному заданию
    waiting_task_reason = State()   # ввод причины отказа по конкретному заданию
    waiting_ban_id = State()        # ввод id для бана
    waiting_ban_duration = State()  # ввод длительности бана
    waiting_unban_id = State()      # ввод id для разбана
    waiting_give_id = State()       # ввод id для ручной выдачи 💎
    waiting_give_amount = State()   # ввод суммы для ручной выдачи 💎


# ==================== КЛАВИАТУРЫ ====================

def user_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🛒 Магазин")],
        ],
        resize_keyboard=True,
    )


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],
            [KeyboardButton(text="📋 Забаненные"), KeyboardButton(text="📊 Балансы")],
            [KeyboardButton(text="💎 Выдать 💎")],
        ],
        resize_keyboard=True,
    )


def task_decision_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💎 Выдать 💎", callback_data=f"task_ok:{user_id}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"task_no:{user_id}"),
            ]
        ]
    )


def shop_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎁 Подарок {item['stars']}⭐ — {item['price']}💎",
                callback_data=f"buy:{item['stars']}:{item['price']}",
            )
        ]
        for item in SHOP_ITEMS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id == ADMIN_ID


# ==================== /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if _is_admin(message):
        await message.answer("Админ-панель готова 👇", reply_markup=admin_main_keyboard())
        return

    user = message.from_user
    await get_user(user.id, user.username, user.full_name)

    banned, status_text = ban_status(await get_user(user.id))
    if banned:
        await message.answer(f"⛔ Вы забанены. Статус: {status_text}")
        return

    await message.answer(WELCOME_TEXT, reply_markup=user_main_keyboard())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message):
        return
    await message.answer("Админ-панель:", reply_markup=admin_main_keyboard())


# ==================== ПРОФИЛЬ / МАГАЗИН (для пользователей) ====================

@router.message(F.from_user.id != ADMIN_ID, F.text == "👤 Профиль")
async def show_profile(message: Message) -> None:
    user_data = await get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    banned, status_text = ban_status(user_data)
    text = (
        f"👤 Ваш профиль\n"
        f"💎 Баланс: {user_data.get('balance', 0)}\n"
        f"✅ Выполнено заданий: {user_data.get('completed', 0)}\n"
    )
    if banned:
        text += f"⛔ Статус: {status_text}\n"
    await message.answer(text)


@router.message(F.from_user.id != ADMIN_ID, F.text == "🛒 Магазин")
async def show_shop(message: Message) -> None:
    user_data = await get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    banned, _ = ban_status(user_data)
    if banned:
        await message.answer("⛔ Вы забанены, магазин недоступен.")
        return
    await message.answer(
        f"🛒 Магазин подарков (ваш баланс: {user_data.get('balance', 0)}💎):",
        reply_markup=shop_keyboard(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def handle_buy(callback: CallbackQuery, bot: Bot) -> None:
    _, stars_str, price_str = callback.data.split(":")
    stars, price = int(stars_str), int(price_str)

    user = callback.from_user
    user_data = await get_user(user.id, user.username, user.full_name)
    banned, _ = ban_status(user_data)
    if banned:
        await callback.answer("⛔ Вы забанены.", show_alert=True)
        return

    if user_data.get("balance", 0) < price:
        await callback.answer("❌ Недостаточно 💎 на балансе.", show_alert=True)
        return

    new_balance = await add_balance(user.id, -price)
    await callback.answer("✅ Покупка оформлена!", show_alert=True)
    await callback.message.answer(
        f"🎉 Вы купили подарок {stars}⭐ за {price}💎.\nВаш новый баланс: {new_balance}💎"
    )

    await bot.send_message(
        ADMIN_ID,
        f"🎁 Покупка подарка\n"
        f"От: {user.full_name} (@{user.username or 'без username'})\n"
        f"ID: {user.id}\n"
        f"Подарок: {stars}⭐ за {price}💎\n"
        f"Остаток на балансе: {new_balance}💎",
    )


# ==================== ЗАДАНИЯ: приём кружка/гс/видео/фото ====================

@router.message(
    F.from_user.id != ADMIN_ID,
    F.content_type.in_({"photo", "video", "video_note", "voice"}),
)
async def handle_task_submission(message: Message, bot: Bot) -> None:
    user = message.from_user
    user_data = await get_user(user.id, user.username, user.full_name)
    banned, status_text = ban_status(user_data)
    if banned:
        await message.answer(f"⛔ Вы забанены. Статус: {status_text}")
        return

    header = (
        f"📩 Новое выполненное задание\n"
        f"От: {user.full_name} (@{user.username or 'без username'})\n"
        f"ID: {user.id}\n"
    )

    try:
        existing_caption = message.caption or ""
        new_caption = f"{header}\n{existing_caption}".strip()
        sent = await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=new_caption if message.content_type != "video_note" else None,
        )
        # video_note нельзя отправить с caption, поэтому шапку шлём отдельным сообщением
        if message.content_type == "video_note":
            await bot.send_message(ADMIN_ID, header)

        await bot.send_message(
            ADMIN_ID,
            "👆 Решение по заданию:",
            reply_markup=task_decision_keyboard(user.id),
        )
    except Exception as e:
        logger.error(f"Ошибка при пересылке задания от {user.id}: {e}")


@router.callback_query(F.data.startswith("task_ok:"))
async def handle_task_approve(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=user_id, task_message_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_task_amount)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"💎 Введите сумму 💎 для выдачи пользователю {user_id}:")
    await callback.answer()


@router.callback_query(F.data.startswith("task_no:"))
async def handle_task_reject(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=user_id, task_message_id=callback.message.message_id)
    await state.set_state(AdminStates.waiting_task_reason)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Введите причину отказа для пользователя {user_id}:")
    await callback.answer()


@router.message(StateFilter(AdminStates.waiting_task_amount), F.from_user.id == ADMIN_ID)
async def process_task_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    user_id = data["target_user_id"]

    if not message.text or not message.text.strip().lstrip("-").isdigit():
        await message.answer("⚠️ Введите число (сумму 💎).")
        return

    amount = int(message.text.strip())
    new_balance = await add_balance(user_id, amount, add_completed=True)
    await state.clear()

    await message.answer(f"✅ Начислено {amount}💎 пользователю {user_id}. Новый баланс: {new_balance}💎")
    try:
        await bot.send_message(
            user_id,
            f"✅ Ваше задание принято!\nНачислено: {amount}💎",
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")


@router.message(StateFilter(AdminStates.waiting_task_reason), F.from_user.id == ADMIN_ID)
async def process_task_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    user_id = data["target_user_id"]

    reason = message.text or "без указания причины"
    await state.clear()

    await message.answer(f"❌ Отказ отправлен пользователю {user_id}.")
    try:
        await bot.send_message(
            user_id,
            f"❌ Ваше задание отклонено.\nПричина: {reason}",
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")


# ==================== АДМИН-ПАНЕЛЬ: БАН / РАЗБАН / СПИСКИ / ВЫДАЧА ====================

@router.message(F.from_user.id == ADMIN_ID, F.text == "🚫 Забанить")
async def admin_ban_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_ban_id)
    await message.answer("Введите ID пользователя, которого нужно забанить:")


@router.message(StateFilter(AdminStates.waiting_ban_id), F.from_user.id == ADMIN_ID)
async def admin_ban_id(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой ID.")
        return
    await state.update_data(ban_target_id=int(message.text.strip()))
    await state.set_state(AdminStates.waiting_ban_duration)
    await message.answer(
        "На сколько минут забанить? Введите число минут, либо слово 'навсегда' для вечного бана.\n"
        "Можно также добавить причину через пробел, например: 60 спам"
    )


@router.message(StateFilter(AdminStates.waiting_ban_duration), F.from_user.id == ADMIN_ID)
async def admin_ban_duration(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    target_id = data["ban_target_id"]

    parts = (message.text or "").strip().split(maxsplit=1)
    if not parts:
        await message.answer("⚠️ Введите длительность бана.")
        return

    duration_part = parts[0].lower()
    reason = parts[1] if len(parts) > 1 else None

    if duration_part in ("навсегда", "forever", "нав"):
        await update_user(target_id, ban_until="forever", ban_reason=reason)
        await message.answer(f"🚫 Пользователь {target_id} забанен навсегда." + (f" Причина: {reason}" if reason else ""))
        try:
            await bot.send_message(target_id, "⛔ Вы забанены навсегда." + (f"\nПричина: {reason}" if reason else ""))
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {target_id}: {e}")
    elif duration_part.isdigit():
        minutes = int(duration_part)
        ban_until = time.time() + minutes * 60
        await update_user(target_id, ban_until=ban_until, ban_reason=reason)
        await message.answer(
            f"🚫 Пользователь {target_id} забанен на {minutes} мин." + (f" Причина: {reason}" if reason else "")
        )
        try:
            await bot.send_message(
                target_id,
                f"⛔ Вы забанены на {minutes} мин." + (f"\nПричина: {reason}" if reason else ""),
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {target_id}: {e}")
    else:
        await message.answer("⚠️ Введите число минут или слово 'навсегда'.")
        return

    await state.clear()


@router.message(F.from_user.id == ADMIN_ID, F.text == "✅ Разбанить")
async def admin_unban_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_unban_id)
    await message.answer("Введите ID пользователя, которого нужно разбанить:")


@router.message(StateFilter(AdminStates.waiting_unban_id), F.from_user.id == ADMIN_ID)
async def admin_unban_id(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой ID.")
        return
    target_id = int(message.text.strip())
    await update_user(target_id, ban_until=None, ban_reason=None)
    await state.clear()
    await message.answer(f"✅ Пользователь {target_id} разбанен.")
    try:
        await bot.send_message(target_id, "✅ Вы разбанены, можете продолжать пользоваться ботом.")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {target_id}: {e}")


@router.message(F.from_user.id == ADMIN_ID, F.text == "📋 Забаненные")
async def admin_banned_list(message: Message) -> None:
    users = await get_all_users()
    lines = []
    for uid, u in users.items():
        banned, status_text = ban_status(u)
        if banned:
            uname = f"@{u.get('username')}" if u.get("username") else "без username"
            reason = u.get("ban_reason")
            line = f"ID {uid} ({uname}) — {status_text}"
            if reason:
                line += f", причина: {reason}"
            lines.append(line)

    if not lines:
        await message.answer("✅ Забаненных пользователей нет.")
    else:
        await message.answer("🚫 Забаненные пользователи:\n" + "\n".join(lines))


@router.message(F.from_user.id == ADMIN_ID, F.text == "📊 Балансы")
async def admin_balances_list(message: Message) -> None:
    users = await get_all_users()
    if not users:
        await message.answer("Пользователей пока нет.")
        return

    lines = []
    for uid, u in users.items():
        uname = f"@{u.get('username')}" if u.get("username") else "без username"
        lines.append(
            f"ID {uid} ({uname}) — 💎{u.get('balance', 0)}, заданий: {u.get('completed', 0)}"
        )

    # Разбиваем на части, если сообщение слишком длинное
    text = "📊 Балансы пользователей:\n" + "\n".join(lines)
    for chunk_start in range(0, len(text), 3500):
        await message.answer(text[chunk_start:chunk_start + 3500])


@router.message(F.from_user.id == ADMIN_ID, F.text == "💎 Выдать 💎")
async def admin_give_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_give_id)
    await message.answer("Введите ID пользователя, которому выдать 💎:")


@router.message(StateFilter(AdminStates.waiting_give_id), F.from_user.id == ADMIN_ID)
async def admin_give_id(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой ID.")
        return
    await state.update_data(give_target_id=int(message.text.strip()))
    await state.set_state(AdminStates.waiting_give_amount)
    await message.answer("Введите сумму 💎 (можно отрицательную, чтобы списать):")


@router.message(StateFilter(AdminStates.waiting_give_amount), F.from_user.id == ADMIN_ID)
async def admin_give_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    target_id = data["give_target_id"]

    if not message.text or not message.text.strip().lstrip("-").isdigit():
        await message.answer("⚠️ Введите число.")
        return

    amount = int(message.text.strip())
    new_balance = await add_balance(target_id, amount, add_completed=False)
    await state.clear()

    await message.answer(f"✅ Баланс пользователя {target_id} изменён на {amount}💎. Новый баланс: {new_balance}💎")
    try:
        if amount >= 0:
            await bot.send_message(target_id, f"🎁 Вам начислено {amount}💎 администратором.\nВаш баланс: {new_balance}💎")
        else:
            await bot.send_message(target_id, f"⚠️ С вашего баланса списано {-amount}💎.\nВаш баланс: {new_balance}💎")
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {target_id}: {e}")


# ==================== ОТВЕТ АДМИНА ПОЛЬЗОВАТЕЛЮ (classic reply) ====================
# Срабатывает на обычный reply к пересланному сообщению пользователя
# (не задачное, т.е. не фото/видео/кружок/гс с кнопками решения).

@router.message(F.from_user.id == ADMIN_ID, F.reply_to_message, StateFilter(None))
async def admin_reply_handler(message: Message, bot: Bot) -> None:
    replied_id = message.reply_to_message.message_id

    user_id = forwarded_map.get(replied_id)

    if user_id is None:
        return

    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as e:
        logger.error(f"Не удалось отправить ответ пользователю {user_id}: {e}")
        await message.reply(f"❌ Не удалось отправить ответ: {e}")


# ==================== ПЕРЕСЫЛКА ПРОЧИХ СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЯ АДМИНУ ====================

@router.message(F.from_user.id != ADMIN_ID, StateFilter(None))
async def forward_to_admin(message: Message, bot: Bot) -> None:
    """
    Пересылает обычное сообщение пользователя (текст, документ и т.п.)
    администратору ОДНИМ сообщением и добавляет возможность classic reply.
    Пользователю никакого подтверждения не отправляется.
    """
    user = message.from_user
    user_data = await get_user(user.id, user.username, user.full_name)
    banned, status_text = ban_status(user_data)
    if banned:
        await message.answer(f"⛔ Вы забанены. Статус: {status_text}")
        return

    header = (
        f"📩 Новое сообщение\n"
        f"От: {user.full_name} (@{user.username or 'без username'})\n"
        f"ID: {user.id}\n"
    )

    try:
        if message.text:
            sent = await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"{header}\n{message.text}",
            )
        else:
            existing_caption = message.caption or ""
            new_caption = f"{header}\n{existing_caption}".strip()
            sent = await bot.copy_message(
                chat_id=ADMIN_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                caption=new_caption,
            )

        forwarded_map[sent.message_id] = user.id

    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения от {user.id}: {e}")


# ==================== МИНИ-ВЕБ-СЕРВЕР (для Render / cron-job.org) ====================

async def handle_ping(request: web.Request) -> web.Response:
    return web.Response(text="Bot is running")


async def start_webserver() -> None:
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {PORT}")


# ==================== ТОЧКА ВХОДА ====================

async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await start_webserver()

    logger.info("Бот запущен.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
