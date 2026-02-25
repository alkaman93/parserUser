import asyncio
import logging
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ========================
# НАСТРОЙКИ
# ========================
API_ID = 28687552
API_HASH = "1abf9a58d0c22f62437bec89bd6b27a3"
BOT_TOKEN = "8559985318:AAHJdshGOYv1hQMEM6kpOFFJzL1lX9OnCGw"
ADMIN_ID = 174415647
# ========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_clients = {}


async def get_group_members(client, group_link):
    """Получить всех участников группы"""
    try:
        if "t.me/" in group_link:
            group_name = group_link.split("t.me/")[-1].rstrip("/")
        else:
            group_name = group_link
        
        entity = await client.get_entity(group_name)
        members = []
        offset = 0
        limit = 200

        print(f"Парсим группу: {group_name}")

        while True:
            participants = await client(GetParticipantsRequest(
                channel=entity,
                filter=ChannelParticipantsSearch(""),
                offset=offset,
                limit=limit,
                hash=0
            ))

            if not participants.users:
                break

            for user in participants.users:
                if not user.bot:
                    username = f"@{user.username}" if user.username else "нет username"
                    members.append({
                        "id": user.id,
                        "username": username,
                    })

            offset += len(participants.users)

            if offset >= participants.count:
                break

            await asyncio.sleep(0.5)

        return members, entity.title

    except Exception as e:
        return None, str(e)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Команда /start"""
    logger.info(f"Получена команда /start от {message.from_user.id}")
    
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У тебя нет доступа к этому боту")
        return
    
    await message.answer(
        "👋 Привет! Я бот для парсинга участников групп.\n\n"
        "Просто отправь мне ссылку на группу (например t.me/groupname или название группы)\n"
        "И я отправлю всех участников по одному!"
    )


@dp.message()
async def handle_message(message: Message):
    """Обработка всех остальных сообщений"""
    logger.info(f"Получено сообщение: {message.text} от {message.from_user.id}")
    
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У тебя нет доступа")
        return
    
    group_link = message.text.strip()
    
    if not group_link:
        await message.answer("❌ Отправь ссылку на группу")
        return
    
    # Игнорируем команды (обработает Command фильтр)
    if group_link.startswith("/"):
        return
    
    await message.answer(f"⏳ Подключаюсь к группе: {group_link}")
    
    try:
        if message.from_user.id not in user_clients:
            client = TelegramClient(f"session_{message.from_user.id}", API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await message.answer("❌ Ошибка: Требуется авторизация. Запусти скрипт на компьютере сначала.")
                return
            user_clients[message.from_user.id] = client
        else:
            client = user_clients[message.from_user.id]
        
        members, group_title = await get_group_members(client, group_link)
        
        if members is None:
            await message.answer(f"❌ Ошибка: {group_title}")
            return
        
        await message.answer(f"✅ Найдено {len(members)} участников в группе '{group_title}'\n\n"
                           f"Начинаю отправлять...")
        
        for i, user in enumerate(members, 1):
            text = f"#{i}\n🆔 ID: {user['id']}\n👤 {user['username']}"
            await message.answer(text)
            await asyncio.sleep(0.1)
        
        await message.answer(f"✅ Готово! Отправлено {len(members)} участников")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
        logger.error(f"Ошибка: {e}")


async def main():
    logger.info("🤖 Бот запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
