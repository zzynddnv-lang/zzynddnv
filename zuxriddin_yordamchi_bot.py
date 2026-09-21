"""
ZUXRIDDIN YORDAMCHISI - Telegram Business bot (Groq / Llama asosida)

O'rnatish (VS Code terminalida):
    pip install -r requirements.txt

Ishga tushirish:
    python zuxriddin_yordamchi_bot.py
    yoki run.bat faylini ikki marta bosing.
"""

import asyncio
import csv
import json
import logging
import os
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.filters import CommandStart
    from groq import AsyncGroq
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Kerakli paketlar topilmadi. Quyidagi buyruqni ishga tushiring:\n"
        "pip install -r requirements.txt"
    ) from exc


# =====================================================================
#  SOZLAMALAR (.env faylidan o'qiydi, bo'lmasa quyidagi qiymatlarni oladi)
# =====================================================================

# 1) BotFather bergan bot tokeni (.env faylida saqlanadi)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 2) Groq API kaliti (.env faylida saqlanadi)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# 3) Ismingiz (bot shu ism bilan tanishtiradi)
EGA_ISMI = os.getenv("EGA_ISMI", "Zuxriddin")

# 4) AI modeli (Groq uchun)
MODEL = os.getenv("MODEL", "llama-3.1-8b-instant")

# Fayllar saqlanadigan asosiy papka
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADLAR_FAYLI = os.path.join(BASE_DIR, "leadlar.csv")

# =====================================================================
#  SO'ZLAR VA TIZIM KO'RSATMALARI
# =====================================================================

SALOM_MATNI = (
    f"Salom, men {EGA_ISMI}ning yordamchisiman. "
    f"Siz bilan men suhbat quraman va siz haqingizda {EGA_ISMI}ga javob beraman.\n\n"
    "Qanday masalada murojaat qilyapsiz?"
)

TIZIM_KORSATMASI = f"""Sen {EGA_ISMI}ning shaxsiy yordamchisisan. Telegram'da unga yozgan odamlar bilan gaplashasan.

Vazifang: suhbat orqali quyidagilarni aniqlab, {EGA_ISMI}ga yetkazish:
1. Odamning ismi
2. Qanday masalada murojaat qilyapti
3. Maqsadi: aniq nima kerak (masalan: mahsulot, narx, hamkorlik, maslahat)
4. Bog'lanish uchun telefon raqami (agar odam xohlasa)

Qoidalar:
- O'zbek tilida, iliq va qisqa gapir (1-3 gap). Odam boshqa tilda yozsa, o'sha tilda javob ber.
- Bir vaqtda faqat bitta savol ber.
- Narx, chegirma, muddat va boshqa narsalarni o'ylab topma va va'da qilma. Bilmasang: "Buni {EGA_ISMI} o'zi aniq aytadi" de.
- O'zingni {EGA_ISMI}ning yordamchisi deb tanishtir. Odam so'rasa, sen sun'iy intellekt ekaningni yashirma.
- Yetarli ma'lumot yig'ilgach (kamida masala va maqsad ma'lum bo'lsa), suhbatni yakunla va {EGA_ISMI} tez orada bog'lanishini ayt.

Javobni FAQAT shu JSON ko'rinishida qaytar, boshqa hech narsa yozma:
{{"javob": "odamga yuboriladigan matn", "tayyor": false, "xulosa": ""}}

Suhbat yakunlanganda "tayyor" ni true qil va "xulosa" ga {EGA_ISMI} uchun qisqa hisobot yoz
(ism, masala, maqsad, aloqa)."""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

bot = None
dp = Dispatcher()
groq_client = None


def init_runtime():
    """Bot va Groq API klientini yaratadi."""
    global bot, dp, groq_client

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi. .env faylini tekshiring.")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY topilmadi. .env faylini tekshiring.")

    if bot is None:
        bot = Bot(token=BOT_TOKEN)
    if dp is None:
        dp = Dispatcher()
    if groq_client is None:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)

    return bot, dp, groq_client


suhbatlar: dict[int, list] = {}
tugaganlar: set[int] = set()
egalar: dict[str, int] = {}


async def ega_id_ol(connection_id: str) -> int:
    """Telegram Business ulanishidan egasining chat_id sini aniqlaydi."""
    if connection_id not in egalar:
        conn = await bot.get_business_connection(connection_id)
        egalar[connection_id] = conn.user.id
    return egalar[connection_id]


async def yubor(message: types.Message, matn: str):
    """Mijozga biznes aloqa orqali javob yuboradi."""
    await bot.send_message(
        chat_id=message.chat.id,
        text=matn,
        business_connection_id=message.business_connection_id,
    )


