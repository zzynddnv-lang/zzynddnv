"""
ZUXRIDDINNING SHAXSIY AI YORDAMCHISI - Executive Personal Assistant Bot
Telegram Business (Groq Qwen 27B & Whisper Turbo)
Doimiy xotira (SQLite), Ovozli xabarlarni tushunish va Google Sheets sinxronizatsiyasi bilan.

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
    from aiohttp import web
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
#  ZUXRIDDINNING SHAXSIY AI YORDAMCHISI - KO'RSATMALAR VA PROMPT
# =====================================================================

SALOM_MATNI = (
    f"Assalomu alaykum! Men {EGA_ISMI}ning yordamchisiman. "
    f"{EGA_ISMI} hozir onlayn emas, biror gapingiz bo'lsa aytsangiz, unga yetkazib qo'yaman."
)

TIZIM_KORSATMASI = f"""Sen {EGA_ISMI}ning shaxsiy, aqlli va xushmuomala yordamchisisan. Telegram Business orqali {EGA_ISMI} nomidan murojaatchilar bilan yozishasan.

ASOSIY QOIDALAR:

1. BIRINCHI XABARDA JAVOB BERISH:
   - {EGA_ISMI} hozir onlayn emas.
   - Birinchi xabarda salomlashganda qisqa, aniq va ortiqcha gaplarsiz shunday degin:
     "Assalomu alaykum! Men {EGA_ISMI}ning yordamchisiman. {EGA_ISMI} hozir onlayn emas, biror gapingiz bo'lsa aytsangiz, unga yetkazib qo'yaman."
   - Ortiqcha gaplar, "muhim ish bilan band", uzun dostonlar yozish QAT'IYAN MAN ETILADI!
   - Agar murojaatchi birinchi xabardayoq biror aniq savol bergan bo'lsa, avval yuqoridagi gapni ayt, so'ngra savoliga 1-2 gapda lo'nda javob ber.

2. JAVOBLARNI CHO'ZMASLIK (LO'NDA VA QISQA BO'L):
   - Har doim juda qisqa, tabiiy va lo'nda yoz (1-3 gap). Uzun dostonlar, ro'yxatlar, robotcha gaplar yozma!
   - AGAR SUHBAT ALLAQACHON KETAYOTGAN BO'LSA, QAYTA SALOMLASHMA! To'g'ridan-to'g'ri mavzuga oid javob ber.

3. HAR QANDAY SAVOLGA MOS JAVOB BER (FULL AI):
   - Murojaatchi nima mavzuda (ish, biznes, taklif, savol) so'rasa ham, savoliga mos, to'g'ri va tushunarli javob ber.
   - Hech qachon "men bilmayman", "{EGA_ISMI} o'zi aytadi" deb javobsiz qoldirma. O'zing qisqa va aniq javob berib, maqsadini bilib ol.

4. SUHBATDOSHNING MAQSADINI ANIQ BILIB OLISH:
   - Murojaatchi nima maqsadda yozganini, ismi kimligini, kerak bo'lsa tashkiloti va telefon raqamini bilib olish uchun suhbatni tabiiy davom ettir.

