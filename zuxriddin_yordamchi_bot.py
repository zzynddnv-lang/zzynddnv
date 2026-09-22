"""
ZUXRIDDIN YORDAMCHISI - Telegram Business bot (Groq Llama / Qwen & Whisper)
Doimiy xotira (SQLite) va Ovozli xabarlarni tushunish (Voice-to-Text) tizimi bilan.

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

# Suhbat tarixi hajmi (tokenlarni tejash uchun)
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
- Agar odam 'Qo'lingdan nima keladi?' yoki 'Nima ish qilasan?' deb so'rasa: 'Men {EGA_ISMI}ning yordamchisiman, sizning murojaatingiz va savollaringizni qabul qilib, {EGA_ISMI}ga aniq yetkazaman' deb tushuntir va qanday masalada yozayotganini so'ra.
- Agar '{EGA_ISMI} kim?' deb so'rasa: '{EGA_ISMI} mening rahbarim. Siz u kishiga qanday masalada murojaat qilmoqchi edingiz?' deb chiroyli yo'naltir.
- Narx, chegirma, muddat va boshqa narsalarni o'ylab topma va va'da qilma. Bilmasang: 'Buni {EGA_ISMI} o'zi aniq aytadi' de.
- O'zingni {EGA_ISMI}ning yordamchisi deb tanishtir. Odam so'rasa, sen sun'iy intellekt ekaningni yashirma.
- Yetarli ma'lumot yig'ilgach (kamida masala va maqsad ma'lum bo'lsa), suhbatni yakunla va {EGA_ISMI} tez orada bog'lanishini ayt.
- Agar odam bilan avval suhbat yakunlangan bo'lsa va u yana yozsa (masalan: "rahmat", "kutaman", "qachon bog'lanadi?", yangi savol yoki qo'shimcha ma'lumot):
  - Har doim samimiy va xushmuomala javob qaytar (masalan: "Arziydi! {EGA_ISMI} tez orada siz bilan bog'lanadi", "Qo'shimcha savolingizni {EGA_ISMI}ga yetkazib qo'yaman").
  - Agar yangi yoki yangilangan ma'lumot bersa, uni xulosaga qo'shib yoz va "tayyor": true qil.
  - Hech qachon odamni javobsiz qoldirma.

Javobni FAQAT quyidagi JSON ko'rinishida qaytar, oldidan yoki ketidan hech qanday boshqa matn yozma:
{{"javob": "odamga yuboriladigan matn", "tayyor": false, "xulosa": ""}}

Suhbat yakunlanganda yoki muhim ma'lumot yig'ilganda "tayyor" ni true qil va "xulosa" ga {EGA_ISMI} uchun qisqa hisobot yoz
(ism, masala, maqsad, aloqa)."""


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
    Mijozga hech qachon xom JSON kodlari ko'rinib qolmasligini kafolatlaydi.
    """
    matn = matn.strip()
    
    if "```" in matn:
        matn = re.sub(r"```(?:json)?", "", matn).strip()

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
    """Groq API orqali javob oladi (model fallback bilan)."""
    messages = [{"role": "system", "content": TIZIM_KORSATMASI}] + tarix
    modellar = [MODEL, "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
    oxirgi_xato = None

    for m in modellar:
        try:
            resp = await groq_client.chat.completions.create(
                model=m,
                temperature=0.3,
                max_tokens=600,
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
        "🔔 <b>Yangi mijoz murojaati</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz.full_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{mijoz.id}</code>\n\n"
        f"📋 <b>Xulosa:</b>\n{xulosa}"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn, parse_mode="HTML")
    except Exception as xato:
        logging.warning("Sizga xabar yuborib bo'lmadi. Bot chatiga kirib /start bosing. (%s)", xato)


async def egaga_qoshimcha_xabar(ega_id: int, mijoz: types.User, xulosa: str):
    """Mijoz qo'shimcha ma'lumot yozganda bot egasiga bildirishnoma."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    matn = (
        "🔔 <b>Mijozdan qo'shimcha ma'lumot / xabar:</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz.full_name} ({username})\n"
        f"🆔 <b>ID:</b> <code>{mijoz.id}</code>\n\n"
        f"📝 <b>Yangilangan xulosa:</b>\n{xulosa}"
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
        f"🤖 Men sizning (<b>{EGA_ISMI}</b>) Telegram Business shaxsiy yordamchingizman.\n"
        "Men matnli va <b>ovozli (voice)</b> xabarlarni tushunaman!\n\n"
        "Buyruqlar:\n"
        "• /leads — Oxirgi kelgan mijozlar ro'yxati\n"
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
        "📊 <b>Bot Statistikasi (SQLite Baza)</b>\n\n"
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
        "💡 <b>Botdan foydalanish bo'yicha qo'llanma:</b>\n\n"
        "1. Telegram Business sozlamalarida ushbu bot Chatbot sifatida ulangan bo'lishi kerak.\n"
        "2. Yangi mijoz matn yoki <b>ovozli xabar (voice)</b> yuborganida AI avtomatik tushunadi va javob beradi.\n"
        "3. Suhbat yakunlanishi bilan sizga hisobot keladi va SQLite hamda CSV faylga saqlanadi.\n"
        "4. Suhbat yakunlanganidan keyin ham mijoz yangi savol bersa, bot unga muloyim javob qaytaradi va yangi ma'lumotlarni sizga yetkazadi.\n"
        "5. Agar siz mijozga o'zingiz yozsangiz, bot sizning xabaringizga xalaqit bermaydi.",
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

        # Birinchi murojaat bo'lsa salomlashadi
        if not tarix:
            db.add_message(chat_id, "user", xabar_matni)
            db.add_message(chat_id, "assistant", SALOM_MATNI)
            await yubor(message, SALOM_MATNI)
            return

        # Keyingi xabarlar uchun Groq AI dan javob olinadi
        db.add_message(chat_id, "user", xabar_matni)
        tarix.append({"role": "user", "content": xabar_matni})

        try:
            javob, tayyor, xulosa = await ai_javob(tarix)
        except Exception as xato:
            logging.error("Groq xatosi: %s", xato)
            db.delete_last_message(chat_id)
            await yubor(message, "Kechirasiz, tizimda vaqtinchalik uzilish bo'ldi. Birozdan so'ng yana yozing.")
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
    logging.info("Bot muvaffaqiyatli ishga tushdi! To'xtatish uchun: Ctrl + C")
    
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())