async def ai_javob(tarix: list):
    """Groq API orqali Llama modelidan javob oladi."""
    messages = [{"role": "system", "content": TIZIM_KORSATMASI}] + tarix
    resp = await groq_client.chat.completions.create(
        model=MODEL,
        max_tokens=700,
        messages=messages,
    )
    matn = resp.choices[0].message.content.strip()
    try:
        boshi = matn.index("{")
        oxiri = matn.rindex("}") + 1
        data = json.loads(matn[boshi:oxiri])
        javob = str(data.get("javob", "")).strip() or matn
        return javob, bool(data.get("tayyor")), str(data.get("xulosa", ""))
    except (ValueError, json.JSONDecodeError):
        return matn, False, ""


def leadni_saqla(mijoz: types.User, xulosa: str):
    """Lead (mijoz ma'lumotlari)ni CSV faylga saqlaydi."""
    yangi_fayl = not os.path.exists(LEADLAR_FAYLI)
    with open(LEADLAR_FAYLI, "a", newline="", encoding="utf-8-sig") as f:
        yozuvchi = csv.writer(f)
        if yangi_fayl:
            yozuvchi.writerow(["Sana", "Ism", "Username", "Telegram ID", "Xulosa"])
        yozuvchi.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            mijoz.full_name,
            f"@{mijoz.username}" if mijoz.username else "",
            mijoz.id,
            xulosa,
        ])


async def egaga_xabar(ega_id: int, mijoz: types.User, xulosa: str):
    """Suhbat yakunlanganda bot egasiga hisobot yuboradi."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    matn = (
        "🔔 Yangi murojaat\n\n"
        f"👤 {mijoz.full_name} ({username})\n\n"
        f"{xulosa}"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn)
    except Exception as xato:
        logging.warning("Sizga xabar yuborib bo'lmadi. Bot chatiga kirib /start bosing. (%s)", xato)


@dp.message(CommandStart())
async def start_komandasi(message: types.Message):
    """Botga to'g'ridan-to'g'ri /start bosilganda ishlaydi."""
    await message.answer(
        f"Salom, {message.from_user.full_name}!\n\n"
        f"Men {EGA_ISMI}ning Telegram Business yordamchi botiman.\n\n"
        "Mijozlar shaxsiy profilingizga yozganda AI orqali suhbat qurib, "
        "aniqlangan ma'lumotlar xulosasini shu yerga yuborib turaman."
    )


@dp.business_connection()
async def ulanish_bildirishi(conn: types.BusinessConnection):
    """Telegram Business akkaunti ulanganda bildirishnoma."""
    egalar[conn.id] = conn.user.id
    logging.info("Akkaunt ulandi: @%s (faol: %s)", conn.user.username, conn.is_enabled)


@dp.business_message()
async def xabar_keldi(message: types.Message):
    """Biznes akkauntiga xabar kelganda ishlovchi asosiy funksiya."""
    ega_id = await ega_id_ol(message.business_connection_id)
    chat_id = message.chat.id

    # Agar bot egasi o'zi yozsa, AI suhbatga aralashmaydi
    if message.from_user is None or message.from_user.id == ega_id:
        tugaganlar.add(chat_id)
        return

    # Agar bu odam bilan suhbat yakunlangan bo'lsa
    if chat_id in tugaganlar:
        return

    # Faqat matnli xabarlarni qabul qiladi
    if not message.text:
        await yubor(message, "Iltimos, savolingizni matn ko'rinishida yozing.")
        return

    tarix = suhbatlar.setdefault(chat_id, [])

    # Birinchi murojaat bo'lsa salomlashadi
    if not tarix:
        tarix.append({"role": "user", "content": message.text})
        tarix.append({"role": "assistant", "content": SALOM_MATNI})
        await yubor(message, SALOM_MATNI)
        return

    # Keyingi xabarlar uchun Groq AI dan javob olinadi
    tarix.append({"role": "user", "content": message.text})
    try:
        javob, tayyor, xulosa = await ai_javob(tarix)
    except Exception as xato:
        logging.error("Groq xatosi: %s", xato)
        tarix.pop()
        await yubor(message, "Kechirasiz, hozir texnik nosozlik bor. Birozdan keyin yana yozing.")
        return

    tarix.append({"role": "assistant", "content": javob})
    await yubor(message, javob)

    # Agar kerakli ma'lumotlar yig'ilib bo'lgan bo'lsa
    if tayyor:
        tugaganlar.add(chat_id)
        leadni_saqla(message.from_user, xulosa)
        await egaga_xabar(ega_id, message.from_user, xulosa)


async def main():
    global bot, dp, groq_client
    bot, dp, groq_client = init_runtime()
    logging.info("Bot ishga tushdi. To'xtatish: Ctrl+C")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())