5. {EGA_ISMI}GA HISOBOT:
   - Murojaatchi nima demoqchiligini aytgach va telefon/aloqa qoldirgach, minnatdorchilik bildir va {EGA_ISMI}ga yetkazishingni ayt.
   - Matn oxirida yangi qatordan yoz:
     [LEAD: Ismi, Telefoni, Tashkiloti/Kasbi, Murojaat mavzusi va to'liq tafsiloti]
     (Agar ma'lumot olinmagan bo'lsa, [LEAD: ...] yozma!)

Javoblaringni qisqa, odobli va oddiy samimiy insondek yoz."""


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
        raise RuntimeError("BOT_TOKEN topilmadi! Render boshqaruv panelidagi 'Environment' bo'limiga BOT_TOKEN ni kiriting.")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY topilmadi! Render boshqaruv panelidagi 'Environment' bo'limiga GROQ_API_KEY ni kiriting.")

    if bot is None:
        bot = Bot(token=BOT_TOKEN)
    if dp is None:
        dp = Dispatcher()
    if groq_client is None:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)

    # SQLite bazasini initsializatsiya qilish
    db.init_db()

    return bot, dp, groq_client


PHONE_REGEX = re.compile(r'(\+?998[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|(?:\b[389]\d[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b))')


def toza_javob_ajratish(matn: str) -> tuple[str, bool, str]:
    """
    AI modelidan qaytgan javobni tozalaydi va [LEAD: ...] hisobotini ajratadi.
    Pure text va JSON formatlarini xavfsiz qo'llab-quvvatlaydi.
    """
    matn = matn.strip()
    
    if "```" in matn:
        matn = re.sub(r"```(?:json)?", "", matn).strip()

    # 1) Agar JSON formatida qaytgan bo'lsa
    if matn.startswith("{") and matn.endswith("}"):
        try:
            data = json.loads(matn)
            if isinstance(data, dict):
                javob = str(data.get("javob", "")).strip()
                tayyor = bool(data.get("tayyor", False))
                xulosa = str(data.get("xulosa", "")).strip()
                if javob:
                    return javob, tayyor, xulosa
        except Exception:
            pass

    # 2) [LEAD: ...] maxsus hisobot tegi mavjudligini tekshirish
    lead_match = re.search(r'\[LEAD:\s*(.*?)\]', matn, re.DOTALL | re.IGNORECASE)
    if lead_match:
        xulosa = lead_match.group(1).strip()
        javob = re.sub(r'\[LEAD:\s*.*?\]', '', matn, flags=re.DOTALL | re.IGNORECASE).strip()
        return javob, True, xulosa

    return matn, False, ""


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
    """Groq API orqali tezkor va sifatli javob oladi (model fallback bilan)."""
    # Salomlashish va qisqa javob berish bo'yicha dinamik eslatma
    qoshimcha = []
    if len(tarix) > 1:
        qoshimcha = [{
            "role": "system",
            "content": "ESLATMA: Suhbat allaqachon ketmoqda. Qayta 'Salom' yoki 'Assalomu alaykum' deb salomlashma! Gapni cho'zmasdan, to'g'ridan-to'g'ri juda qisqa (1-3 gapda) javob ber."
        }]
    else:
        qoshimcha = [{
            "role": "system",
            "content": f"ESLATMA: Bu birinchi xabar. Salomlashganda FAQAT shunday degin: 'Assalomu alaykum! Men {EGA_ISMI}ning yordamchisiman. {EGA_ISMI} hozir onlayn emas, biror gapingiz bo\\'lsa aytsangiz, unga yetkazib qo\\'yaman.' Ortiqcha gap yozma!"
        }]

    messages = [{"role": "system", "content": TIZIM_KORSATMASI}] + tarix + qoshimcha
    # Dublikatlardan xoli tartiblangan model ro'yxati
    modellar = list(dict.fromkeys([MODEL, "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]))
    oxirgi_xato = None

    for m in modellar:
        try:
            resp = await groq_client.chat.completions.create(
                model=m,
                temperature=0.3,
                max_tokens=250,
                messages=messages,
            )
            matn = resp.choices[0].message.content.strip()
            if matn:
                return toza_javob_ajratish(matn)
        except Exception as e:
            oxirgi_xato = e
            logging.warning("Model '%s' da xato yuz berdi: %s. Zaxira model tekshirilmoqda...", m, e)

    raise oxirgi_xato or RuntimeError("Barcha modellar xato berdi")


async def lid_kartochkasini_shakllantirish(tarix: list, mijoz: types.User, raw_xulosa: str) -> dict:
    """Mijoz suhbati va xulosasidan to'liq shaxsiy yordamchi Murojaat Dosyesini shakllantiradi."""
    sana = datetime.now().strftime("%Y-%m-%d %H:%M")
    username = f"@{mijoz.username}" if mijoz.username else ""
    
    # Telefon raqamini xulosa yoki suhbatdan aniqlash
    tel_topildi = ""
    for qidiruv_matni in [raw_xulosa] + [m.get("content", "") for m in reversed(tarix) if m.get("role") == "user"]:
        m = PHONE_REGEX.search(qidiruv_matni)
        if m:
            tel_topildi = m.group(0)
            break

    karta = {
        "sana": sana,
        "ism": mijoz.full_name or "Noma'lum murojaatchi",
        "telefon": tel_topildi or "Ko'rsatilmagan",
        "username": username,
        "telegram_id": mijoz.id,
        "tashkilot": "Ko'rsatilmagan",
        "mavzu": "Umumiy murojaat",
        "muhimlik": "Oddiy",
        "izoh": raw_xulosa,
        "holat": "🟡 Yangi murojaat",
    }

    # AI orqali har bir maydonni aniq ajratib olish (JSON)
    prompt = (
        f"Quyidagi suhbat asosida {EGA_ISMI} uchun MUROJAAT DOSYESI (Shaxsiy hisobot) tuz.\n"
        "Faqat quyidagi kalitlar bilan toza JSON qaytar, boshqa hech narsa yozma:\n"
        "{\n"
        '  "ism": "Murojaatchi ismi (suhbatda aytilgan bo\'lsa)",\n'
        '  "telefon": "Telefon raqami",\n'
        '  "tashkilot": "Kompaniyasi, tashkiloti yoki kasbi/sohasi (agar aytilgan bo\'lsa)",\n'
        '  "mavzu": "Murojaatning qisqa mavzusi (masalan: Hamkorlik taklifi, Ish masalasi, Uchrashuv so\'rovi, Xizmat taklifi, Shaxsiy savol)",\n'
        '  "muhimlik": "Shoshilinch yoki Oddiy",\n'
        '  "izoh": "Suhbatning to\'liq xulosasi: nima haqida gaplashildi, Zuxriddindan nima kutyapti (2-3 gap)"\n'
        "}\n\n"
        f"Telegram ismi: {mijoz.full_name}\n"
        f"Oxirgi xulosa: {raw_xulosa}\n"
        f"Suhbat:\n" + "\n".join([f"{m.get('role')}: {m.get('content')}" for m in tarix[-8:]])
    )

    try:
        resp = await groq_client.chat.completions.create(
            model=MODEL,
            temperature=0.1,
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        javob_matn = resp.choices[0].message.content.strip()
        if "```" in javob_matn:
            javob_matn = re.sub(r"```(?:json)?", "", javob_matn).strip()
        
        json_match = re.search(r'\{.*\}', javob_matn, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            if isinstance(data, dict):
                if data.get("ism") and len(str(data["ism"])) > 1:
                    karta["ism"] = str(data["ism"]).strip()
                if data.get("telefon") and PHONE_REGEX.search(str(data["telefon"])):
                    karta["telefon"] = str(data["telefon"]).strip()
                if data.get("tashkilot"):
                    karta["tashkilot"] = str(data["tashkilot"]).strip()
                if data.get("mavzu"):
                    karta["mavzu"] = str(data["mavzu"]).strip()
                if data.get("muhimlik"):
                    karta["muhimlik"] = str(data["muhimlik"]).strip()
                if data.get("izoh"):
                    karta["izoh"] = str(data["izoh"]).strip()
    except Exception as e:
        logging.warning("Murojaat dosyesini AI orqali tuzishda xatolik: %s", e)

    return karta


async def google_sheetsga_yozish(karta: dict):
    """Yangi murojaatni Google Sheets onlayn jadvaliga webhook orqali avtomatik yozadi."""
    webhook_url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=karta,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status in (200, 201, 302) or resp.status < 400:
                    logging.info("Google Sheets jadvaliga muvaffaqiyatli saqlandi: %s (%s)", karta.get("ism"), karta.get("telefon"))
                else:
                    logging.warning("Google Sheetsga yuborishda server statusi: %s", resp.status)
    except Exception as e:
        logging.error("Google Sheetsga yozishda xatolik: %s", e)


async def leadni_saqla(chat_id: int, mijoz: types.User, karta: dict):
    """Murojaat dosyesini SQLite bazaga, CSV zaxira fayliga va Google Sheetsga saqlaydi."""
    username = karta.get("username", "")
    sana = karta.get("sana", datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    # 1) SQLite bazaga saqlash
    db.save_lead(
        chat_id=chat_id,
        full_name=karta.get("ism", mijoz.full_name),
        username=username,
        telegram_id=mijoz.id,
        xulosa=karta.get("izoh", ""),
        telefon=karta.get("telefon", ""),
        tashkilot=karta.get("tashkilot", ""),
        mavzu=karta.get("mavzu", ""),
        muhimlik=karta.get("muhimlik", "Oddiy"),
        holat=karta.get("holat", "🟡 Yangi murojaat"),
    )

    # 2) CSV zaxira fayliga yozish
    async with csv_lock:
        yangi_fayl = not os.path.exists(LEADLAR_FAYLI)
        try:
            with open(LEADLAR_FAYLI, "a", newline="", encoding="utf-8-sig") as f:
                yozuvchi = csv.writer(f)
                if yangi_fayl:
                    yozuvchi.writerow([
                        "Sana", "Murojaatchi Ismi", "Telefon", "Telegram", "Telegram ID",
                        "Tashkilot / Kasbi", "Mavzu", "Muhimlik", "Batafsil Tafsilot / Xulosa", "Holati"
                    ])
                yozuvchi.writerow([
                    sana,
                    karta.get("ism", mijoz.full_name),
                    karta.get("telefon", ""),
                    username,
                    mijoz.id,
                    karta.get("tashkilot", ""),
                    karta.get("mavzu", ""),
                    karta.get("muhimlik", ""),
                    karta.get("izoh", ""),
                    karta.get("holat", "🟡 Yangi murojaat"),
                ])
        except Exception as e:
            logging.error("Murojaatni CSV ga saqlashda xatolik: %s", e)

    # 3) Google Sheets onlayn jadvaliga avtomatik yuborish
    asyncio.create_task(google_sheetsga_yozish(karta))


async def egaga_xabar(ega_id: int, mijoz: types.User, karta: dict):
    """Suhbat yakunlanganda bot egasiga chiroyli Murojaat Dosyesi ko'rinishida hisobot yuboradi."""
    username_matn = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    mijoz_link = f"<a href='tg://user?id={mijoz.id}'>{karta.get('ism', mijoz.full_name)}</a>"
    
    tel = karta.get("telefon", "")
    tel_link = ""
    if tel and tel != "Ko'rsatilmagan":
        tel_toza = re.sub(r'[^\d+]', '', tel)
        tel_link = f"\n📞 <b>Telefon:</b> <a href='tel:{tel_toza}'>{tel}</a>"
    else:
        tel_link = f"\n📞 <b>Telefon:</b> Ko'rsatilmagan"

    muhimlik_belgi = "🔴" if "shoshilinch" in karta.get("muhimlik", "").lower() else "⚡️"

    matn = (
        "🔔 <b>YANGI MUROJAAT DOSYESI (Shaxsiy Yordamchi)</b>\n\n"
        f"👤 <b>Murojaatchi:</b> {mijoz_link} ({username_matn})\n"
        f"🆔 <b>Telegram ID:</b> <code>{mijoz.id}</code>{tel_link}\n"
        f"🏢 <b>Tashkilot / Kasbi:</b> {karta.get('tashkilot', 'Ko\'rsatilmagan')}\n"
        f"🎯 <b>Murojaat mavzusi:</b> {karta.get('mavzu', 'Umumiy murojaat')}\n"
        f"{muhimlik_belgi} <b>Muhimlik darajasi:</b> {karta.get('muhimlik', 'Oddiy')}\n\n"
        f"📝 <b>Suhbat tafsilotlari va xulosa:</b>\n{karta.get('izoh', '')}\n\n"
        f"📊 <b>Holati:</b> {karta.get('holat', '🟡 Yangi murojaat')} <i>(Google Sheetsga yozildi)</i>\n"
        "💡 <i>Murojaatchi profiliga o'tish uchun ismini bosing.</i>"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn, parse_mode="HTML")
    except Exception as xato:
        logging.warning("Sizga xabar yuborib bo'lmadi. Bot chatiga kirib /start bosing. (%s)", xato)


async def egaga_qoshimcha_xabar(ega_id: int, mijoz: types.User, karta: dict):
    """Mijoz qo'shimcha ma'lumot yozganda bot egasiga yangilangan Murojaat Dosyesi bildirishnomasi."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    mijoz_link = f"<a href='tg://user?id={mijoz.id}'>{karta.get('ism', mijoz.full_name)}</a>"
    matn = (
        "🔄 <b>YANGILANGAN MUROJAAT DOSYESI:</b>\n\n"
        f"👤 <b>Murojaatchi:</b> {mijoz_link} ({username})\n"
        f"📞 <b>Telefon:</b> {karta.get('telefon', 'Ko\'rsatilmagan')}\n"
        f"🏢 <b>Tashkilot / Kasbi:</b> {karta.get('tashkilot', '')}\n"
        f"🎯 <b>Mavzu:</b> {karta.get('mavzu', '')}\n\n"
        f"📝 <b>Yangi xulosa:</b>\n{karta.get('izoh', '')}"
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
        f"🤖 Men sizning (<b>{EGA_ISMI}</b>) Telegram Business shaxsiy AI yordamchingizman.\n"
        "Siz onlayn bo'lmagan vaqtingizda murojaatchilar bilan muloqot qilaman, har qanday savollariga mos javob beraman, maqsadini aniqlab, sizga to'liq dosye yuboraman!\n\n"
        "Buyruqlar:\n"
        "• /leads — Oxirgi kelgan murojaatlar dosyesi\n"
        "• /export — Barcha murojaatlarni Excel (CSV) faylda yuklab olish\n"
        "• /stats — Umumiy statistika (Baza bo'yicha)\n"
        "• /resume &lt;chat_id&gt; — Chatda botni qayta faollashtirish\n"
        "• /reset &lt;chat_id&gt; — Chat xotirasini tozalash\n"
        "• /help — Yordam va qo'llanma",
        parse_mode="HTML"
    )


@dp.message(Command("leads"))
async def leads_komandasi(message: types.Message):
    """Oxirgi kelgan murojaatlarni SQLite bazasidan ko'rsatish."""
    oxirgi_leadlar = db.get_recent_leads(limit=5)
    if not oxirgi_leadlar:
        await message.answer("Hozircha yangi murojaatlar mavjud emas.")
        return

    javob = "📋 <b>Oxirgi 5 ta Murojaat Dosyesi:</b>\n\n"
    for idx, row in enumerate(oxirgi_leadlar, 1):
        keys = row.keys() if hasattr(row, 'keys') else []
        username_matn = f"@{row['username']}" if row['username'] and not str(row['username']).startswith('@') else (row['username'] or 'yo\'q')
        mijoz_link = f"<a href='tg://user?id={row['telegram_id']}'>{row['full_name']}</a>"
        tel = row['telefon'] if 'telefon' in keys and row['telefon'] else 'Aniqlanmagan'
        mavzu = row['mavzu'] if 'mavzu' in keys and row['mavzu'] else 'Umumiy'
        tashkilot = row['tashkilot'] if 'tashkilot' in keys and row['tashkilot'] else ''
        tashkilot_matn = f" ({tashkilot})" if tashkilot else ""
        
        javob += (
            f"<b>{idx}. {mijoz_link}</b> ({username_matn}) — <i>{row['created_at']}</i>\n"
            f"📞 <code>{tel}</code> | 🎯 {mavzu}{tashkilot_matn}\n"
            f"📝 {row['xulosa']}\n\n"
        )

    await message.answer(javob, parse_mode="HTML")


@dp.message(Command("export"))
@dp.message(Command("excel"))
async def export_komandasi(message: types.Message):
    """Murojaatlar ro'yxatini to'liq ustunlar bilan Excel/CSV fayl ko'rinishida yuboradi."""
    all_leads = db.get_all_leads()
    if not all_leads:
        await message.answer("Hozircha saqlangan murojaatlar mavjud emas.")
        return

    # CSV faylni to'liq va yangilangan holda shakllantiramiz
    async with csv_lock:
        try:
            with open(LEADLAR_FAYLI, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Sana", "Murojaatchi Ismi", "Telefon", "Telegram", "Telegram ID",
                    "Tashkilot / Kasbi", "Mavzu", "Muhimlik", "Xulosa / Tafsilot", "Holati"
                ])
                for r in all_leads:
                    keys = r.keys() if hasattr(r, 'keys') else []
                    writer.writerow([
                        r["id"] if "id" in keys else "",
                        r["created_at"] if "created_at" in keys else "",
                        r["full_name"] if "full_name" in keys else "",
                        r["telefon"] if "telefon" in keys else "",
                        r["username"] if "username" in keys else "",
                        r["telegram_id"] if "telegram_id" in keys else "",
                        r["tashkilot"] if "tashkilot" in keys else "",
                        r["mavzu"] if "mavzu" in keys else "",
                        r["muhimlik"] if "muhimlik" in keys else "",
                        r["xulosa"] if "xulosa" in keys else "",
                        r["holat"] if "holat" in keys else "Yangi murojaat",
                    ])
        except Exception as e:
            logging.error("CSV yozishda xato: %s", e)

    try:
        fayl = types.FSInputFile(LEADLAR_FAYLI, filename=f"Zuxriddin_Murojaatlar_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        await message.answer_document(
            document=fayl,
            caption="📊 <b>Barcha kelgan murojaatlar dosyesi</b>\nUshbu faylni Excel dasturida to'liq jadval ko'rinishida ko'rishingiz mumkin.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"Faylni yuborishda xatolik yuz berdi: {e}")


@dp.message(Command("stats"))
async def stats_komandasi(message: types.Message):
    """Statistika buyrug'i (SQLite bazasidan)."""
    stats = db.get_stats()
    matn = (
        f"📊 <b>{EGA_ISMI} Shaxsiy Yordamchisi Statistikasi</b>\n\n"
        f"👥 Jami qabul qilingan murojaatlar: <b>{stats['total_leads']} ta</b>\n"
        f"💬 Faol suhbatlar: <b>{stats['active_chats']} ta</b>\n"
        f"✅ Yakunlangan suhbatlar: <b>{stats['completed_chats']} ta</b>\n\n"
        f"🧠 AI modeli: <code>{MODEL}</code>\n"
        f"🎙 Ovoz modeli: <code>{WHISPER_MODEL}</code>"
    )
    await message.answer(matn, parse_mode="HTML")


@dp.message(Command("resume"))
async def resume_komandasi(message: types.Message):
    """Bot egasi mijoz bilan gaplashib bo'lgach, botni ushbu chatda yana faollashtirish."""
    qismlar = message.text.split()
    if len(qismlar) > 1 and qismlar[1].lstrip("-").isdigit():
        target_id = int(qismlar[1])
        db.clear_owner_activity(target_id)
        await message.answer(f"✅ Chat <code>{target_id}</code> da bot qayta faollashtirildi. Endi mijoz yozsa, bot darhol javob beradi.", parse_mode="HTML")
    else:
        await message.answer("Iltimos, chat ID sini kiriting. Masalan:\n<code>/resume 12345678</code>", parse_mode="HTML")


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
        f"💡 <b>{EGA_ISMI} Shaxsiy Yordamchisi Qo'llanmasi:</b>\n\n"
        "1. Bot Telegram Business orqali shaxsiy akkauntingizga ulangan bo'lishi kerak.\n"
        f"2. Siz onlayn bo'lmaganingizda yozgan har qanday odamga yordamchi javob beradi va maqsadini to'liq aniqlaydi.\n"
        "3. Suhbatdosh matn, <b>ovoz (voice)</b>, <b>video-xabar (kruglyash)</b>, <b>rasm</b> yoki <b>kontakt</b> yuborsa ham bot to'liq tushunadi.\n"
        "4. Suhbatdoshning kimligi va maqsadi aniqlangach, sizga to'liq dosye yuboriladi va Google Sheets jadvalingizga yoziladi.\n"
        "5. Agar siz suhbatdoshga o'zingiz yozsangiz, bot 30 daqiqa davomida suhbatga xalaqit bermaydi. Qayta faollashtirish uchun: <code>/resume &lt;chat_id&gt;</code>.",
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

    # Agar bot egasi o'zi yozsa, faollik vaqtini saqlaydi va bot javob qaytarmaydi
    if message.from_user is None or message.from_user.id == ega_id:
        db.record_owner_activity(chat_id)
        return

    # Agar bot egasi so'nggi 30 daqiqada ushbu mijoz bilan o'zi gaplashgan bo'lsa,
    # bot jonli suhbatga xalaqit bermaydi
    if db.is_owner_recently_active(chat_id, minutes=30):
        logging.info("Chat %s da bot egasi faol, bot aralashmaydi.", chat_id)
        return

    # 1) Xabar turini aniqlash (Matn, Kontakt, Rasm, Lokatsiya, Ovoz, Kruglyash, Audio, Hujjat)
    xabar_matni = ""
    if message.text:
        xabar_matni = message.text.strip()
    elif message.contact:
        # Murojaatchi Telegram orqali telefon raqamini (kontakt) ulashdi
        tel = message.contact.phone_number
        ism = f"{message.contact.first_name or ''} {message.contact.last_name or ''}".strip()
        xabar_matni = f"Mening ismim: {ism}, telefon raqamim: {tel}. {EGA_ISMI} bilan bog'lanish uchun o'z kontakt ma'lumotlarimni qoldirdim."
    elif message.photo:
        # Murojaatchi rasm yubordi
        caption = message.caption.strip() if message.caption else ""
        if caption:
            xabar_matni = f"[Murojaatchi rasm yubordi va izoh yozdi]: {caption}"
        else:
            xabar_matni = f"Murojaatchi rasm yubordi. Rasm uchun minnatdorchilik bildirib, {EGA_ISMI}ga bu rasm bo'yicha qanday masala yoki taklif borligini so'ra."
    elif message.location:
        # Murojaatchi lokatsiya yubordi
        lat, lon = message.location.latitude, message.location.longitude
        xabar_matni = f"Murojaatchi manzil lokatsiyasini yubordi (Kenglik: {lat}, Uzunlik: {lon}). Lokatsiya qabul qilinganini va {EGA_ISMI}ga yetkazilishini bildir."
    elif message.voice:
        # Telegram ovozli xabarini (voice) Whisper orqali matnga o'giramiz
        xabar_matni = await ovozni_matnga_aylantirish(message.voice.file_id, "voice.ogg")
        if not xabar_matni:
            await yubor(message, "Kechirasiz, ovozli xabaringizni aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.")
            return
    elif message.video_note:
        # Telegram kruglyash (dumaloq video) ovozini Whisper orqali matnga o'giramiz
        xabar_matni = await ovozni_matnga_aylantirish(message.video_note.file_id, "video_note.mp4")
        if not xabar_matni:
            await yubor(message, "Kechirasiz, video xabardagi ovozni aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.")
            return
    elif message.audio:
        # Oddiy audio faylni Whisper orqali matnga o'giramiz
        xabar_matni = await ovozni_matnga_aylantirish(message.audio.file_id, "audio.mp3")
        if not xabar_matni:
            await yubor(message, "Kechirasiz, audio xabaringizni aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.")
            return
    elif message.document:
        caption = message.caption.strip() if message.caption else ""
        xabar_matni = f"[Mijoz hujjat/fayl yubordi]: {caption}" if caption else "Mijoz fayl yubordi. Savolingizni matn ko'rinishida yozing."
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

        # Mijozga 'yozmoqda...' (typing) statusini darhol ko'rsatish
        try:
            await bot.send_chat_action(chat_id=message.chat.id, action="typing", business_connection_id=message.business_connection_id)
        except Exception:
            pass

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

        # Agar murojaatchi xabarida telefon raqami bo'lsa, zaxira sifatida lead deb belgilaymiz
        if not tayyor and PHONE_REGEX.search(xabar_matni):
            tayyor = True
            if not xulosa:
                xulosa = f"Murojaatchi telefon raqami qoldirdi: {xabar_matni}"

        db.add_message(chat_id, "assistant", javob)
        await yubor(message, javob)

        # Agar ma'lumotlar yig'ilgan yoki yangilangan bo'lsa (Murojaat dosyesi shakllantiriladi)
        if tayyor and xulosa:
            eski_xulosa = db.get_last_lead_summary(chat_id)
            karta = await lid_kartochkasini_shakllantirish(tarix, message.from_user, xulosa)
            if not eski_xulosa:
                # Birinchi marta to'liq hisobot shakllandi
                db.mark_chat_completed(chat_id)
                await leadni_saqla(chat_id, message.from_user, karta)
                await egaga_xabar(ega_id, message.from_user, karta)
            elif xulosa.strip() != eski_xulosa.strip():
                # Yangi yoki qo'shimcha ma'lumot kiritildi
                await leadni_saqla(chat_id, message.from_user, karta)
                await egaga_qoshimcha_xabar(ega_id, message.from_user, karta)


# =====================================================================
#  RENDER CLOUD UCHUN HEALTH CHECK WEB SERVER VA ISHGA TUSHIRISH
# =====================================================================

async def handle_ping(request):
    """Render yoki Uptime monitoring uchun Health Check javobi."""
    return web.json_response({
        "status": "online",
        "service": f"{EGA_ISMI} Shaxsiy AI Yordamchisi",
        "owner": EGA_ISMI,
        "message": "Bot 24/7 faol ishlamoqda! 🟢"
    })


async def start_web_server():
    """Render Free Web Service talab qiladigan HTTP serverni ishga tushiradi."""
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Render HTTP Health Check server %s-portda ishga tushdi.", port)
    return runner


async def main():
    global bot, dp, groq_client
    bot, dp, groq_client = init_runtime()

    # 1) Render Web Service uchun port ochish va health-check serverni yoqish
    runner = await start_web_server()

    logging.info("AKFA Savdo Boti muvaffaqiyatli ishga tushdi! To'xtatish uchun: Ctrl + C")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())