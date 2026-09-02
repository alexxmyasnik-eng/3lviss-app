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
   список балансов всех (без заблокировавших бота), ручная выдача 💎 любому
   пользователю, глобальная рассылка всем пользователям.
6. При первом /start пользователя админ получает уведомление о новичке.
7. Если пользователь заблокировал бота, он помечается "blocked" и пропадает
   из списка "Балансы"; при повторном обращении к боту (например, разблокировал
   и написал заново) помечается снова активным.

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
from aiogram.exceptions import TelegramForbiddenError
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


async def user_exists(user_id: int) -> bool:
    """Проверяет, есть ли уже запись о пользователе (не создавая её)."""
    async with _data_lock:
        data = _load_data()
        return str(user_id) in data["users"]


async def get_user(user_id: int, username: str | None = None, full_name: str | None = None) -> dict[str, Any]:
    """Возвращает запись пользователя, создавая её при первом обращении.
    Вызывается только из хендлеров реальной активности пользователя, поэтому
    здесь же сбрасываем флаг "blocked" — раз пользователь взаимодействует
    с ботом, значит бот у него не заблокирован."""
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
                "blocked": False,
            }
            _save_data(data)
        else:
            changed = False
            if username is not None and data["users"][uid].get("username") != username:
                data["users"][uid]["username"] = username
                changed = True
            if full_name is not None and data["users"][uid].get("full_name") != full_name:
                data["users"][uid]["full_name"] = full_name
                changed = True
            if data["users"][uid].get("blocked"):
                data["users"][uid]["blocked"] = False
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
                "blocked": False,
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
                "blocked": False,
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


async def get_shop_prices() -> dict[str, dict[str, int | None]]:
    """Возвращает текущие цены магазина. Формат:
    { "15": {"price": 30, "old_price": None}, "25": {...}, ... }
    Ключ — количество звёзд (stars) как строка.
    Если в data.json ещё ничего не сохранено — берём значения из SHOP_ITEMS."""
    async with _data_lock:
        data = _load_data()
        prices = data.get("shop_prices")
        if not prices:
            prices = {
                str(item["stars"]): {"price": item["price"], "old_price": None}
                for item in SHOP_ITEMS
            }
            data["shop_prices"] = prices
            _save_data(data)
        return prices


async def set_shop_price(stars: int, new_price: int, discount: bool = False) -> None:
    """Устанавливает новую цену для позиции с данным количеством звёзд.
    Если discount=True — текущая цена сохраняется как old_price (зачёркнутая),
    иначе old_price сбрасывается (скидка снята)."""
    async with _data_lock:
        data = _load_data()
        prices = data.get("shop_prices")
        if not prices:
            prices = {
                str(item["stars"]): {"price": item["price"], "old_price": None}
                for item in SHOP_ITEMS
            }
        key = str(stars)
        if key not in prices:
            prices[key] = {"price": new_price, "old_price": None}
        else:
            current_price = prices[key]["price"]
            prices[key]["old_price"] = current_price if discount else None
            prices[key]["price"] = new_price
        data["shop_prices"] = prices
        _save_data(data)


async def notify_user(bot: Bot, user_id: int, text: str) -> bool:
    """Отправляет сообщение пользователю. Если бот у него заблокирован —
    помечает это в базе и возвращает False, ничего не выбрасывая наружу."""
    try:
        await bot.send_message(user_id, text)
        return True
    except TelegramForbiddenError:
        await update_user(user_id, blocked=True)
        logger.info(f"Пользователь {user_id} заблокировал бота.")
        return False
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        return False


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
    waiting_broadcast = State()     # ввод текста глобальной рассылки
    waiting_add_completed_id = State()      # ввод id для ручного добавления к счётчику заданий
    waiting_add_completed_amount = State()  # ввод количества для добавления к счётчику заданий
    waiting_price_stars = State()     # админ выбирает, у какой позиции менять цену
    waiting_price_value = State()     # ввод новой цены
    waiting_price_discount = State()  # да/нет — показывать ли старую цену зачёркнутой


