"""
Бот для быстрого формирования текста подтверждения перед продажей Telegram Stars.

Логика:
1. Вы отправляете боту юзернейм покупателя (с @ или без).
2. Бот НЕ обращается к API Telegram за поиском юзера (это невозможно без
   предварительного контакта пользователя с ботом — ограничение платформы).
   Вместо этого он просто красиво форматирует текст на основе введённого
   вами юзернейма, который вы сразу пересылаете покупателю для проверки.

Требования: Python 3.10+, aiogram 3.x
"""

import asyncio
import logging
import re

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ==== НАСТРОЙКИ ====
BOT_TOKEN = "8612824930:AAHvqxF3fp5Up2EJm7SQZO1GjTJzTTGuX9I"  # получить у @BotFather

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()


def normalize_username(raw: str) -> str | None:
    """
    Приводит введённый текст к чистому виду username (без @, без пробелов).
    Возвращает None, если строка не похожа на юзернейм.
    """
    raw = raw.strip()
    # убираем @ в начале, если есть
    if raw.startswith("@"):
        raw = raw[1:]

    # username в Telegram: латиница, цифры, подчёркивания, 5-32 символа
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", raw):
        return raw
    return None


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Отправь мне юзернейм покупателя (например, *durov* или *@durov*), "
        "и я сразу подготовлю текст для проверки, который можно переслать ему."
    )


@dp.message()
async def handle_username(message: Message):
    text = message.text or ""
    username = normalize_username(text)

    if not username:
        await message.answer(
            "❌ Не похоже на юзернейм.\n"
            "Отправь username в формате `@username` или `username` "
            "(только латинские буквы, цифры и `_`, от 5 символов)."
        )
        return

    # Формируем готовый текст для пересылки покупателю
    reply_text = (
        "⭐️ *Проверь данные для получения Stars:*\n\n"
        f"🔗 *Юзернейм:* @{username}\n\n"
        "❓ Это твой аккаунт?\n"
        "Если всё верно, отправь *+*\n"
        "Если данные неверны, отправь *-* и напиши точный @username."
    )

    # Отправляем одним сообщением — Markdown позволяет копировать
    # @username и остальной текст одним тапом на моноширинных/жирных частях.
    await message.answer(reply_text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
