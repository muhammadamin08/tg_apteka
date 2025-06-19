import asyncio
import json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

API_TOKEN = "8048459930:AAEj98MtJhn7-lOj35NQmbtZUxupQB8td-0"

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Загрузка базы
def load_medicines():
    try:
        with open("mediciness.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Ошибка загрузки базы: {e}")
        return {}

medicines = load_medicines()

# Состояния
class Form(StatesGroup):
    waiting_for_medicine = State()
    waiting_for_dosage = State()
    waiting_for_count = State()
    waiting_for_confirmation = State()

user_data = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_data[message.from_user.id] = {"medicines": []}
    await state.set_state(Form.waiting_for_medicine)
    await message.answer("👋 Assalomu alaykum! Davolanishni boshlaymiz. Iltimos, dori nomidan kamida 2 harf kiriting:")

@dp.message(Command("restart"))
async def cmd_restart(message: types.Message, state: FSMContext):
    user_data[message.from_user.id] = {"medicines": []}
    await state.clear()
    await message.answer("🔄 Ma'lumotlar o'chirildi. Yangi dori kiriting:")
    await state.set_state(Form.waiting_for_medicine)

@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_medicine)
    await message.answer("➕ Yangi dori qo'shish uchun kamida 2 ta harf kiriting:")

@dp.message(Command("mening_dorilarim"))
async def my_medicines(message: types.Message):
    user_id = message.from_user.id
    meds = user_data.get(user_id, {}).get("medicines", [])

    if not meds:
        await message.answer("❗ Sizda hozircha dori yo'q.")
        return

    text = "💊 Sizdagi dorilar:\n"
    for m in meds:
        text += f"\n🔹 {m['name'].title()} — {m['dosage']}, {m['count']} marta (vaqt: {', '.join(m['times'])})"

    await message.answer(text)

@dp.message(StateFilter(Form.waiting_for_medicine))
async def handle_medicine(message: types.Message, state: FSMContext):
    query = message.text.lower()
    if len(query) < 2:
        await message.answer("⚠️ Iltimos, kamida 2 ta harf kiriting.")
        return

    matches = [name for name in medicines if name.startswith(query)]
    if not matches:
        await message.answer("🚫 Dori topilmadi. Qayta urinib ko'ring.")
        return

    buttons = [[InlineKeyboardButton(text=name, callback_data=f"med_{name}")] for name in matches[:5]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("👇 Dorini tanlang:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("med_"))
async def handle_dosage(callback: types.CallbackQuery, state: FSMContext):
    med_name = callback.data[4:]
    await state.update_data(medicine_choice=med_name)

    med = medicines[med_name]
    buttons = [[InlineKeyboardButton(text=dose, callback_data=f"dose_{dose}")] for dose in med["dosages"]]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text(f"📄 {med['description']}\n👇 Dori dozasini tanlang:", reply_markup=keyboard)
    await state.set_state(Form.waiting_for_count)

@dp.callback_query(F.data.startswith("dose_"))
async def handle_count(callback: types.CallbackQuery, state: FSMContext):
    dosage = callback.data[5:]
    data = await state.get_data()
    med_name = data.get("medicine_choice")

    if not med_name or dosage not in medicines[med_name]["dosages"]:
        await callback.answer("⚠️ Dozani tanlang.", show_alert=True)
        return

    await state.update_data(dosage=dosage)

    buttons = [[InlineKeyboardButton(text=str(i), callback_data=f"count_{i}")] for i in range(1, 5)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text("🕒 Kuniga nechta marta qabul qilish kerak?", reply_markup=keyboard)
    await state.set_state(Form.waiting_for_confirmation)

@dp.callback_query(F.data.startswith("count_"))
async def handle_confirm(callback: types.CallbackQuery, state: FSMContext):
    count = int(callback.data[6:])
    data = await state.get_data()
    med_name = data["medicine_choice"]
    dosage = data["dosage"]
    med = medicines[med_name]
    times = med["times"][:count]

    user_id = callback.from_user.id
    user_data.setdefault(user_id, {"medicines": []})

    if any(m["name"] == med_name for m in user_data[user_id]["medicines"]):
        await callback.message.answer("❗ Bu dori allaqachon qo'shilgan.")
        await state.set_state(Form.waiting_for_medicine)
        return

    user_data[user_id]["medicines"].append({
        "name": med_name,
        "dosage": dosage,
        "count": count,
        "times": times,
    })

    text = (
        f"✅ Qo'shildi:\n"
        f"💊 Dori: {med_name.title()}\n"
        f"💉 Doza: {dosage}\n"
        f"📆 Qabul: {count} marta\n"
        f"🕒 Vaqtlar: {', '.join(times)}"
    )
    await callback.message.edit_text(text)
    await state.set_state(Form.waiting_for_medicine)
    await schedule_jobs_for_user(user_id)

async def schedule_jobs_for_user(user_id: int):
    prefix = f"{user_id}_"
    for job in scheduler.get_jobs():
        if job.id.startswith(prefix):
            scheduler.remove_job(job.id)

    meds = user_data[user_id]["medicines"]
    for midx, med in enumerate(meds):
        for tidx, t in enumerate(med["times"]):
            hour, minute = map(int, t.split(":"))
            scheduler.add_job(
                send_reminder,
                CronTrigger(hour=hour, minute=minute),
                args=[user_id, med["name"], med["dosage"]],
                id=f"{user_id}_{midx}_{tidx}",
                replace_existing=True,
            )

async def send_reminder(user_id, med_name, dosage):
    try:
        await bot.send_message(user_id, f"🔔 Eslatma: {med_name.title()} — {dosage}")
    except Exception as e:
        print(f"Xatolik eslatma yuborishda: {e}")

async def on_startup():
    scheduler.start()

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