class SuggestTaskStates(StatesGroup):
    waiting_description = State()  # пользователь вводит описание предлагаемого задания
    waiting_media = State()        # пользователь присылает медиа выполнения этого задания


# ==================== КЛАВИАТУРЫ ====================

def user_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🛒 Магазин")],
            [KeyboardButton(text="💡 Предложить задание")],
        ],
        resize_keyboard=True,
    )


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить")],
            [KeyboardButton(text="📋 Забаненные"), KeyboardButton(text="📊 Балансы")],
            [KeyboardButton(text="💎 Выдать 💎"), KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="➕ Добавить заданий"), KeyboardButton(text="🏷 Изменить цены")],
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


def suggested_task_decision_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"suggest_ok:{user_id}"),
                InlineKeyboardButton(text="❌ Не принять", callback_data=f"suggest_no:{user_id}"),
            ]
        ]
    )


def shop_keyboard(prices: dict[str, dict[str, int | None]]) -> InlineKeyboardMarkup:
    rows = []
    for item in SHOP_ITEMS:
        key = str(item["stars"])
        entry = prices.get(key, {"price": item["price"], "old_price": None})
        price = entry["price"]
        old_price = entry.get("old_price")
        if old_price:
            label = f"🎁 {item['stars']}⭐ — ~{old_price}~ {price}💎"
        else:
            label = f"🎁 Подарок {item['stars']}⭐ — {price}💎"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"buy:{item['stars']}:{price}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_admin(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id == ADMIN_ID


# ==================== /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    if _is_admin(message):
        await message.answer("Админ-панель готова 👇", reply_markup=admin_main_keyboard())
        return

    user = message.from_user
    is_new = not await user_exists(user.id)
    user_data = await get_user(user.id, user.username, user.full_name)

    if is_new:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🆕 Новый пользователь запустил бота\n"
                f"Имя: {user.full_name} (@{user.username or 'без username'})\n"
                f"ID: {user.id}",
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа о новом пользователе: {e}")

    banned, status_text = ban_status(user_data)
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

    prices = await get_shop_prices()
    lines = [f"🛒 Магазин подарков (ваш баланс: {user_data.get('balance', 0)}💎):", ""]
    for item in SHOP_ITEMS:
        entry = prices.get(str(item["stars"]), {"price": item["price"], "old_price": None})
        price = entry["price"]
        old_price = entry.get("old_price")
        if old_price:
            lines.append(f"🎁 {item['stars']}⭐ — <s>{old_price}💎</s> {price}💎")
        else:
            lines.append(f"🎁 {item['stars']}⭐ — {price}💎")

    await message.answer("\n".join(lines), reply_markup=shop_keyboard(prices))

@router.callback_query(F.data.startswith("buy:"))
async def handle_buy(callback: CallbackQuery, bot: Bot) -> None:
    _, stars_str, _old_price_str = callback.data.split(":")
    stars = int(stars_str)

    prices = await get_shop_prices()
    entry = prices.get(str(stars))
    if entry is None:
        await callback.answer("❌ Этот подарок больше недоступен.", show_alert=True)
        return
    price = entry["price"]

    user = callback.from_user
    user_data = await get_user(user.id, user.username, user.full_name)
    banned, _ = ban_status(user_data)
    if banned:
        await callback.answer("⛔ Вы забанены.", show_alert=True)
        return

    if user_data.get("balance", 0) < price:
        await callback.answer("❌ Недостаточно 💎 на балансе.", show_alert=True)
        return

    min_tasks = 5
    if user_data.get("completed", 0) < min_tasks:
        await callback.answer(
            f"Вы не выполнили минимум {min_tasks} заданий для покупки подарков.",
            show_alert=True,
        )
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
    StateFilter(None),
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
    await notify_user(bot, user_id, f"✅ Ваше задание принято!\nНачислено: {amount}💎")


