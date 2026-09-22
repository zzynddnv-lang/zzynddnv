"""
ZUXRIDDIN YORDAMCHISI - AKFA Mahsulotlari bo'yicha Professional Savdo Boti
Telegram Business (Groq Qwen 27B & Whisper)
Doimiy xotira (SQLite) va Ovozli xabarlarni tushunish tizimi bilan.

O'rnatish:
    pip install -r requirements.txt

Ishga tushirish:
    python zuxriddin_yordamchi_bot.py
    yoki run.bat faylini bosing.
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

import database as db


# =====================================================================
#  SOZLAMALAR (.env faylidan o'qiladi)
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
EGA_ISMI = os.getenv("EGA_ISMI", "Zuxriddin")

# O'zbek tilida yuqori aniqlikda ishlovchi model
MODEL = os.getenv("MODEL", "qwen/qwen3.8-27b")
WHISPER_MODEL = "whisper-large-v3-turbo"

# Fayllar saqlanadigan asosiy papka
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADLAR_FAYLI = os.path.join(BASE_DIR, "leadlar.csv")

# Suhbat tarixi hajmi
MAX_TARIX = 14

# =====================================================================
#  AKFA MAHSULOTLARI VA SAVDO KO'RSATMALARI
# =====================================================================

SALOM_MATNI = (
    f"Assalomu alaykum! Xush kelibsiz! 👋\n\n"
    f"Men {EGA_ISMI}ning shaxsiy yordamchisi va AKFA mahsulotlari bo'yicha professional maslahatchiman.\n\n"
    "Bizning sifatli mahsulotlarimiz va boshlang'ich narxlarimiz:\n\n"
    "🪟 <b>Derazalar (romlar)</b> — 1 000 000 so'mdan boshlanadi\n"
    "🚪 <b>Eshiklar</b> (xona, kirish, vanna, surilma) — 1 000 000 so'mdan boshlanadi\n"
    "🏢 <b>Fasad vitrajlari va surilma (slayding) tizimlar</b>\n"
    "🦟 <b>Moskitka (chivin to'rlari:</b> oddiy va plisse/garmoshka)\n\n"
    "✨ <b>Nega aynan AKFA?</b>\n"
    "• 🛡 10 yilgacha rasmiy kafolat\n"
    "• 📏 Mutaxassisimiz tomonidan <b>BEPUL o'lchash (zamer)</b> xizmati\n"
    "• ❄️ Qishda sovuqdan, yozda oftob issig'idan 100% himoya (Solar oynalar)\n\n"
    "Sizga aynan qaysi mahsulot kerak edi? O'lchami yoki xona turi ma'lummi?"
)

TIZIM_KORSATMASI = f"""Sen {EGA_ISMI}ning shaxsiy savdo yordamchisi va AKFA mahsulotlari bo'yicha professional maslahatchisan. Telegram'da mijozlar bilan muloqot qilasan.

