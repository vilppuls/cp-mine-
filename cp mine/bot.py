import asyncio
import logging
import os
import re
import json
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
REVIEWS_CHAT_ID = -1003244079264

# Админ получает уведомления о выигрышах
ADMINS_LIST = ADMIN_IDS  # можно заменить на отдельный чат, если нужно

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
processed_message_ids = set()
current_prize = "NFT подарок"  # по умолчанию


# ─── FSM ──────────────────────────────────────────────────────────
class ReviewState(StatesGroup):
    waiting_for_text = State()

class PrizeState(StatesGroup):
    waiting_for_prize = State()


# ─── ХРАНЕНИЕ ТЕКУЩЕГО ПРИЗА ──────────────────────────────────────
PRIZE_FILE = "current_prize.txt"

def get_current_prize():
    global current_prize
    try:
        with open(PRIZE_FILE, "r", encoding="utf-8") as f:
            current_prize = f.read().strip()
    except FileNotFoundError:
        pass
    return current_prize

def set_current_prize(prize: str):
    global current_prize
    current_prize = prize
    with open(PRIZE_FILE, "w", encoding="utf-8") as f:
        f.write(prize)


# ─── /start ───────────────────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "🎰 <b>Добро пожаловать в Lucky SPIN!</b>\n\n"
        "🔥 Играйте и выигрывайте крутые призы!\n"
        "💬 Нажмите «Написать отзыв», чтобы поделиться мнением.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Написать отзыв", callback_data="write_review")]
        ]),
        parse_mode="HTML"
    )


# ─── ОТЗЫВ ────────────────────────────────────────────────────────
@dp.callback_query(lambda c: c.data == "write_review")
async def write_review_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ <b>Напишите, что думаете о Lucky SPIN:</b>", parse_mode="HTML")
    await state.set_state(ReviewState.waiting_for_text)
    await callback.answer()

@dp.message(ReviewState.waiting_for_text)
async def process_review(message: types.Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 3:
        await message.answer("❌ Минимум 3 символа.")
        return

    user = message.from_user
    username = f"@{user.username}" if user.username else f"ID{user.id}"

    try:
        await bot.send_message(
            REVIEWS_CHAT_ID,
            f"<b>Пользователь:</b> <b><i>{username}</i></b>\n"
            f"<b><i>Отзыв: </i></b> <code><i>{message.text.strip()}</i></code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Отзыв не отправлен: {e}")

    await message.answer("✅ Спасибо за отзыв!", parse_mode="HTML")
    await state.clear()


# ─── /panel ───────────────────────────────────────────────────────
@dp.message(Command("panel"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "🛠️ <b>Админ-панель</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Приз", callback_data="set_prize")]
        ]),
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "set_prize")
async def set_prize_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("🎁 Укажите приз для розыгрыша:", parse_mode="HTML")
    await state.set_state(PrizeState.waiting_for_prize)
    await callback.answer()

@dp.message(PrizeState.waiting_for_prize)
async def process_prize(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    prize = message.text.strip()
    if not prize:
        await message.answer("❌ Приз не может быть пустым.")
        return

    set_current_prize(prize)
    announcement = (
        f"✨ <b>ОГРОМНЫЙ РОЗЫГРЫШ!</b> ✨\n\n"
        f"🏆 <b>Разыгрывается:</b> <code>{prize}</code>\n\n"
        f"🎯 <b>Как участвовать?</b>\n"
        f"Пополните счёт → Сыграйте в слот → Выиграйте приз мгновенно!\n\n"
        f"💫 <i>Ваш шанс — прямо сейчас. Удача на вашей стороне!</i>"
    )

    try:
        sent = await bot.send_message(CHANNEL_ID, announcement, parse_mode="HTML")
        await bot.pin_chat_message(CHANNEL_ID, sent.message_id, disable_notification=True)
        await message.answer("✅ Розыгрыш объявлен и закреплён!", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Закрепление не удалось: {e}")
        await message.answer("❌ Ошибка. Проверьте права бота в канале.")

    await state.clear()


# ─── КНОПКА "ПОЛУЧИТЬ ВЫИГРЫШ" ────────────────────────────────────
@dp.callback_query(lambda c: c.data.startswith("claim_prize_"))
async def claim_prize(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.username or f"ID{user_id}"
    prize = get_current_prize()

    # Отправляем уведомление админам
    for admin_id in ADMINS_LIST:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 <b>Новый запрос на выдачу приза!</b>\n\n"
                f"👤 <b>Пользователь:</b> @{user_name}\n"
                f"🎁 <b>Приз:</b> {prize}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить админу {admin_id}: {e}")

    bot_username = (await bot.me()).username
    await callback.answer(
        show_alert=False,
        url=f"https://t.me/{bot_username}"
    )

@dp.channel_post()
async def handle_channel_post(message: types.message):
    if message.chat.id != CHANNEL_ID:
        return
    text = message.text or ""
    if "ustd" not in text in processed_message_ids:
        return
    if processed_message_ids in processed_message_ids:
        return
    processed_message_ids.add(processed_message_ids)
    if text.startswith("trustget -"):
        match = re.search(r'TrustGet - ([От])+?\s+отправил',text)
    else:
        match = re.search(r'TrustGet - ([От])+?\s+отправил',text)
        amount_match = re.search(r'TrustGet - ([От])+?\s+отправил',text)

raw_name = match.group(1).strip()



async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())