@router.message(StateFilter(AdminStates.waiting_task_reason), F.from_user.id == ADMIN_ID)
async def process_task_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    user_id = data["target_user_id"]

    reason = message.text or "без указания причины"
    await state.clear()

    await message.answer(f"❌ Отказ отправлен пользователю {user_id}.")
    await notify_user(bot, user_id, f"❌ Ваше задание отклонено.\nПричина: {reason}")


# ==================== ПРЕДЛОЖИТЬ ЗАДАНИЕ (от пользователя) ====================

SUGGEST_TASK_RULES_TEXT = (
    "💡 Предложение задания\n\n"
    "1. Опишите задание, которое вы предлагаете.\n"
    "2. Затем выполните его сами и пришлите медиа-отчёт (фото/видео/кружок/гс) выполнения.\n"
    "3. Заявка уйдёт администратору на проверку.\n\n"
    "🎁 Если ваше задание примут и другие пользователи будут его выполнять, "
    "вы будете получать 10% роялти в 💎 с каждого начисления за выполнение вашего задания."
)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отменить предложение")]],
        resize_keyboard=True,
    )


@router.message(F.from_user.id != ADMIN_ID, F.text == "💡 Предложить задание")
async def suggest_task_start(message: Message, state: FSMContext) -> None:
    user_data = await get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    banned, status_text = ban_status(user_data)
    if banned:
        await message.answer(f"⛔ Вы забанены. Статус: {status_text}")
        return

    if user_data.get("completed", 0) < 1:
        await message.answer(
            "⚠️ Сначала нужно выполнить хотя бы одно задание самому, "
            "прежде чем предлагать своё."
        )
        return

    await state.set_state(SuggestTaskStates.waiting_description)
    await message.answer(
        SUGGEST_TASK_RULES_TEXT + "\n\n✏️ Напишите описание задания:",
        reply_markup=cancel_keyboard(),
    )


@router.message(StateFilter(SuggestTaskStates.waiting_description, SuggestTaskStates.waiting_media), F.text == "❌ Отменить предложение")
async def suggest_task_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🚫 Предложение задания отменено.", reply_markup=user_main_keyboard())


