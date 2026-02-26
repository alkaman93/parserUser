import asyncio
import logging
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from telethon.errors import SessionPasswordNeededError
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

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
dp = Dispatcher(storage=MemoryStorage())

user_clients: dict[int, TelegramClient] = {}


# ===================== STATES =====================
class Auth(StatesGroup):
    phone = State()
    code = State()
    password = State()


# ===================== HELPERS =====================
async def get_group_members(client: TelegramClient, group_link: str, status_msg=None):
    """Получить участников группы — перебор по символам и комбинациям"""
    try:
        if "t.me/" in group_link:
            group_name = group_link.split("t.me/")[-1].rstrip("/").lstrip("+")
        else:
            group_name = group_link

        entity = await client.get_entity(group_name)
        members_dict = {}  # id -> user (дедупликация)

        # Все символы для перебора
        chars = list("abcdefghijklmnopqrstuvwxyz0123456789_.")
        # Двойные комбинации для глубокого поиска (aa, ab, ... zz + цифры)
        double_chars = [a + b for a in "abcdefghijklmnopqrstuvwxyz" for b in "abcdefghijklmnopqrstuvwxyz0123456789_"]

        all_queries = [""] + chars + double_chars  # сначала пустой, потом одиночные, потом двойные
        total = len(all_queries)

        for i, query in enumerate(all_queries):
            try:
                offset = 0
                while True:
                    result = await client(GetParticipantsRequest(
                        channel=entity,
                        filter=ChannelParticipantsSearch(query),
                        offset=offset,
                        limit=200,
                        hash=0
                    ))
                    if not result.users:
                        break
                    new_found = 0
                    for user in result.users:
                        if not user.bot and user.username and user.id not in members_dict:
                            members_dict[user.id] = user
                            new_found += 1
                    offset += len(result.users)
                    if offset >= result.count or new_found == 0:
                        break
                    await asyncio.sleep(0.3)

                # Обновляем статус каждые 50 запросов
                if status_msg and i % 50 == 0 and i > 0:
                    percent = int(i / total * 100)
                    try:
                        await status_msg.edit_text(
                            f"⏳ Парсинг... {percent}%\n"
                            f"🔍 Запросов: {i}/{total}\n"
                            f"👥 Найдено пока: {len(members_dict)}"
                        )
                    except Exception:
                        pass

                await asyncio.sleep(0.35)

            except Exception:
                await asyncio.sleep(1)
                continue

        # Формируем итоговый список
        members = []
        for user in members_dict.values():
            members.append({
                "id": user.id,
                "username": f"@{user.username}",
                "name": f"{user.first_name or ''} {user.last_name or ''}".strip()
            })

        return members, entity.title

    except Exception as e:
        return None, str(e)


async def get_or_create_client(uid: int) -> TelegramClient:
    if uid not in user_clients:
        client = TelegramClient(f"session_{uid}", API_ID, API_HASH)
        await client.connect()
        user_clients[uid] = client
    return user_clients[uid]


# ===================== HANDLERS =====================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У тебя нет доступа к этому боту")
        return

    await state.clear()

    client = await get_or_create_client(message.from_user.id)
    if await client.is_user_authorized():
        me = await client.get_me()
        await message.answer(
            f"👋 Привет! Я бот для парсинга участников групп.\n\n"
            f"✅ Авторизован как: {me.first_name} (@{me.username})\n\n"
            f"Отправь ссылку на группу (например <code>t.me/groupname</code>) "
            f"и я спаршу всех участников!",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "👋 Привет! Для начала нужно авторизоваться.\n\n"
            "📱 Введи свой номер телефона в формате: <code>+79001234567</code>",
            parse_mode="HTML"
        )
        await state.set_state(Auth.phone)


@dp.message(Command("auth"))
async def cmd_auth(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "📱 Введи номер телефона в формате: <code>+79001234567</code>",
        parse_mode="HTML"
    )
    await state.set_state(Auth.phone)


