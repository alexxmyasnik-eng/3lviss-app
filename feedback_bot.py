"""
Telegram-бот обратной связи и приёма заявок.
Библиотека: aiogram 3.x

Логика:
1. /start — приветствие + правила (ссылку на вступление впишите прямо в текст ниже).
2. Любое сообщение от пользователя (текст, фото, видео, документ и т.д.)
   пересылается администратору ОДНИМ сообщением (инфо + контент вместе)
   с кнопкой "✍️ Ответить".
3. Админ жмёт кнопку "✍️ Ответить" -> бот просит ввести текст ответа ->
   следующее сообщение админа автоматически уходит пользователю.
   (Также работает classic reply: можно ответить на пересланное сообщение
   через "Ответить" в Telegram — сработает тот же механизм.)
4. Пользователю НЕ отправляется никаких служебных подтверждений.

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
На cron-job.org настрой пинг GET-запросом на твой URL (например,
https://anonpeak-9eje.onrender.com/) каждые 5 минут.
"""

import asyncio
import logging
import os

from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

# ==================== НАСТРОЙКИ (ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ) ====================

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
PORT = int(os.environ.get("PORT", 10000))

# =============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = Router()

# message_id (пересланного сообщения у админа) -> user_id
forwarded_map: dict[int, int] = {}
# message_id (сообщения-запроса "введите ответ") -> user_id

# Впишите ссылку на вступление прямо в текст ниже (вручную).
WELCOME_TEXT = (
    "Привет! Добро пожаловать 👋\n"
    "Это не просто бот, а твой личный анонимный чат с Администратором.\n"
    "📌 Что делать дальше:\n"
    "Подай заявку на вступление в закрытый канал по ссылке ниже.\n"
    "Дальше бот - ваша личная переписка с Администратором\n"
    "В закрытом канале будут выходить задания, а все выполненные фото/видео отчеты ты будешь отправлять прямо в этот чат. Всё полностью анонимно.\n"
    "🔗 Ссылка на приватный канал: https://t.me/+3RnGI1K53psxNmI1"
)



# ==================== /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT)


# ==================== КНОПКА "ОТВЕТИТЬ" ====================



# ==================== ОТВЕТ АДМИНА ПОЛЬЗОВАТЕЛЮ ====================
# Срабатывает как на reply к сообщению-запросу (после кнопки "Ответить"),
# так и на обычный reply к пересланному сообщению пользователя.

@router.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
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


# ==================== ПЕРЕСЫЛКА СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЯ АДМИНУ ====================

@router.message(F.from_user.id != ADMIN_ID)
async def forward_to_admin(message: Message, bot: Bot) -> None:
    """
    Пересылает сообщение пользователя администратору ОДНИМ сообщением
    (шапка с данными пользователя + сам контент) и добавляет кнопку "Ответить".
    Пользователю никакого подтверждения не отправляется.
    """
    user = message.from_user
    header = (
        f"📩 Новое сообщение\n"
        f"От: {user.full_name} (@{user.username or 'без username'})\n"
        f"ID: {user.id}\n"
    )

    try:
        if message.text:
            # Текстовое сообщение — объединяем шапку и текст в одно сообщение
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=f"{header}\n{message.text}",
            )
        else:
            # Медиа (фото/видео/документ/голос и т.д.) — шапка становится подписью
            existing_caption = message.caption or ""
            new_caption = f"{header}\n{existing_caption}".strip()
            await bot.copy_message(
                chat_id=ADMIN_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                caption=new_caption,
            )

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
    dp = Dispatcher()
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