@router.message(StateFilter(SuggestTaskStates.waiting_description), F.from_user.id != ADMIN_ID)
async def suggest_task_description(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("⚠️ Пришлите текстовое описание задания.")
        return
    await state.update_data(suggested_description=message.text)
    await state.set_state(SuggestTaskStates.waiting_media)
    await message.answer(
        "✅ Описание сохранено.\n"
        "Теперь выполните это задание сами и пришлите медиа-отчёт (фото/видео/кружок/гс).",
        reply_markup=cancel_keyboard(),
    )


@router.message(
    StateFilter(SuggestTaskStates.waiting_media),
    F.from_user.id != ADMIN_ID,
    F.content_type.in_({"photo", "video", "video_note", "voice"}),
)
async def suggest_task_media(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    description = data.get("suggested_description", "")
    user = message.from_user

    header = (
        f"💡 Новое предложенное задание\n"
        f"От: {user.full_name} (@{user.username or 'без username'})\n"
        f"ID: {user.id}\n\n"
        f"Описание задания:\n{description}\n"
    )

    try:
        new_caption = header if message.content_type != "video_note" else None
        await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=new_caption,
        )
        if message.content_type == "video_note":
            await bot.send_message(ADMIN_ID, header)

        await bot.send_message(
            ADMIN_ID,
            "👆 Решение по предложенному заданию:",
            reply_markup=suggested_task_decision_keyboard(user.id),
        )
        await message.answer(
            "✅ Ваше предложение отправлено администратору на проверку. Ожидайте решения.",
            reply_markup=user_main_keyboard(),
        )
    except Exception as e:
        logger.error(f"Ошибка при пересылке предложенного задания от {user.id}: {e}")
        await message.answer("❌ Не удалось отправить предложение, попробуйте позже.", reply_markup=user_main_keyboard())
    finally:
        await state.clear()


@router.message(StateFilter(SuggestTaskStates.waiting_media), F.from_user.id != ADMIN_ID)
async def suggest_task_media_wrong_type(message: Message) -> None:
    await message.answer(
        "⚠️ Пришлите, пожалуйста, фото, видео, кружок или голосовое сообщение с выполнением задания.",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data.startswith("suggest_ok:"))
async def handle_suggest_approve(callback: CallbackQuery, bot: Bot) -> None:
    user_id = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await notify_user(bot, user_id, "✅ Ваше задание принято!")
    await callback.message.answer(f"✅ Задание пользователя {user_id} принято.")
    await callback.answer()


@router.callback_query(F.data.startswith("suggest_no:"))
async def handle_suggest_reject(callback: CallbackQuery, bot: Bot) -> None:
    user_id = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await notify_user(bot, user_id, "❌ Ваше задание отклонено.")
    await callback.message.answer(f"❌ Задание пользователя {user_id} отклонено.")
    await callback.answer()


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
        await notify_user(bot, target_id, "⛔ Вы забанены навсегда." + (f"\nПричина: {reason}" if reason else ""))
    elif duration_part.isdigit():
        minutes = int(duration_part)
        ban_until = time.time() + minutes * 60
        await update_user(target_id, ban_until=ban_until, ban_reason=reason)
        await message.answer(
            f"🚫 Пользователь {target_id} забанен на {minutes} мин." + (f" Причина: {reason}" if reason else "")
        )
        await notify_user(
            bot, target_id, f"⛔ Вы забанены на {minutes} мин." + (f"\nПричина: {reason}" if reason else "")
        )
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
    await notify_user(bot, target_id, "✅ Вы разбанены, можете продолжать пользоваться ботом.")


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
        if u.get("blocked"):
            continue
        uname = f"@{u.get('username')}" if u.get("username") else "без username"
        lines.append(
            f"ID {uid} ({uname}) — 💎{u.get('balance', 0)}, заданий: {u.get('completed', 0)}"
        )

    if not lines:
        await message.answer("Нет активных пользователей (не заблокировавших бота).")
        return

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
    if amount >= 0:
        await notify_user(bot, target_id, f"🎁 Вам начислено {amount}💎 администратором.\nВаш баланс: {new_balance}💎")
    else:
        await notify_user(bot, target_id, f"⚠️ С вашего баланса списано {-amount}💎.\nВаш баланс: {new_balance}💎")


# ==================== РУЧНОЕ ДОБАВЛЕНИЕ К СЧЁТЧИКУ ВЫПОЛНЕННЫХ ЗАДАНИЙ ====================

@router.message(F.from_user.id == ADMIN_ID, F.text == "➕ Добавить заданий")
async def admin_add_completed_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_add_completed_id)
    await message.answer("Введите ID пользователя, которому нужно добавить выполненные задания:")