@dp.message(Command("logout"))
async def cmd_logout(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    uid = message.from_user.id
    if uid in user_clients:
        await user_clients[uid].log_out()
        del user_clients[uid]
    await state.clear()
    await message.answer("✅ Сессия завершена. Используй /auth для повторной авторизации.")


# --- AUTH FLOW ---
@dp.message(Auth.phone)
async def auth_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not phone.startswith("+"):
        await message.answer("❌ Номер должен начинаться с +\nПример: <code>+79001234567</code>", parse_mode="HTML")
        return

    client = await get_or_create_client(message.from_user.id)
    try:
        result = await client.send_code_request(phone)
        await state.update_data(phone=phone, phone_code_hash=result.phone_code_hash)
        await state.set_state(Auth.code)
        await message.answer(
            "📨 Код отправлен в Telegram!\n\n"
            "Введи код который пришёл в приложение Telegram.\n"
            "Пиши код слитно: <code>12345</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке кода: {str(e)}")
        logger.error(f"Ошибка send_code: {e}")


@dp.message(Auth.code)
async def auth_code(message: Message, state: FSMContext):
    code = message.text.strip().replace(" ", "")
    data = await state.get_data()
    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")

    client = user_clients.get(message.from_user.id)
    if not client:
        await message.answer("❌ Сессия потеряна. Начни заново: /auth")
        await state.clear()
        return

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        await state.clear()
        await message.answer(
            f"✅ Авторизация успешна!\n\n"
            f"Вошёл как: <b>{me.first_name}</b> (@{me.username})\n\n"
            f"Теперь отправь ссылку на группу для парсинга.",
            parse_mode="HTML"
        )
    except SessionPasswordNeededError:
        await state.set_state(Auth.password)
        await message.answer("🔐 Включена двухфакторная аутентификация.\nВведи пароль:")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}\n\nПопробуй снова: /auth")
        await state.clear()
        logger.error(f"Ошибка sign_in: {e}")


@dp.message(Auth.password)
async def auth_password(message: Message, state: FSMContext):
    password = message.text.strip()
    client = user_clients.get(message.from_user.id)
    if not client:
        await message.answer("❌ Сессия потеряна. Начни заново: /auth")
        await state.clear()
        return

    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        await state.clear()
        await message.answer(
            f"✅ Авторизация успешна!\n\n"
            f"Вошёл как: <b>{me.first_name}</b> (@{me.username})\n\n"
            f"Теперь отправь ссылку на группу для парсинга.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {str(e)}")
        logger.error(f"Ошибка 2FA: {e}")


# --- PARSING ---
@dp.message(F.text)
async def handle_group_link(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ У тебя нет доступа")
        return

    # Если в режиме авторизации — игнорируем
    current_state = await state.get_state()
    if current_state is not None:
        return

    group_link = message.text.strip()
    if not group_link or group_link.startswith("/"):
        return

    client = user_clients.get(message.from_user.id)
    if not client or not await client.is_user_authorized():
        await message.answer(
            "❌ Сначала авторизуйся!\n\nИспользуй /auth для входа в аккаунт."
        )
        return

    await message.answer(
        f"⏳ Парсю группу: <code>{group_link}</code>\n\n"
        f"🔍 Перебираю все комбинации символов для поиска скрытых участников...\n"
        f"⏱ Это может занять 2-5 минут, подожди.",
        parse_mode="HTML"
    )
    status_msg = await message.answer("⏳ Парсинг... 0%\n🔍 Запросов: 0/0\n👥 Найдено: 0")

    members, group_title = await get_group_members(client, group_link, status_msg)

    if members is None:
        await message.answer(f"❌ Ошибка: {group_title}")
        return

    await message.answer(
        f"✅ Найдено <b>{len(members)}</b> участников в группе <b>'{group_title}'</b>\n\n"
        f"Начинаю отправлять...",
        parse_mode="HTML"
    )

    # Отправляем порциями по 50 в одном сообщении чтобы не спамить
    chunk_size = 50
    for i in range(0, len(members), chunk_size):
        chunk = members[i:i + chunk_size]
        lines = []
        for j, user in enumerate(chunk, i + 1):
            name = f" | {user['name']}" if user['name'] else ""
            lines.append(f"#{j} {user['username']}{name} | ID: {user['id']}")
        await message.answer("\n".join(lines))
        await asyncio.sleep(0.3)

    await message.answer(f"✅ Готово! Спаршено <b>{len(members)}</b> участников", parse_mode="HTML")


# ===================== MAIN =====================
async def main():
    logger.info("🤖 Парсер запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        # Закрываем все клиентские сессии
        for client in user_clients.values():
            await client.disconnect()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
