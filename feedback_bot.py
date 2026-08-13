"""
Telegram-бот обратной связи и приёма заявок.
Библиотека: aiogram 3.x

Логика:
1. /start — приветствие + правила + кнопка со ссылкой на вступление в сообщество.
2. Любое сообщение от пользователя (текст, фото, видео, документ и т.д.)
   пересылается администратору, а пользователю приходит подтверждение.
3. Администратор может ответить пользователю через reply на пересланное
   сообщение — бот доставит ответ пользователю (опционально, включено ниже).

Установка зависимостей:
    pip install aiogram==3.*

Запуск:
    python feedback_bot.py
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ==================== НАСТРОЙКИ (ВСТАВЬТЕ СВОИ ЗНАЧЕНИЯ) ====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
# =============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()

# Словарь для сопоставления пересланного админу сообщения с ID пользователя,
# чтобы администратор мог ответить пользователю через "Ответить" (reply).
# Формат: {message_id_у_админа: user_id}
forwarded_map: dict[int, int] = {}

WELCOME_TEXT = (
    "Добро пожаловать! 👋\n"
    "Это прямой чат с Администратором нашего сообщества.\n\n"
    "Здесь вы можете:\n"
    "• Отправить вопрос, отчёт или заявку — она будет передана администратору.\n"
    "• Получить ссылку на вступление в сообщество (кнопка ниже).\n\n"
    "Просто отправьте текстовое сообщение, фото или видео — оно автоматически "
    "будет переслано администратору на проверку."
)

CONFIRMATION_TEXT = "Ваш отчёт получен и передан на проверку администратору ⏳"


def get_start_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой вступления в сообщество."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Вступить в сообщество", url=COMMUNITY_LINK)]
        ]
    )


# ==================== ОБРАБОТЧИК /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        WELCOME_TEXT,
        reply_markup=get_start_keyboard(),
    )


# ==================== ОТВЕТ АДМИНА ПОЛЬЗОВАТЕЛЮ ====================
# Если админ отвечает (reply) на пересланное ботом сообщение — бот
# доставляет этот ответ исходному пользователю.

@router.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def admin_reply_handler(message: Message, bot: Bot) -> None:
    replied_id = message.reply_to_message.message_id
    user_id = forwarded_map.get(replied_id)

    if user_id is None:
        # Это не ответ на пересланное сообщение — игнорируем /
        # либо это обычное сообщение админа, не связанное с пересылкой.
        return

    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await message.reply("✅ Ответ отправлен пользователю.")
    except Exception as e:
        logger.error(f"Не удалось отправить ответ пользователю {user_id}: {e}")
        await message.reply(f"❌ Не удалось отправить ответ: {e}")


# ==================== ПЕРЕСЫЛКА СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЯ АДМИНУ ====================

@router.message(F.from_user.id != ADMIN_ID)
async def forward_to_admin(message: Message, bot: Bot) -> None:
    """
    Пересылает любое сообщение (текст, фото, видео, документ, голосовое и т.д.)
    от пользователя администратору и подтверждает получение.
    """
    user = message.from_user
    caption_info = (
        f"📩 Новое сообщение\n"
        f"От: {user.full_name} (@{user.username or 'без username'})\n"
        f"ID: {user.id}"
    )

    try:
        # Сначала отправляем админу служебную информацию о пользователе
        await bot.send_message(chat_id=ADMIN_ID, text=caption_info)

        # Затем копируем (пересылаем) само сообщение пользователя
        sent = await bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )

        # Запоминаем связь message_id (у админа) -> user_id,
        # чтобы можно было ответить пользователю через reply
        forwarded_map[sent.message_id] = user.id

        # Подтверждение пользователю
        await message.answer(CONFIRMATION_TEXT)

    except Exception as e:
        logger.error(f"Ошибка при пересылке сообщения от {user.id}: {e}")
        await message.answer(
            "⚠️ Произошла ошибка при отправке. Попробуйте ещё раз позже."
        )


# ==================== ТОЧКА ВХОДА ====================

async def main() -> None:
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    logger.info("Бот запущен.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