@router.message(StateFilter(AdminStates.waiting_add_completed_id), F.from_user.id == ADMIN_ID)
async def admin_add_completed_id(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("⚠️ Введите числовой ID.")
        return
    await state.update_data(add_completed_target_id=int(message.text.strip()))
    await state.set_state(AdminStates.waiting_add_completed_amount)
    await message.answer("Введите количество заданий, которое нужно добавить к счётчику (можно отрицательное):")


@router.message(StateFilter(AdminStates.waiting_add_completed_amount), F.from_user.id == ADMIN_ID)
async def admin_add_completed_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    target_id = data["add_completed_target_id"]

    if not message.text or not message.text.strip().lstrip("-").isdigit():
        await message.answer("⚠️ Введите число.")
        return

    amount = int(message.text.strip())
    async with _data_lock:
        stored = _load_data()
        uid = str(target_id)
        if uid not in stored["users"]:
            stored["users"][uid] = {
                "username": None,
                "full_name": None,
                "balance": 0,
                "completed": 0,
                "ban_until": None,
                "ban_reason": None,
                "blocked": False,
            }
        stored["users"][uid]["completed"] = stored["users"][uid].get("completed", 0) + amount
        new_completed = stored["users"][uid]["completed"]
        _save_data(stored)
    await state.clear()

    await message.answer(
        f"✅ Счётчик заданий пользователя {target_id} изменён на {amount}. Новое значение: {new_completed}"
    )
    await notify_user(bot, target_id, f"ℹ️ Ваш счётчик выполненных заданий обновлён администратором. Текущее значение: {new_completed}")


# ==================== ИЗМЕНЕНИЕ ЦЕН МАГАЗИНА (временное, без правки кода) ====================

def price_pick_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{item['stars']}⭐", callback_data=f"pricepick:{item['stars']}")]
        for item in SHOP_ITEMS
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.from_user.id == ADMIN_ID, F.text == "🏷 Изменить цены")
async def admin_price_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_price_stars)
    await message.answer("Выберите позицию, у которой хотите изменить цену:", reply_markup=price_pick_keyboard())


@router.callback_query(F.data.startswith("pricepick:"), StateFilter(AdminStates.waiting_price_stars))
async def admin_price_pick(callback: CallbackQuery, state: FSMContext) -> None:
    stars = int(callback.data.split(":")[1])
    await state.update_data(price_target_stars=stars)
    await state.set_state(AdminStates.waiting_price_value)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"Введите новую цену в 💎 для подарка {stars}⭐:")
    await callback.answer()


@router.message(StateFilter(AdminStates.waiting_price_value), F.from_user.id == ADMIN_ID)
async def admin_price_value(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip().isdigit():
        await message.answer("⚠️ Введите целое число.")
        return
    await state.update_data(price_new_value=int(message.text.strip()))
    await state.set_state(AdminStates.waiting_price_discount)
    await message.answer(
        "Это скидка? Если да — старая цена будет показана зачёркнутой.\n"
        "Ответьте: да / нет"
    )


@router.message(StateFilter(AdminStates.waiting_price_discount), F.from_user.id == ADMIN_ID)
async def admin_price_discount(message: Message, state: FSMContext) -> None:
    answer = (message.text or "").strip().lower()
    if answer not in ("да", "нет"):
        await message.answer("⚠️ Ответьте 'да' или 'нет'.")
        return

    data = await state.get_data()
    stars = data["price_target_stars"]
    new_price = data["price_new_value"]
    discount = answer == "да"

    await set_shop_price(stars, new_price, discount=discount)
    await state.clear()
    await message.answer(f"✅ Цена для {stars}⭐ обновлена: {new_price}💎" + (" (со скидкой, старая цена зачёркнута)" if discount else ""))


# ==================== ГЛОБАЛЬНАЯ РАССЫЛКА ====================

@router.message(F.from_user.id == ADMIN_ID, F.text == "📢 Рассылка")
async def admin_broadcast_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_broadcast)
    await message.answer(
        "Отправьте сообщение (текст, фото, видео и т.п.), которое нужно разослать всем пользователям."
    )


@router.message(StateFilter(AdminStates.waiting_broadcast), F.from_user.id == ADMIN_ID)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    users = await get_all_users()

    sent, failed = 0, 0
    for uid_str, u in users.items():
        uid = int(uid_str)
        if uid == ADMIN_ID:
            continue
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            sent += 1
        except TelegramForbiddenError:
            await update_user(uid, blocked=True)
            failed += 1
        except Exception as e:
            logger.error(f"Не удалось отправить рассылку пользователю {uid}: {e}")
            failed += 1

    await message.answer(f"📢 Рассылка завершена.\n✅ Доставлено: {sent}\n❌ Не доставлено: {failed}")


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
    except TelegramForbiddenError:
        await update_user(user_id, blocked=True)
        await message.reply("❌ Пользователь заблокировал бота, ответ не доставлен.")
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
