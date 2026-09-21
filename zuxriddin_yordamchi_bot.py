"""
ZUXRIDDIN YORDAMCHISI - Telegram Business bot (Groq / Llama asosida)
Mukammallashtirilgan va xavfsiz versiya (Production-ready)

O'rnatish:
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
import re
from collections import defaultdict
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import CommandStart, Command
    from aiogram.exceptions import TelegramAPIError
    from groq import AsyncGroq
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Kerakli paketlar topilmadi. Quyidagi buyruqni ishga tushiring:\n"
        "pip install -r requirements.txt"
    ) from exc


# =====================================================================
#  SOZLAMALAR (.env faylidan o'qiladi)
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
EGA_ISMI = os.getenv("EGA_ISMI", "Zuxriddin")
MODEL = os.getenv("MODEL", "llama-3.1-8b-instant")

# Fayllar saqlanadigan asosiy papka
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADLAR_FAYLI = os.path.join(BASE_DIR, "leadlar.csv")

# Suhbat tarixi hajmi (tokenlarni tejash va tezlik uchun)
MAX_TARIX = 12

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
- O'zbek tilida, samimiy va lo'nda gapir (1-3 gap). Odam boshqa tilda yozsa, o'sha tilda javob ber.
- Bir vaqtda faqat bitta savol ber.
- Narx, chegirma, muddat va boshqa narsalarni o'ylab topma va va'da qilma. Bilmasang: "Buni {EGA_ISMI} o'zi aniq aytadi" de.
- O'zingni {EGA_ISMI}ning yordamchisi deb tanishtir. Odam so'rasa, sen sun'iy intellekt ekaningni yashirma.
- Yetarli ma'lumot yig'ilgach (kamida masala va maqsad ma'lum bo'lsa), suhbatni yakunla va {EGA_ISMI} tez orada bog'lanishini ayt.

Javobni FAQAT quyidagi JSON ko'rinishida qaytar, oldidan yoki ketidan hech qanday boshqa matn yozma:
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

# Operativ xotira va muloqot boshqaruvi
suhbatlar: dict[int, list] = {}
tugaganlar: set[int] = set()
egalar: dict[str, int] = {}

# Har bir chat uchun alohida lock (poyga holatini oldini olish)
chat_locks = defaultdict(asyncio.Lock)
# CSV faylga xavfsiz yozish uchun lock
csv_lock = asyncio.Lock()


def init_runtime():
    """Bot va Groq API klientini yaratadi."""
    global bot, dp, groq_client

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env fayliga BOT_TOKEN=... ni kiriting.")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY topilmadi! .env fayliga GROQ_API_KEY=... ni kiriting.")

    if bot is None:
        bot = Bot(token=BOT_TOKEN)
    if dp is None:
        dp = Dispatcher()
    if groq_client is None:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)

    return bot, dp, groq_client


def toza_javob_ajratish(matn: str) -> tuple[str, bool, str]:
    """
    AI modelidan qaytgan matndan javob, tayyor va xulosani xavfsiz ajratib oladi.
    Mijozga hech qachon xom JSON kodlari ko'rinib qolmasligini kafolatlaydi.
    """
    matn = matn.strip()
    
    # Agar model javobni markdown code block ichiga olgan bo'lsa
    if "```" in matn:
        matn = re.sub(r"```(?:json)?", "", matn).strip()

    # 1-urinish: Standart JSON parsing
    boshi = matn.find("{")
    oxiri = matn.rfind("}")
    if boshi != -1 and oxiri != -1 and oxiri > boshi:
        try:
            data = json.loads(matn[boshi : oxiri + 1])
            javob = str(data.get("javob", "")).strip()
            tayyor = bool(data.get("tayyor", False))
            xulosa = str(data.get("xulosa", "")).strip()
            if javob:
                return javob, tayyor, xulosa
        except Exception:
            pass

    # 2-urinish: Regex orqali "javob" maydonini ajratish
    match_javob = re.search(r'"javob"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', matn)
    if match_javob:
        try:
            javob = match_javob.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        except Exception:
            javob = match_javob.group(1)
        tayyor = '"tayyor": true' in matn.lower() or '"tayyor":true' in matn.lower()
        match_xulosa = re.search(r'"xulosa"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', matn)
        xulosa = match_xulosa.group(1) if match_xulosa else ""
        return javob.strip(), tayyor, xulosa.strip()

    # 3-urinish: Agar model JSON qaytarmasa, qavs va skript belgilarini tozalash
    tozalangan = re.sub(r'["{}\[\]]', '', matn).strip()
    if tozalangan:
        return tozalangan, False, ""

    return f"Salom, men {EGA_ISMI}ning yordamchisiman. Sizga qanday yordam bera olaman?", False, ""


async def ega_id_ol(connection_id: str) -> int:
    """Telegram Business ulanishidan egasining chat_id sini aniqlaydi."""
    if connection_id not in egalar:
        conn = await bot.get_business_connection(connection_id)
        egalar[connection_id] = conn.user.id
    return egalar[connection_id]


async def yubor(message: types.Message, matn: str):
    """Mijozga biznes aloqa orqali xavfsiz javob yuboradi."""
    try:
        await bot.send_message(
            chat_id=message.chat.id,
            text=matn,
            business_connection_id=message.business_connection_id,
        )
    except TelegramAPIError as e:
        logging.error("Xabar yuborishda Telegram API xatosi (chat_id: %s): %s", message.chat.id, e)


async def ai_javob(tarix: list) -> tuple[str, bool, str]:
    """Groq API orqali Llama modelidan javob oladi."""
    messages = [{"role": "system", "content": TIZIM_KORSATMASI}] + tarix
    resp = await groq_client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        max_tokens=600,
        messages=messages,
    )
    matn = resp.choices[0].message.content.strip()
    return toza_javob_ajratish(matn)


async def leadni_saqla(mijoz: types.User, xulosa: str):
    """Lead (mijoz ma'lumotlari)ni CSV faylga asinxron va xavfsiz saqlaydi."""
    async with csv_lock:
        yangi_fayl = not os.path.exists(LEADLAR_FAYLI)
        try:
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
        except Exception as e:
            logging.error("Leadni CSV ga saqlashda xatolik: %s", e)


async def egaga_xabar(ega_id: int, mijoz: types.User, xulosa: str):
    """Suhbat yakunlanganda bot egasiga hisobot yuboradi."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    matn = (
        "🔔 <b>Yangi mijoz murojaati</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz.full_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{mijoz.id}</code>\n\n"
        f"📋 <b>Xulosa:</b>\n{xulosa}"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn, parse_mode="HTML")
    except Exception as xato:
        logging.warning("Sizga xabar yuborib bo'lmadi. Bot chatiga kirib /start bosing. (%s)", xato)


# =====================================================================
#  BOT EGASI UCHUN ADMIN BUYRUQLARI
# =====================================================================

@dp.message(CommandStart())
async def start_komandasi(message: types.Message):
    """Bot egasi /start bosganida status xabari."""
    await message.answer(
        f"Assalomu alaykum, <b>{message.from_user.full_name}</b>!\n\n"
        f"🤖 Men sizning (<b>{EGA_ISMI}</b>) Telegram Business shaxsiy yordamchingizman.\n\n"
        "Buyruqlar:\n"
        "• /leads — Oxirgi kelgan mijozlar ro'yxati\n"
        "• /stats — Umumiy statistika\n"
        "• /help — Yordam va sozlamalar",
        parse_mode="HTML"
    )


@dp.message(Command("leads"))
async def leads_komandasi(message: types.Message):
    """Oxirgi kelgan mijozlarni ko'rsatish."""
    if not os.path.exists(LEADLAR_FAYLI):
        await message.answer("Hozircha yangi murojaatlar (leadlar) mavjud emas.")
        return

    try:
        oxirgi_leadlar = []
        with open(LEADLAR_FAYLI, "r", encoding="utf-8-sig") as f:
            reader = list(csv.reader(f))
            qatorlar = [q for q in reader if q and q[0] != "Sana"]
            oxirgi_leadlar = qatorlar[-5:]

        if not oxirgi_leadlar:
            await message.answer("Mijozlar bazasi hali bo'sh.")
            return

        javob = "📋 <b>Oxirgi 5 ta murojaat:</b>\n\n"
        for idx, row in enumerate(reversed(oxirgi_leadlar), 1):
            sana, ism, user, uid, xulosa = (row + [""] * 5)[:5]
            javob += f"{idx}. <b>{ism}</b> ({user}) — <i>{sana}</i>\n📝 {xulosa}\n\n"

        await message.answer(javob, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Leadlarni o'qishda xatolik: {e}")


@dp.message(Command("stats"))
async def stats_komandasi(message: types.Message):
    """Statistika buyrug'i."""
    lead_soni = 0
    if os.path.exists(LEADLAR_FAYLI):
        with open(LEADLAR_FAYLI, "r", encoding="utf-8-sig") as f:
            rows = [r for r in csv.reader(f) if r and r[0] != "Sana"]
            lead_soni = len(rows)

    faol_suhbatlar = len(suhbatlar)
    tugagan_suhbatlar = len(tugaganlar)

    matn = (
        "📊 <b>Bot Statistikasi</b>\n\n"
        f"👥 Jami qabul qilingan leadlar: <b>{lead_soni} ta</b>\n"
        f"💬 Hozirgi faol suhbatlar: <b>{faol_suhbatlar} ta</b>\n"
        f"✅ Yakunlangan suhbatlar: <b>{tugagan_suhbatlar} ta</b>\n"
        f"🧠 Ishlatilayotgan AI model: <code>{MODEL}</code>"
    )
    await message.answer(matn, parse_mode="HTML")


@dp.message(Command("help"))
async def help_komandasi(message: types.Message):
    """Yordam bo'limi."""
    await message.answer(
        "💡 <b>Botdan foydalanish bo'yicha qo'llanma:</b>\n\n"
        "1. Telegram Business sozlamalarida ushbu bot Chatbot sifatida ulangan bo'lishi kerak.\n"
        "2. Yangi mijoz shaxsiy akkauntingizga yozganda AI avtomatik javob beradi.\n"
        "3. Suhbat yakunlanishi bilan sizga hisobot keladi va CSV faylga saqlanadi.\n"
        "4. Agar siz mijozga o'zingiz yozsangiz, bot avtomatik aralashishni to'xtatadi.",
        parse_mode="HTML"
    )


# =====================================================================
#  TELEGRAM BUSINESS ASOSIY ISHLOVCHILARI
# =====================================================================

@dp.business_connection()
async def ulanish_bildirishi(conn: types.BusinessConnection):
    """Telegram Business akkaunti ulanganda bildirishnoma."""
    egalar[conn.id] = conn.user.id
    logging.info("Biznes akkaunt ulandi: @%s (faol: %s)", conn.user.username, conn.is_enabled)


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

    # Poyga holatini (race condition) oldini olish uchun chat lock ishlatamiz
    async with chat_locks[chat_id]:
        tarix = suhbatlar.setdefault(chat_id, [])

        # Birinchi murojaat bo'lsa salomlashadi
        if not tarix:
            tarix.append({"role": "user", "content": message.text})
            tarix.append({"role": "assistant", "content": SALOM_MATNI})
            await yubor(message, SALOM_MATNI)
            return

        # Suhbat tarixini qisqartirish (Sliding window)
        if len(tarix) > MAX_TARIX:
            tarix = tarix[-MAX_TARIX:]
            suhbatlar[chat_id] = tarix

        # Keyingi xabarlar uchun Groq AI dan javob olinadi
        tarix.append({"role": "user", "content": message.text})
        try:
            javob, tayyor, xulosa = await ai_javob(tarix)
        except Exception as xato:
            logging.error("Groq xatosi: %s", xato)
            tarix.pop()
            await yubor(message, "Kechirasiz, hozir texnik yangilanish ketmoqda. Birozdan so'ng yana yozing.")
            return

        tarix.append({"role": "assistant", "content": javob})
        await yubor(message, javob)

        # Agar kerakli ma'lumotlar yig'ilib bo'lgan bo'lsa
        if tayyor:
            tugaganlar.add(chat_id)
            await leadni_saqla(message.from_user, xulosa)
            await egaga_xabar(ega_id, message.from_user, xulosa)


# =====================================================================
#  BOTNI ISHGA TUSHIRISH
# =====================================================================

async def main():
    global bot, dp, groq_client
    bot, dp, groq_client = init_runtime()
    logging.info("Bot muvaffaqiyatli ishga tushdi! To'xtatish uchun: Ctrl + C")
    
    # MUHIM TUZATISH: Telegram Business update'larini majburiy ro'yxatdan o'tkazish
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())