SENING ASOSIY VAZIFANG:
1. Mijozlarga AKFA mahsulotlari (eshiklar, derazalar/romlar, fasad vitrajlari, chivin to'rlari) haqida to'liq, TARTIBLI va qiziqarli ma'lumot berish.
2. Har qanday savolga O'ZING aniq, batafsil va chiroyli javob ber. Hech qachon javobni qisqa (masalan 'Salom! Xush' yoki 'AK') qilib to'xtatma! "Zuxriddin o'zi aytadi" deb javobdan qochma!
3. Matnlarni juda TARTIBLI, paragraflarga bo'lib, chiroyli emoji va punktlar (•) bilan yoz.
4. Narx, sifat, muddat, o'lcham va kafolat bo'yicha savollarga professional javob ber.
5. Mijozning ehtiyojini aniqlab, mutaxassis bepul borib o'lchab (zamer qilib) berishi uchun mijozning ismi va telefon raqamini olish.

AKFA MAHSULOTLARI VA NARXLAR BAZASI:
• 🚪 Eshiklar: 1 dona sifatli AKFA eshigi narxi 1 000 000 so'mdan boshlanadi.
  - Xona eshiklari, kirish eshiklari, sanuzel/vanna uchun namlikka chidamli eshiklar va surilma (slayding) eshiklar.
• 🪟 Derazalar (romlar): 1 dona standart AKFA oynasi narxi 1 000 000 so'mdan boshlanadi.
  - 1 yoki 2 kamerali germetik oyna paketlar.
• Profil turlari:
  - AKFA Plastik (PVX): Trio (3 kamerali, tejamkor), Quattro (4 kamerali, yuqori issiqlik va shovqin himoyasi), Engelberg (premium daraja).
  - AKFA Alyuminiy: Aldoks (engil va qulay), Termo seriya (qishda sovuq o'tkazmaydigan termo-ko'prikli maxsus alyuminiy).
• Ranglar: Oq (klassik), Karamel, Oltin eman (zolotoy dub), Antratsit kulrang, Mokko va boshqa yog'och teksturalar.
• Oyna paketlar: Energiya tejamkor Solar shishalar (yozda oftob issig'ini qaytaradi, qishda xonadagi issiqlikni saqlaydi), shovqin to'suvchi germetik shishalar.
• Qo'shimcha mahsulotlar: 🦟 Moskitka (chivin to'rlari: oddiy va plisse/garmoshka), podokonniklar, mustahkam turk va nemis furnituralari.
• Kafolat va Xizmatlar: 🛡 10 yilgacha rasmiy kafolat, Toshkent va viloyatlar bo'yicha yetkazib berish va eng muhimi — 📏 BEPUL O'LCHASH (ZAMER) xizmati mavjud!

SAVOLLARGA MOS JAVOB BERISH QOIDALARI:

1. AGAR MIJOZ SALOMLASHSA (masalan: "salom", "assalomu alaykum", "qalesiz"):
   Doim samimiy va juda TARTIBLI javob ber. Quyidagi tartibda yoz:
   - Salomlashish va o'zingni tanishtirish ({EGA_ISMI}ning yordamchisi va AKFA maslahatchisi).
   - Mahsulotlar ro'yxatini va boshlang'ich narxlarini ko'rsatish:
     🪟 Derazalar — 1 000 000 so'mdan boshlanadi
     🚪 Eshiklar — 1 000 000 so'mdan boshlanadi
     🏢 Fasad vitrajlari va surilma tizimlar
     🦟 Moskitka (chivin to'rlari)
   - Afzalliklarimiz: 10 yil kafolat, bepul zamer (o'lchash).
   - Mijozdan qaysi mahsulot kerakligini so'rash.

2. AGAR MIJOZ NARX SO'RASA (masalan: "narxlar qancha?", "necha pul?", "eshik qancha?", "deraza narxi?"):
   - Eshiklar 1 000 000 so'mdan, derazalar 1 000 000 so'mdan boshlanishini aniq ayt.
   - Aniq narx o'lchamga, profil turiga (plastik yoki alyuminiy) va rangiga bog'liqligini tushuntir.
   - Mutaxassisimiz uyingizga borib BEPUL o'lchab (zamer qilib) berishi va aniq narx chiqarishini ayt.
   - Nechta dona kerakligini yoki o'lchamlari bor-yo'qligini so'ra.

3. AGAR MIJOZ ANIQ BIR MAHSULOT SO'RASA (masalan: "4 ta eshik kerak", "deraza kerak"):
   - O'sha mahsulot bo'yicha darhol ma'lumot ber (boshlang'ich narxi 1 000 000 so'm, turlari, ranglari).
   - O'lchamlari bormi yoki mutaxassisimiz bepul o'lchab berishi uchun manzil/telefon qoldirishini so'ra.

4. AGAR KAFOLAT YOKI SIFAT SO'RASA:
   - 10 yil rasmiy kafolat, sovuq va shovqindan 100% himoya, sifatli nemis/turk furnituralarini ta'kidla.

5. AGAR MIJOZ TELEFON RAQAM YOKI ISMINI YOZSA:
   - Minnatdorchilik bildir, {EGA_ISMI} va mutaxassis tez orada bog'lanishini ayt. "tayyor": true qil.

JAVOB FORMATI:
Faqat va faqat quyidagi JSON formatida javob ber, tashqarisiga hech qanday ortiqcha matn qo'shma:
{{
  "javob": "Mijozga yuboriladigan chiroyli, tartibli va to'liq matn",
  "tayyor": false,
  "xulosa": ""
}}
Mijozning telefon raqami yoki aniq buyurtmasi ma'lum bo'lganda "tayyor": true qil va "xulosa" ga {EGA_ISMI} uchun batafsil hisobot yoz."""


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

bot = None
dp = Dispatcher()
groq_client = None

# Xotira va muloqot boshqaruvi
egalar: dict[str, int] = {}
chat_locks = defaultdict(asyncio.Lock)
csv_lock = asyncio.Lock()


def init_runtime():
    """Bot va Groq API klientini yaratadi hamda bazani tekshiradi."""
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

    # SQLite bazasini initsializatsiya qilish
    db.init_db()

    return bot, dp, groq_client


def toza_javob_ajratish(matn: str) -> tuple[str, bool, str]:
    """
    AI modelidan qaytgan matndan javob, tayyor va xulosani xavfsiz ajratib oladi.
    Mijozga xom JSON kodlari yoki chala so'zlar ko'rinib qolmasligini kafolatlaydi.
    """
    matn = matn.strip()
    
    if "```" in matn:
        matn = re.sub(r"```(?:json)?", "", matn).strip()

    # 1) To'g'ridan-to'g'ri to'liq JSON sifatida o'qish
    try:
        data = json.loads(matn)
        if isinstance(data, dict):
            javob = str(data.get("javob", "")).strip()
            tayyor = bool(data.get("tayyor", False))
            xulosa = str(data.get("xulosa", "")).strip()
            if len(javob) >= 15:
                return javob, tayyor, xulosa
    except Exception:
        pass

    # 2) Matn ichidagi birinchi { va oxirgi } orqali JSON topish
    boshi = matn.find("{")
    oxiri = matn.rfind("}")
    if boshi != -1 and oxiri != -1 and oxiri > boshi:
        try:
            data = json.loads(matn[boshi : oxiri + 1])
            if isinstance(data, dict):
                javob = str(data.get("javob", "")).strip()
                tayyor = bool(data.get("tayyor", False))
                xulosa = str(data.get("xulosa", "")).strip()
                if len(javob) >= 15:
                    return javob, tayyor, xulosa
        except Exception:
            pass

    # 3) Regex orqali "javob" va "xulosa" ni ajratish (re.DOTALL bilan)
    match_javob = re.search(r'"javob"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', matn, re.DOTALL)
    if match_javob:
        try:
            javob = match_javob.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        except Exception:
            javob = match_javob.group(1)
        tayyor = '"tayyor": true' in matn.lower() or '"tayyor":true' in matn.lower()
        match_xulosa = re.search(r'"xulosa"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', matn, re.DOTALL)
        xulosa = match_xulosa.group(1) if match_xulosa else ""
        if len(javob.strip()) >= 15:
            return javob.strip(), tayyor, xulosa.strip()

    # 4) Tozalangan matnni tekshirish
    tozalangan = re.sub(r'["{}\[\]]', '', matn).strip()
    if len(tozalangan) >= 20:
        return tozalangan, False, ""

    # Chala yoki qisqa matn yuzaga kelmasligi uchun to'liq standart javob
    return SALOM_MATNI, False, ""


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


async def ovozni_matnga_aylantirish(file_id: str, fayl_nomi: str = "voice.ogg") -> str:
    """Telegram ovozli xabarini yuklab olib, Groq Whisper orqali matnga o'giradi."""
    try:
        file_info = await bot.get_file(file_id)
        file_bytes_io = await bot.download_file(file_info.file_path)
        audio_bytes = file_bytes_io.read()

        transcription = await groq_client.audio.transcriptions.create(
            file=(fayl_nomi, audio_bytes),
            model=WHISPER_MODEL,
        )
        matn = transcription.text.strip()
        logging.info("Ovoz matnga aylantirildi: '%s'", matn)
        return matn
    except Exception as e:
        logging.error("Whisper orqali ovozni tanishda xatolik: %s", e)
        return ""


async def ai_javob(tarix: list) -> tuple[str, bool, str]:
    """Groq API orqali javob oladi (native json_object va model fallback bilan)."""
    messages = [{"role": "system", "content": TIZIM_KORSATMASI}] + tarix
    modellar = [MODEL, "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
    oxirgi_xato = None

    for m in modellar:
        try:
            resp = await groq_client.chat.completions.create(
                model=m,
                temperature=0.3,
                max_tokens=1200,
                response_format={"type": "json_object"},
                messages=messages,
            )
            matn = resp.choices[0].message.content.strip()
            return toza_javob_ajratish(matn)
        except Exception as e:
            oxirgi_xato = e
            logging.warning("Model '%s' da xato yuz berdi: %s. Zaxira model tekshirilmoqda...", m, e)

    raise oxirgi_xato or RuntimeError("Barcha modellar xato berdi")


async def leadni_saqla(chat_id: int, mijoz: types.User, xulosa: str):
    """Leadni ham SQLite bazaga, ham CSV zaxira fayliga saqlaydi."""
    username = f"@{mijoz.username}" if mijoz.username else ""
    
    # 1) SQLite bazaga saqlash
    db.save_lead(
        chat_id=chat_id,
        full_name=mijoz.full_name,
        username=username,
        telegram_id=mijoz.id,
        xulosa=xulosa,
    )

    # 2) CSV zaxira fayliga yozish
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
                    username,
                    mijoz.id,
                    xulosa,
                ])
        except Exception as e:
            logging.error("Leadni CSV ga saqlashda xatolik: %s", e)


async def egaga_xabar(ega_id: int, mijoz: types.User, xulosa: str):
    """Suhbat yakunlanganda bot egasiga hisobot yuboradi."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    matn = (
        "🔔 <b>Yangi mijoz murojaati (AKFA buyurtma)</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz.full_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{mijoz.id}</code>\n\n"
        f"📋 <b>Buyurtma tafsilotlari va xulosa:</b>\n{xulosa}"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn, parse_mode="HTML")
    except Exception as xato:
        logging.warning("Sizga xabar yuborib bo'lmadi. Bot chatiga kirib /start bosing. (%s)", xato)


async def egaga_qoshimcha_xabar(ega_id: int, mijoz: types.User, xulosa: str):
    """Mijoz qo'shimcha ma'lumot yozganda bot egasiga bildirishnoma."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    matn = (
        "🔔 <b>Mijozdan yangilangan buyurtma ma'lumoti:</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz.full_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{mijoz.id}</code>\n\n"
        f"📝 <b>Yangi xulosa:</b>\n{xulosa}"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn, parse_mode="HTML")
    except Exception as xato:
        logging.warning("Sizga qo'shimcha xabar yuborib bo'lmadi. (%s)", xato)


# =====================================================================
#  BOT EGASI UCHUN ADMIN BUYRUQLARI
# =====================================================================

@dp.message(CommandStart())
async def start_komandasi(message: types.Message):
    """Bot egasi /start bosganida status xabari."""
    await message.answer(
        f"Assalomu alaykum, <b>{message.from_user.full_name}</b>!\n\n"
        f"🤖 Men sizning (<b>{EGA_ISMI}</b>) AKFA mahsulotlari bo'yicha Telegram Business savdo yordamchingizman.\n"
        "Mijozlarga deraza, eshik, narxlar va sifat bo'yicha to'liq maslahat beraman, matnli va <b>ovozli (voice)</b> xabarlarni tushunaman!\n\n"
        "Buyruqlar:\n"
        "• /leads — Oxirgi kelgan buyurtmalar (leadlar) ro'yxati\n"
        "• /stats — Umumiy statistika (Baza bo'yicha)\n"
        "• /reset &lt;chat_id&gt; — Chatni qayta faollashtirish\n"
        "• /help — Yordam va qo'llanma",
        parse_mode="HTML"
    )


@dp.message(Command("leads"))
async def leads_komandasi(message: types.Message):
    """Oxirgi kelgan mijozlarni SQLite bazasidan ko'rsatish."""
    oxirgi_leadlar = db.get_recent_leads(limit=5)
    if not oxirgi_leadlar:
        await message.answer("Hozircha yangi murojaatlar (leadlar) mavjud emas.")
        return

    javob = "📋 <b>Oxirgi 5 ta murojaat:</b>\n\n"
    for idx, row in enumerate(oxirgi_leadlar, 1):
        javob += (
            f"{idx}. <b>{row['full_name']}</b> ({row['username'] or 'username yoq'}) "
            f"— <i>{row['created_at']}</i>\n"
            f"📝 {row['xulosa']}\n\n"
        )

    await message.answer(javob, parse_mode="HTML")


@dp.message(Command("stats"))
async def stats_komandasi(message: types.Message):
    """Statistika buyrug'i (SQLite bazasidan)."""
    stats = db.get_stats()
    matn = (
        "📊 <b>Bot Statistikasi (AKFA Baza)</b>\n\n"
        f"👥 Jami qabul qilingan leadlar: <b>{stats['total_leads']} ta</b>\n"
        f"💬 Faol suhbatlar: <b>{stats['active_chats']} ta</b>\n"
        f"✅ Yakunlangan suhbatlar: <b>{stats['completed_chats']} ta</b>\n\n"
        f"🧠 Matn modeli: <code>{MODEL}</code>\n"
        f"🎙 Ovoz modeli: <code>{WHISPER_MODEL}</code>"
    )
    await message.answer(matn, parse_mode="HTML")


@dp.message(Command("reset"))
async def reset_komandasi(message: types.Message):
    """Chat holatini qayta faollashtirish (sinovlar uchun)."""
    qismlar = message.text.split()
    if len(qismlar) > 1 and qismlar[1].lstrip("-").isdigit():
        target_id = int(qismlar[1])
        db.clear_chat_history(target_id)
        await message.answer(f"✅ Chat <code>{target_id}</code> xotirasi tozalandi va qayta faollashtirildi.", parse_mode="HTML")
    else:
        await message.answer("Iltimos, chat ID sini kiriting. Masalan:\n<code>/reset 12345678</code>", parse_mode="HTML")


@dp.message(Command("help"))
async def help_komandasi(message: types.Message):
    """Yordam bo'limi."""
    await message.answer(
        "💡 <b>AKFA Savdo Boti Qo'llanmasi:</b>\n\n"
        "1. Bot Telegram Business orqali shaxsiy akkauntingizga ulangan bo'lishi kerak.\n"
        "2. Yangi mijoz yozganda AI AKFA derazalari, eshiklari, narxlari va sifati bo'yicha mustaqil maslahat beradi.\n"
        "3. Mijozning telefon raqami va buyurtma tafsilotlari aniqlangach, sizga bildirishnoma yuboradi.\n"
        "4. Suhbat yakunlanganidan keyin ham mijoz yozsa, doim muloyim javob berishda davom etadi.\n"
        "5. Agar siz mijozga o'zingiz yozsangiz, bot sizning suhbatingizga xalaqit bermaydi.",
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

    # Agar bot egasi o'zi yozsa, bot o'z egasiga javob qaytarmaydi
    if message.from_user is None or message.from_user.id == ega_id:
        return

    # 1) Xabar turini aniqlash (Matn yoki Ovoz)
    xabar_matni = ""
    if message.text:
        xabar_matni = message.text.strip()
    elif message.voice:
        # Telegram ovozli xabarini (voice) Whisper orqali matnga o'giramiz
        xabar_matni = await ovozni_matnga_aylantirish(message.voice.file_id, "voice.ogg")
        if not xabar_matni:
            await yubor(message, "Kechirasiz, ovozli xabaringizni aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.")
            return
    elif message.audio:
        # Oddiy audio faylni Whisper orqali matnga o'giramiz
        xabar_matni = await ovozni_matnga_aylantirish(message.audio.file_id, "audio.mp3")
        if not xabar_matni:
            await yubor(message, "Kechirasiz, audio xabaringizni aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.")
            return
    else:
        await yubor(message, "Iltimos, savolingizni matn yoki ovozli xabar ko'rinishida yuboring.")
        return

    # 2) Poyga holatini (race condition) oldini olish uchun chat lock
    async with chat_locks[chat_id]:
        # Agar suhbatdan buyon 12 soatdan ko'p vaqt o'tgan bo'lsa, yangi sessiya sifatida yangilaymiz
        oxirgi_vaqt = db.get_last_message_time(chat_id)
        if oxirgi_vaqt and (datetime.now() - oxirgi_vaqt).total_seconds() > 12 * 3600:
            db.clear_chat_history(chat_id)

        # Suhbat tarixini bazadan olish
        tarix = db.get_chat_history(chat_id, limit=MAX_TARIX)

        # Har qanday xabar (birinchi murojaat bo'lsa ham) bazaga va AI ga yuboriladi.
        # Bu orqali mijoz birinchi xabardayoq savol bersa ham, bot darhol savoliga mos javob beradi.
        db.add_message(chat_id, "user", xabar_matni)
        tarix.append({"role": "user", "content": xabar_matni})

        try:
            javob, tayyor, xulosa = await ai_javob(tarix)
        except Exception as xato:
            logging.error("Groq xatosi: %s", xato)
            db.delete_last_message(chat_id)
            await yubor(message, SALOM_MATNI)
            return

        db.add_message(chat_id, "assistant", javob)
        await yubor(message, javob)

        # Agar ma'lumotlar yig'ilgan yoki yangilangan bo'lsa
        if tayyor and xulosa:
            eski_xulosa = db.get_last_lead_summary(chat_id)
            if not eski_xulosa:
                # Birinchi marta to'liq hisobot shakllandi
                db.mark_chat_completed(chat_id)
                await leadni_saqla(chat_id, message.from_user, xulosa)
                await egaga_xabar(ega_id, message.from_user, xulosa)
            elif xulosa.strip() != eski_xulosa.strip():
                # Yangi yoki qo'shimcha ma'lumot kiritildi
                await leadni_saqla(chat_id, message.from_user, xulosa)
                await egaga_qoshimcha_xabar(ega_id, message.from_user, xulosa)


# =====================================================================
#  BOTNI ISHGA TUSHIRISH
# =====================================================================

async def main():
    global bot, dp, groq_client
    bot, dp, groq_client = init_runtime()
    logging.info("AKFA Savdo Boti muvaffaqiyatli ishga tushdi! To'xtatish uchun: Ctrl + C")
    
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())