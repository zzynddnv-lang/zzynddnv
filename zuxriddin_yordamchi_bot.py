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
import html
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
    import aiohttp
    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import CommandStart, Command, Filter
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


def _idlarni_oqish(qiymat: str) -> set[int]:
    """'123, 456' ko'rinishidagi matndan Telegram ID lar to'plamini ajratadi."""
    return {int(q) for q in re.split(r"[,\s]+", qiymat or "") if q.lstrip("-").isdigit()}


# Bot egasi(lari)ning Telegram ID si. Faqat shu ID lar admin buyruqlaridan foydalana oladi
# va murojaat dosyelarini oladi. Bir nechta bo'lsa vergul bilan ajrating.
OWNER_IDS = _idlarni_oqish(os.getenv("OWNER_ID", ""))

# O'zbek tilida yuqori aniqlikda ishlovchi model (Groq)
MODEL = os.getenv("MODEL", "qwen/qwen3.8-27b")
ZAXIRA_MODELLAR = [
    m.strip() for m in os.getenv("FALLBACK_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b").split(",") if m.strip()
]
WHISPER_MODEL = "whisper-large-v3-turbo"

# Fayllar saqlanadigan asosiy papka
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADLAR_FAYLI = os.getenv("CSV_PATH") or os.path.join(BASE_DIR, "leadlar.csv")

# Suhbat tarixi hajmi
MAX_TARIX = 14

# Render Free xizmati uxlab qolmasligi uchun o'zini-o'zi ping qilish oralig'i (soniya)
KEEPALIVE_ORALIQ = 10 * 60

# =====================================================================
#  ZUXRIDDINNING SHAXSIY AI YORDAMCHISI - KO'RSATMALAR VA PROMPT
# =====================================================================

SALOM_MATNI = (
    f"Assalomu alaykum! Men {EGA_ISMI}ning yordamchisiman. "
    f"{EGA_ISMI} hozir onlayn emas, biror gapingiz bo'lsa aytsangiz, unga yetkazib qo'yaman."
)

TIZIM_KORSATMASI = f"""Sen {EGA_ISMI}ning shaxsiy, o'ta aqlli, madaniyatli va ziyoli AI yordamchisisan.
Telegram orqali {EGA_ISMI} nomidan murojaatchilar bilan muloqot qilasan.

SENING ASOSIY VAZIFANG:
1. Murojaatchining nima demoqchiligini DIQQAT BILAN, ANIQ TAHLIL QILISH.
   - O'zingdan o'zing taxmin qilib, asossiz yoki mavzudan tashqari gaplarni UMUMAN GAPIRMA!
   - Suhbatdosh nima haqida yozgan bo'lsa, aynan o'sha mavzuni tushunib, to'g'ri, mantiqiy va lo'nda javob ber.
2. Odamlar har qanday savol yoki masala bilan murojaat qilsa (biznes, ish, dasturlash, IT, takliflar, hamkorlik, fikr, maslahat, narxlar va h.k.), ularning aytgan gapini to'g'ri tushunib, savoliga mos, lo'nda va aqlli javob berish.
3. Suhbatdoshning kimligini (ismi, telefon raqami, tashkiloti yoki kasbi) va nima maqsadda yozganini aniqlab, {EGA_ISMI}ga hisobot tayyorlash.

MUHIM QOIDALAR:

1. BIRINCHI XABAR (1-MULOQOT):
   - Suhbatning eng birinchi javobini QAT'IY ravishda quyidagi jumla bilan boshlaysan:
     "{SALOM_MATNI}"
   - Agar murojaatchi birinchi xabaridayoq biror savol bergan yoki fikr bildirgan bo'lsa, ushbu salomlashish ortidan DARHOL uning aytgan gapiga mantiqan mos va to'g'ri javob ber.
   - Agar shunchaki "Salom" yoki "Assalomu alaykum" degan bo'lsa, faqatgina yuqoridagi salom jumlasi kifoya.

2. IKKINCHI VA KEYINGI XABARLAR (QAYTA SALOMLASHISH TAQIQLANADI):
   - QAYTA SALOMLASHMA! "{SALOM_MATNI}" yoki "Assalomu alaykum" deb takrorlama! Bitta gapni qaytaraverish QAT'IYAN TAQIQLANADI.
   - To'g'ridan-to'g'ri suhbatdoshning aytgan gapiga, savoliga mantiqiy javob ber va muloqotni tabiiy insondek davom ettir.

3. FOYDALANUVCHINING GAPINI ANIQ TAHLIL QILISH (O'ZINGDAN KELIB GAPIRMA):
   - Murojaatchi nima deb yozgan bo'lsa, aynan o'sha mavzu bo'yicha gapir.
   - QAT'IY QOIDA: Agar murojaatchi maktab darsligi, maktab uy vazifasi yoki misol-masala yechishni so'ramagan bo'lsa, "maktab", "misol-masala yechmayman" degan gaplarni UMUMAN TILGA OLMA VA GAPIRMA! O'z-o'zidan bu haqda gapirish qat'iyan man etiladi!
   - Faqatgina va faqatgina kimdir to'g'ridan-to'g'ri maktab uy vazifasini yoki maktab darslik misolini yechib berishni talab qilsagina, bunday vazifalar bilan shug'ullanmasligingni qisqa bildirasan.

4. ALOQA MA'LUMOTLARINI OLISH VA HISOBOT:
   - Suhbatdoshning ismi, telefon raqami va murojaat tafsilotlari olingach, minnatdorchilik bildir va {EGA_ISMI} tez orada bog'lanishini ayt.
   - Matn oxiriga yangi qatordan yoz:
     [LEAD: Ismi, Telefoni, Tashkiloti/Sohasi, Murojaat mazmuni]
     (Faqatgina ma'lumotlar olinganida yoz, aks holda bu tegni yozma!)

Javoblaringni qisqa (1-3 gap), aqlli, mantiqiy va samimiy insondek yoz."""


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
    global bot, groq_client

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env fayliga yoki Render 'Environment' bo'limiga BOT_TOKEN ni kiriting.")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY topilmadi! .env fayliga yoki Render 'Environment' bo'limiga GROQ_API_KEY ni kiriting.")

    if bot is None:
        bot = Bot(token=BOT_TOKEN)
    if groq_client is None:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)

    # SQLite bazasini initsializatsiya qilish
    db.init_db()

    if OWNER_IDS:
        logging.info("Bot egalari (OWNER_ID): %s", ", ".join(map(str, sorted(OWNER_IDS))))
    else:
        logging.warning(
            "OWNER_ID o'rnatilmagan! Xavfsizlik uchun .env ga o'z Telegram ID raqamingizni OWNER_ID sifatida yozing."
        )

    return bot, dp, groq_client


# =====================================================================
#  EGA (ADMIN) HUQUQLARINI TEKSHIRISH
# =====================================================================

def egami(user_id: int | None) -> bool:
    """
    Foydalanuvchi bot egasimi?
    - OWNER_ID o'rnatilgan bo'lsa: faqat o'sha ID lar va Telegram Business ulangan akkaunt egasi.
    - O'rnatilmagan bo'lsa: bazadagi egalar (birinchi /start bosgan yoki Business ulagan akkaunt).
    """
    if user_id is None:
        return False
    if user_id in OWNER_IDS or user_id in egalar.values():
        return True
    if not OWNER_IDS:
        return user_id in db.get_owner_ids()
    return False


def hisobot_oluvchilar(ega_id: int | None) -> set[int]:
    """Murojaat dosyesi yuboriladigan egalar ro'yxati."""
    idlar = set(OWNER_IDS)
    if ega_id:
        idlar.add(ega_id)
    if not OWNER_IDS:
        idlar.update(db.get_owner_ids())
    return idlar


class EgaFilter(Filter):
    """Admin buyruqlarini faqat bot egasiga ruxsat beruvchi filtr."""

    async def __call__(self, message: types.Message) -> bool:
        return egami(message.from_user.id if message.from_user else None)


# =====================================================================
#  YORDAMCHI FUNKSIYALAR
# =====================================================================

PHONE_REGEX = re.compile(r'(\+?998[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|(?:\b[389]\d[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b))')

KORSATILMAGAN = "Ko'rsatilmagan"


def h(qiymat) -> str:
    """Telegram HTML xabarlari uchun matnni xavfsiz qiladi (<, >, & belgilar)."""
    return html.escape(str(qiymat if qiymat is not None else ""), quote=True)


def toza_javob_ajratish(matn: str) -> tuple[str, bool, str]:
    """
    AI modelidan qaytgan javobni tozalaydi va [LEAD: ...] hisobotini ajratadi.
    Pure text va JSON formatlarini xavfsiz qo'llab-quvvatlaydi.
    """
    # Reasoning modellarning <think>...</think> fikrlash qismini olib tashlash
    matn = re.sub(r"<think>.*?</think>", "", matn, flags=re.DOTALL | re.IGNORECASE)
    if re.search(r"<think>", matn, re.IGNORECASE):
        # Yopilmagan fikrlash bloki - javob kesilib qolgan
        matn = matn[:re.search(r"<think>", matn, re.IGNORECASE).start()]
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
        except ValueError:
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


def tozalash_asossiz_maktab_rad_etish(javob: str, tarix: list) -> str:
    """
    Agar murojaatchi o'zi maktab yoki misol-masala haqida so'ramagan bo'lsa,
    model javobida asossiz paydo bo'lgan maktab misollari haqidagi gaplarni tozalaydi.
    """
    user_matnlari = " ".join([m.get("content", "") for m in tarix if m.get("role") == "user"]).lower()
    maktab_sozlari = ["maktab", "darslik", "uy vazifa", "uyga vazifa", "algebra", "geometriya", "fizika", "kimyo", "tenglama", "sinf", "mashq"]
    user_maktab_soradimi = any(s in user_matnlari for s in maktab_sozlari)

    if not user_maktab_soradimi:
        pattern = r'(?:Kechirasiz,?\s*)?(?:men\s*)?maktab\s*(?:darsliklari|misol|masala|savollari)[^.!?\n]*[.!?\n]?'
        javob = re.sub(pattern, '', javob, flags=re.IGNORECASE).strip()
    return javob


def salomni_moslash(javob: str, birinchi_muloqotmi: bool) -> str:
    """1-xabarda salom jumlasi bilan boshlanishini, keyingilarida esa qaytarilmasligini kafolatlaydi."""
    if birinchi_muloqotmi:
        if not javob.startswith("Assalomu alaykum! Men"):
            javob = f"{SALOM_MATNI}\n\n{javob}".strip()
    elif javob.startswith(SALOM_MATNI):
        javob = javob[len(SALOM_MATNI):].strip()
    elif javob.startswith(f"Assalomu alaykum! Men {EGA_ISMI}ning yordamchisiman."):
        javob = re.sub(rf"^Assalomu alaykum!\s*Men\s*{re.escape(EGA_ISMI)}ning\s*yordamchisiman\.[^.]*\.", "", javob).strip()
    return javob


async def ai_javob(tarix: list) -> tuple[str, bool, str]:
    """Groq API orqali tezkor va sifatli javob oladi (model fallback bilan)."""
    # Suhbatda yordamchi (assistant) hali biror marta javob berganmi-yo'qmi tekshiramiz
    birinchi_muloqotmi = not any(m.get("role") == "assistant" for m in tarix)

    if birinchi_muloqotmi:
        qoshimcha = [{
            "role": "system",
            "content": (
                f"DIQQAT: Bu suhbatning BIRINCHI XABARI!\n"
                f"1. Javobingni QAT'IY ravishda quyidagi jumla bilan boshlaysan:\n"
                f"   \"{SALOM_MATNI}\"\n"
                f"2. Murojaatchining aytgan gapini diqqat bilan, chuqur tahlil qil. "
                f"Agar salomdan tashqari biror savol bergan yoki fikr bildirgan bo'lsa, salom ortidan DARHOL uning aytgan gapiga mantiqan to'g'ri, mos va lo'nda javob ber.\n"
                f"3. O'zingdan o'zing asossiz narsalarni to'qima va gapirma! Suhbatdoshning ismini va aloqa ma'lumotlarini so'ra."
            )
        }]
    else:
        qoshimcha = [{
            "role": "system",
            "content": (
                f"DIQQAT: Suhbat ALLAQACHON boshlangan (bu 2- yoki undan keyingi xabar)!\n"
                f"1. QAYTA SALOMLASHMA! '{SALOM_MATNI}' yoki 'Assalomu alaykum' deb QAYTARA KO'RMA!\n"
                f"2. Faqat bitta gapni qaytaraverish QAT'IYAN TAQIQLANADI.\n"
                f"3. Murojaatchining aytgan gapini aniq tahlil qilib, to'g'ridan-to'g'ri uning savoliga yoki fikriga mantiqiy, aqlli javob ber.\n"
                f"4. Suhbatdoshning ismi, telefon raqami va murojaat maqsadini bilib olish uchun muloqotni davom ettir."
            )
        }]

    messages = [{"role": "system", "content": TIZIM_KORSATMASI}] + tarix + qoshimcha
    # Dublikatlardan xoli tartiblangan model ro'yxati
    modellar = list(dict.fromkeys([MODEL] + ZAXIRA_MODELLAR))
    oxirgi_xato = None

    for m in modellar:
        try:
            resp = await groq_client.chat.completions.create(
                model=m,
                temperature=0.3,
                max_tokens=350,
                messages=messages,
            )
            matn = (resp.choices[0].message.content or "").strip()
            javob, tayyor, xulosa = toza_javob_ajratish(matn)
            # Asossiz maktab/misol rad etishlarini tozalash
            javob = tozalash_asossiz_maktab_rad_etish(javob, tarix)
            if not javob and not birinchi_muloqotmi:
                logging.warning("Model '%s' bo'sh javob qaytardi, zaxira model tekshirilmoqda...", m)
                continue
            if m != MODEL:
                logging.info("Javob zaxira model '%s' orqali olindi.", m)
            return salomni_moslash(javob, birinchi_muloqotmi), tayyor, xulosa
        except Exception as e:
            oxirgi_xato = e
            logging.warning("Model '%s' da xato yuz berdi: %s. Zaxira model tekshirilmoqda...", m, e)

    raise oxirgi_xato or RuntimeError("Barcha modellar bo'sh javob qaytardi")


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
        "telefon": tel_topildi or KORSATILMAGAN,
        "username": username,
        "telegram_id": mijoz.id,
        "tashkilot": KORSATILMAGAN,
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
        f'  "izoh": "Suhbatning to\'liq xulosasi: nima haqida gaplashildi, {EGA_ISMI}dan nima kutyapti (2-3 gap)"\n'
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
        javob_matn = (resp.choices[0].message.content or "").strip()
        javob_matn = re.sub(r"<think>.*?</think>", "", javob_matn, flags=re.DOTALL | re.IGNORECASE)
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
                for kalit in ("tashkilot", "mavzu", "muhimlik", "izoh"):
                    if data.get(kalit):
                        karta[kalit] = str(data[kalit]).strip()
    except Exception as e:
        logging.warning("Murojaat dosyesini AI orqali tuzishda xatolik: %s", e)

    return karta


async def google_sheetsga_yozish(karta: dict) -> bool | None:
    """
    Murojaatni Google Sheets jadvaliga webhook (Apps Script) orqali yozadi.
    Qaytaradi: None - webhook sozlanmagan, True - muvaffaqiyatli, False - xatolik.
    """
    webhook_url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=karta,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status < 400:
                    logging.info("Google Sheets jadvaliga saqlandi: %s (%s)", karta.get("ism"), karta.get("telefon"))
                    return True
                logging.warning("Google Sheetsga yuborishda server statusi: %s", resp.status)
                return False
    except Exception as e:
        logging.error("Google Sheetsga yozishda xatolik: %s", e)
        return False


def _csv_faylni_yozish(leadlar) -> None:
    """Bazadagi barcha murojaatlarni CSV fayliga (Excel uchun) qayta yozadi."""
    with open(LEADLAR_FAYLI, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ID", "Sana", "Yangilangan", "Murojaatchi Ismi", "Telefon", "Telegram", "Telegram ID",
            "Tashkilot / Kasbi", "Mavzu", "Muhimlik", "Xulosa / Tafsilot", "Holati"
        ])
        for r in leadlar:
            writer.writerow([
                r["id"], r["created_at"], r["updated_at"] or "", r["full_name"], r["telefon"] or "",
                r["username"] or "", r["telegram_id"], r["tashkilot"] or "", r["mavzu"] or "",
                r["muhimlik"] or "", r["xulosa"] or "", r["holat"] or "",
            ])


async def csv_yangilash() -> bool:
    """CSV zaxira faylini bazadan to'liq qayta shakllantiradi (dublikatlarsiz)."""
    async with csv_lock:
        try:
            leadlar = await asyncio.to_thread(db.get_all_leads)
            await asyncio.to_thread(_csv_faylni_yozish, leadlar)
            return True
        except Exception as e:
            logging.error("Murojaatlarni CSV ga yozishda xatolik: %s", e)
            return False


async def leadni_saqla(chat_id: int, mijoz: types.User, karta: dict) -> tuple[bool, bool | None]:
    """
    Murojaat dosyesini SQLite bazaga, CSV zaxira fayliga va Google Sheetsga saqlaydi.
    Chat uchun dosye mavjud bo'lsa, yangi qator qo'shilmaydi - mavjudi yangilanadi.
    Qaytaradi: (yangi_dosyemi, google_sheets_holati)
    """
    yangi = await asyncio.to_thread(
        db.upsert_lead,
        chat_id=chat_id,
        full_name=karta.get("ism", mijoz.full_name),
        username=karta.get("username", ""),
        telegram_id=mijoz.id,
        xulosa=karta.get("izoh", ""),
        telefon=karta.get("telefon", ""),
        tashkilot=karta.get("tashkilot", ""),
        mavzu=karta.get("mavzu", ""),
        muhimlik=karta.get("muhimlik", "Oddiy"),
        holat=karta.get("holat", "🟡 Yangi murojaat"),
    )

    await csv_yangilash()

    # Google Sheets: Apps Script telegram_id bo'yicha mavjud qatorni yangilaydi
    sheets_holati = await google_sheetsga_yozish({**karta, "chat_id": chat_id, "yangilangan": not yangi})
    return yangi, sheets_holati


def _sheets_matni(holat: bool | None) -> str:
    if holat is True:
        return "✅ Google Sheetsga yozildi"
    if holat is False:
        return "⚠️ Google Sheetsga yozib bo'lmadi (loglarni tekshiring)"
    return "ℹ️ Google Sheets ulanmagan"


async def egalarga_yuborish(ega_id: int | None, matn: str):
    """HTML xabarni barcha bot egalariga yuboradi."""
    maqsadli_idlar = await asyncio.to_thread(hisobot_oluvchilar, ega_id)
    if not maqsadli_idlar:
        logging.warning("Ega Telegram ID si topilmadi. .env ga OWNER_ID yozing yoki botga /start yuboring.")
        return
    for target_id in maqsadli_idlar:
        try:
            await bot.send_message(chat_id=target_id, text=matn, parse_mode="HTML")
        except Exception as xato:
            logging.warning("Ega (%s) ga xabar yuborib bo'lmadi: %s", target_id, xato)


def _mijoz_havolasi(mijoz: types.User, karta: dict) -> str:
    username_matn = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    ism = karta.get("ism") or mijoz.full_name
    return f"<a href='tg://user?id={mijoz.id}'>{h(ism)}</a> ({h(username_matn)})"


async def egaga_xabar(ega_id: int | None, mijoz: types.User, karta: dict, sheets_holati: bool | None):
    """Suhbat yakunlanganda bot egasiga chiroyli Murojaat Dosyesi ko'rinishida hisobot yuboradi."""
    tel = karta.get("telefon", "")
    if tel and tel != KORSATILMAGAN:
        tel_toza = re.sub(r'[^\d+]', '', tel)
        tel_qator = f"📞 <b>Telefon:</b> <a href='tel:{h(tel_toza)}'>{h(tel)}</a>"
    else:
        tel_qator = f"📞 <b>Telefon:</b> {KORSATILMAGAN}"

    muhimlik = karta.get("muhimlik", "Oddiy")
    muhimlik_belgi = "🔴" if "shoshilinch" in muhimlik.lower() else "⚡️"

    matn = (
        "🔔 <b>YANGI MUROJAAT DOSYESI (Shaxsiy Yordamchi)</b>\n\n"
        f"👤 <b>Murojaatchi:</b> {_mijoz_havolasi(mijoz, karta)}\n"
        f"🆔 <b>Telegram ID:</b> <code>{mijoz.id}</code>\n"
        f"{tel_qator}\n"
        f"🏢 <b>Tashkilot / Kasbi:</b> {h(karta.get('tashkilot', KORSATILMAGAN))}\n"
        f"🎯 <b>Murojaat mavzusi:</b> {h(karta.get('mavzu', 'Umumiy murojaat'))}\n"
        f"{muhimlik_belgi} <b>Muhimlik darajasi:</b> {h(muhimlik)}\n\n"
        f"📝 <b>Suhbat tafsilotlari va xulosa:</b>\n{h(karta.get('izoh', ''))}\n\n"
        f"📊 <b>Holati:</b> {h(karta.get('holat', '🟡 Yangi murojaat'))}\n"
        f"<i>{_sheets_matni(sheets_holati)}</i>\n"
        "💡 <i>Murojaatchi profiliga o'tish uchun ismini bosing.</i>"
    )
    await egalarga_yuborish(ega_id, matn)


async def egaga_qoshimcha_xabar(ega_id: int | None, mijoz: types.User, karta: dict, sheets_holati: bool | None):
    """Mijoz qo'shimcha ma'lumot yozganda bot egasiga yangilangan Murojaat Dosyesi bildirishnomasi."""
    matn = (
        "🔄 <b>YANGILANGAN MUROJAAT DOSYESI:</b>\n\n"
        f"👤 <b>Murojaatchi:</b> {_mijoz_havolasi(mijoz, karta)}\n"
        f"📞 <b>Telefon:</b> {h(karta.get('telefon', KORSATILMAGAN))}\n"
        f"🏢 <b>Tashkilot / Kasbi:</b> {h(karta.get('tashkilot', ''))}\n"
        f"🎯 <b>Mavzu:</b> {h(karta.get('mavzu', ''))}\n\n"
        f"📝 <b>Yangi xulosa:</b>\n{h(karta.get('izoh', ''))}\n\n"
        f"<i>{_sheets_matni(sheets_holati)}</i>"
    )
    await egalarga_yuborish(ega_id, matn)


# =====================================================================
#  BOT EGASI UCHUN ADMIN BUYRUQLARI
# =====================================================================

BUYRUQLAR_MATNI = (
    "Buyruqlar:\n"
    "• /leads — Oxirgi kelgan murojaatlar dosyesi\n"
    "• /export — Barcha murojaatlarni Excel (CSV) faylda yuklab olish\n"
    "• /stats — Umumiy statistika (Baza bo'yicha)\n"
    "• /resume &lt;chat_id&gt; — Chatda botni qayta faollashtirish\n"
    "• /reset &lt;chat_id&gt; — Chat xotirasini tozalash\n"
    "• /help — Yordam va qo'llanma"
)


@dp.message(CommandStart())
async def start_komandasi(message: types.Message):
    """
    Bot egasi /start bosganida uni hisobotlar uchun ro'yxatga oladi.
    Begona foydalanuvchilar ega bo'lib qololmaydi.
    """
    user = message.from_user
    if user is None:
        return

    ega = egami(user.id)
    # OWNER_ID o'rnatilmagan va hali hech kim ro'yxatdan o'tmagan bo'lsa - birinchi foydalanuvchi ega bo'ladi
    if not ega and not OWNER_IDS and not db.get_owner_ids() and not egalar:
        ega = True
        logging.warning("Birinchi ega /start orqali ro'yxatga olindi: %s. OWNER_ID ni .env ga yozish tavsiya etiladi.", user.id)

    if not ega:
        await message.answer(SALOM_MATNI)
        return

    db.save_owner_id(user.id)
    await message.answer(
        f"Assalomu alaykum, <b>{h(user.full_name)}</b>!\n\n"
        f"🤖 Men sizning (<b>{h(EGA_ISMI)}</b>) Telegram shaxsiy AI yordamchingizman.\n"
        "Siz onlayn bo'lmagan vaqtingizda murojaatchilar bilan muloqot qilaman, har qanday savollariga mos javob beraman, maqsadini aniqlab, sizga to'liq dosye yuboraman!\n\n"
        f"🆔 Sizning Telegram ID: <code>{user.id}</code>"
        + ("" if OWNER_IDS else "\n⚠️ Xavfsizlik uchun ushbu raqamni <code>.env</code> / Render sozlamalariga <code>OWNER_ID</code> sifatida yozing.")
        + "\n\n" + BUYRUQLAR_MATNI,
        parse_mode="HTML"
    )


@dp.message(Command("leads"), EgaFilter())
async def leads_komandasi(message: types.Message):
    """Oxirgi kelgan murojaatlarni SQLite bazasidan ko'rsatish."""
    oxirgi_leadlar = db.get_recent_leads(limit=5)
    if not oxirgi_leadlar:
        await message.answer("Hozircha yangi murojaatlar mavjud emas.")
        return

    javob = "📋 <b>Oxirgi 5 ta Murojaat Dosyesi:</b>\n\n"
    for idx, row in enumerate(oxirgi_leadlar, 1):
        username = row["username"] or ""
        username_matn = username if username.startswith("@") or not username else f"@{username}"
        mijoz_link = f"<a href='tg://user?id={row['telegram_id']}'>{h(row['full_name'])}</a>"
        tel = row["telefon"] or "Aniqlanmagan"
        mavzu = row["mavzu"] or "Umumiy"
        tashkilot_matn = f" ({h(row['tashkilot'])})" if row["tashkilot"] else ""
        vaqt = row["updated_at"] or row["created_at"]
        username_matn = username_matn or "yo'q"

        javob += (
            f"<b>{idx}. {mijoz_link}</b> ({h(username_matn)}) — <i>{h(vaqt)}</i>\n"
            f"📞 <code>{h(tel)}</code> | 🎯 {h(mavzu)}{tashkilot_matn}\n"
            f"📝 {h(row['xulosa'])}\n\n"
        )

    await message.answer(javob, parse_mode="HTML")


@dp.message(Command("export", "excel"), EgaFilter())
async def export_komandasi(message: types.Message):
    """Murojaatlar ro'yxatini to'liq ustunlar bilan Excel/CSV fayl ko'rinishida yuboradi."""
    if not db.get_recent_leads(limit=1):
        await message.answer("Hozircha saqlangan murojaatlar mavjud emas.")
        return

    if not await csv_yangilash():
        await message.answer("CSV faylni shakllantirishda xatolik yuz berdi.")
        return

    try:
        fayl = types.FSInputFile(LEADLAR_FAYLI, filename=f"{EGA_ISMI}_Murojaatlar_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        await message.answer_document(
            document=fayl,
            caption="📊 <b>Barcha kelgan murojaatlar dosyesi</b>\nUshbu faylni Excel dasturida to'liq jadval ko'rinishida ko'rishingiz mumkin.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"Faylni yuborishda xatolik yuz berdi: {e}")


@dp.message(Command("stats"), EgaFilter())
async def stats_komandasi(message: types.Message):
    """Statistika buyrug'i (SQLite bazasidan)."""
    stats = db.get_stats()
    sheets = "ulangan ✅" if os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip() else "ulanmagan"
    matn = (
        f"📊 <b>{h(EGA_ISMI)} Shaxsiy Yordamchisi Statistikasi</b>\n\n"
        f"👥 Jami murojaat dosyelari: <b>{stats['total_leads']} ta</b>\n"
        f"💬 Dosye shakllanmagan suhbatlar: <b>{stats['active_chats']} ta</b>\n"
        f"✅ Dosye shakllangan suhbatlar: <b>{stats['completed_chats']} ta</b>\n\n"
        f"🧠 AI modeli: <code>{h(MODEL)}</code>\n"
        f"🔁 Zaxira modellar: <code>{h(', '.join(ZAXIRA_MODELLAR) or '-')}</code>\n"
        f"🎙 Ovoz modeli: <code>{WHISPER_MODEL}</code>\n"
        f"📄 Google Sheets: {sheets}"
    )
    await message.answer(matn, parse_mode="HTML")


def _chat_id_ajratish(message: types.Message) -> int | None:
    qismlar = (message.text or "").split()
    if len(qismlar) > 1 and qismlar[1].lstrip("-").isdigit():
        return int(qismlar[1])
    return None


@dp.message(Command("resume"), EgaFilter())
async def resume_komandasi(message: types.Message):
    """Bot egasi mijoz bilan gaplashib bo'lgach, botni ushbu chatda yana faollashtirish."""
    target_id = _chat_id_ajratish(message)
    if target_id is None:
        await message.answer("Iltimos, chat ID sini kiriting. Masalan:\n<code>/resume 12345678</code>", parse_mode="HTML")
        return
    db.clear_owner_activity(target_id)
    await message.answer(f"✅ Chat <code>{target_id}</code> da bot qayta faollashtirildi. Endi mijoz yozsa, bot darhol javob beradi.", parse_mode="HTML")


@dp.message(Command("reset"), EgaFilter())
async def reset_komandasi(message: types.Message):
    """Chat holatini qayta faollashtirish (sinovlar uchun)."""
    target_id = _chat_id_ajratish(message)
    if target_id is None:
        await message.answer("Iltimos, chat ID sini kiriting. Masalan:\n<code>/reset 12345678</code>", parse_mode="HTML")
        return
    db.clear_chat_history(target_id)
    await message.answer(f"✅ Chat <code>{target_id}</code> xotirasi tozalandi va qayta faollashtirildi.", parse_mode="HTML")


@dp.message(Command("help"), EgaFilter())
async def help_komandasi(message: types.Message):
    """Yordam bo'limi."""
    await message.answer(
        f"💡 <b>{h(EGA_ISMI)} Shaxsiy Yordamchisi Qo'llanmasi:</b>\n\n"
        "1. Bot Telegram Business orqali shaxsiy akkauntingizga ulangan bo'lishi kerak.\n"
        "2. Siz onlayn bo'lmaganingizda yozgan har qanday odamga yordamchi javob beradi va maqsadini to'liq aniqlaydi.\n"
        "3. Suhbatdosh matn, <b>ovoz (voice)</b>, <b>video-xabar (kruglyash)</b>, <b>rasm</b> yoki <b>kontakt</b> yuborsa ham bot to'liq tushunadi.\n"
        "4. Suhbatdoshning kimligi va maqsadi aniqlangach, sizga to'liq dosye yuboriladi va Google Sheets jadvalingizga yoziladi.\n"
        "5. Agar siz suhbatdoshga o'zingiz yozsangiz, bot 30 daqiqa davomida suhbatga xalaqit bermaydi. Qayta faollashtirish uchun: <code>/resume &lt;chat_id&gt;</code>.\n\n"
        + BUYRUQLAR_MATNI,
        parse_mode="HTML"
    )


# =====================================================================
#  TELEGRAM BUSINESS ASOSIY ISHLOVCHILARI
# =====================================================================

@dp.business_connection()
async def ulanish_bildirishi(conn: types.BusinessConnection):
    """Telegram Business akkaunti ulanganda bildirishnoma."""
    egalar[conn.id] = conn.user.id
    # Business akkaunt egasi haqiqiy ega - hisobotlar unga ham yuboriladi
    await asyncio.to_thread(db.save_owner_id, conn.user.id)
    logging.info("Biznes akkaunt ulandi: @%s (faol: %s)", conn.user.username, conn.is_enabled)


async def javob_yubor(message: types.Message, matn: str, is_business: bool = True):
    """Biznes yoki oddiy chat orqali mijozga xavfsiz javob yuboradi."""
    if is_business and message.business_connection_id:
        await yubor(message, matn)
    else:
        try:
            await message.answer(matn)
        except Exception as e:
            logging.error("Xabar yuborishda xatolik: %s", e)


async def xabar_matnini_olish(message: types.Message, is_business: bool) -> str | None:
    """Xabar turini aniqlab (Matn, Kontakt, Rasm, Lokatsiya, Ovoz, Kruglyash, Audio, Hujjat) matnga aylantiradi."""
    if message.text:
        return message.text.strip()
    if message.contact:
        # Murojaatchi Telegram orqali telefon raqamini (kontakt) ulashdi
        tel = message.contact.phone_number
        ism = f"{message.contact.first_name or ''} {message.contact.last_name or ''}".strip()
        return f"Mening ismim: {ism}, telefon raqamim: {tel}. {EGA_ISMI} bilan bog'lanish uchun o'z kontakt ma'lumotlarimni qoldirdim."
    if message.photo:
        caption = message.caption.strip() if message.caption else ""
        if caption:
            return f"[Murojaatchi rasm yubordi va izoh yozdi]: {caption}"
        return f"Murojaatchi rasm yubordi. Rasm uchun minnatdorchilik bildirib, {EGA_ISMI}ga bu rasm bo'yicha qanday masala yoki taklif borligini so'ra."
    if message.location:
        lat, lon = message.location.latitude, message.location.longitude
        return f"Murojaatchi manzil lokatsiyasini yubordi (Kenglik: {lat}, Uzunlik: {lon}). Lokatsiya qabul qilinganini va {EGA_ISMI}ga yetkazilishini bildir."

    # Ovozli xabar, kruglyash va audio Whisper orqali matnga o'giriladi
    for media, fayl_nomi, turi in (
        (message.voice, "voice.ogg", "ovozli xabaringizni"),
        (message.video_note, "video_note.mp4", "video xabardagi ovozni"),
        (message.audio, "audio.mp3", "audio xabaringizni"),
    ):
        if media:
            matn = await ovozni_matnga_aylantirish(media.file_id, fayl_nomi)
            if not matn:
                await javob_yubor(message, f"Kechirasiz, {turi} aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.", is_business)
                return None
            return matn

    if message.document:
        caption = message.caption.strip() if message.caption else ""
        return f"[Mijoz hujjat/fayl yubordi]: {caption}" if caption else "Mijoz fayl yubordi. Savolingizni matn ko'rinishida yozing."

    await javob_yubor(message, "Iltimos, savolingizni matn yoki ovozli xabar ko'rinishida yuboring.", is_business)
    return None


async def xabarni_qayta_ishlash(message: types.Message, is_business: bool = True):
    """Kelgan xabarni (matn, ovoz, rasm, kontakt) qayta ishlab, AI orqali javob qaytaradi."""
    chat_id = message.chat.id
    ega_id = None

    if is_business and message.business_connection_id:
        ega_id = await ega_id_ol(message.business_connection_id)
        # Agar bot egasi o'zi yozsa, faollik vaqtini saqlaydi va bot javob qaytarmaydi
        if message.from_user is None or message.from_user.id == ega_id:
            await asyncio.to_thread(db.record_owner_activity, chat_id)
            return

        # Agar bot egasi so'nggi 30 daqiqada ushbu mijoz bilan o'zi gaplashgan bo'lsa,
        # bot jonli suhbatga xalaqit bermaydi
        if await asyncio.to_thread(db.is_owner_recently_active, chat_id, 30):
            logging.info("Chat %s da bot egasi faol, bot aralashmaydi.", chat_id)
            return

    # 1) Xabar turini aniqlash
    xabar_matni = await xabar_matnini_olish(message, is_business)
    if not xabar_matni:
        return

    # 2) Poyga holatini (race condition) oldini olish uchun chat lock
    async with chat_locks[chat_id]:
        # Agar suhbatdan buyon 12 soatdan ko'p vaqt o'tgan bo'lsa, yangi sessiya sifatida yangilaymiz
        oxirgi_vaqt = await asyncio.to_thread(db.get_last_message_time, chat_id)
        if oxirgi_vaqt and (datetime.now() - oxirgi_vaqt).total_seconds() > 12 * 3600:
            await asyncio.to_thread(db.clear_chat_history, chat_id)

        # Suhbat tarixini bazadan olish
        tarix = await asyncio.to_thread(db.get_chat_history, chat_id, MAX_TARIX)

        # Mijozga 'yozmoqda...' (typing) statusini darhol ko'rsatish
        try:
            if is_business and message.business_connection_id:
                await bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=message.business_connection_id)
            else:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        # Har qanday xabar (birinchi murojaat bo'lsa ham) bazaga va AI ga yuboriladi.
        await asyncio.to_thread(db.add_message, chat_id, "user", xabar_matni)
        tarix.append({"role": "user", "content": xabar_matni})

        try:
            javob, tayyor, xulosa = await ai_javob(tarix)
        except Exception as xato:
            logging.error("Groq xatosi: %s", xato)
            await asyncio.to_thread(db.delete_last_message, chat_id)
            await javob_yubor(message, SALOM_MATNI, is_business)
            return

        # Agar murojaatchi xabarida telefon raqami bo'lsa, zaxira sifatida lead deb belgilaymiz
        if not tayyor and PHONE_REGEX.search(xabar_matni):
            tayyor = True
            if not xulosa:
                xulosa = f"Murojaatchi telefon raqami qoldirdi: {xabar_matni}"

        await asyncio.to_thread(db.add_message, chat_id, "assistant", javob)
        await javob_yubor(message, javob, is_business)

        # Agar ma'lumotlar yig'ilgan yoki yangilangan bo'lsa (Murojaat dosyesi shakllantiriladi)
        if tayyor and xulosa:
            eski_xulosa = await asyncio.to_thread(db.get_last_lead_summary, chat_id)
            if eski_xulosa and xulosa.strip() == eski_xulosa.strip():
                return

            karta = await lid_kartochkasini_shakllantirish(tarix, message.from_user, xulosa)
            if eski_xulosa:
                karta["holat"] = "🔄 Yangilangan murojaat"
            yangi, sheets_holati = await leadni_saqla(chat_id, message.from_user, karta)
            if yangi:
                # Birinchi marta to'liq hisobot shakllandi
                await asyncio.to_thread(db.mark_chat_completed, chat_id)
                await egaga_xabar(ega_id, message.from_user, karta, sheets_holati)
            else:
                # Yangi yoki qo'shimcha ma'lumot kiritildi
                await egaga_qoshimcha_xabar(ega_id, message.from_user, karta, sheets_holati)


@dp.business_message()
async def xabar_keldi_biznes(message: types.Message):
    """Biznes akkauntiga xabar kelganda ishlovchi asosiy funksiya."""
    await xabarni_qayta_ishlash(message, is_business=True)


@dp.message(F.chat.type == "private")
async def xabar_keldi_shaxsiy(message: types.Message):
    """Foydalanuvchi bot chatiga to'g'ridan-to'g'ri (private) yozganda ishlovchi funksiya."""
    # Buyruqlar (shu jumladan ruxsatsiz admin buyruqlari) AI ga yuborilmaydi
    if message.text and message.text.startswith("/"):
        return
    await xabarni_qayta_ishlash(message, is_business=False)


# =====================================================================
#  RENDER CLOUD UCHUN HEALTH CHECK WEB SERVER VA ISHGA TUSHIRISH
# =====================================================================

async def handle_ping(request):
    """Render yoki Uptime monitoring uchun Health Check javobi."""
    return web.json_response({
        "status": "online",
        "service": f"{EGA_ISMI} Shaxsiy AI Yordamchisi",
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
    logging.info("HTTP Health Check server %s-portda ishga tushdi.", port)
    return runner


async def keepalive_loop(url: str):
    """
    Render Free xizmati 15 daqiqa so'rov kelmasa uxlab qoladi va bot to'xtaydi.
    Shuning uchun har 10 daqiqada o'zining ommaviy manziliga ping yuboramiz.
    """
    ping_url = url.rstrip("/") + "/health"
    logging.info("Keep-alive yoqildi: %s (har %s soniyada)", ping_url, KEEPALIVE_ORALIQ)
    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(KEEPALIVE_ORALIQ)
            try:
                async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    logging.debug("Keep-alive ping: %s", resp.status)
            except Exception as e:
                logging.warning("Keep-alive ping xatosi: %s", e)


async def main():
    init_runtime()

    # 1) Render Web Service uchun port ochish va health-check serverni yoqish
    runner = await start_web_server()

    # 2) Render Free uxlab qolmasligi uchun keep-alive (Render RENDER_EXTERNAL_URL ni o'zi beradi)
    keepalive_url = os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    keepalive_task = asyncio.create_task(keepalive_loop(keepalive_url)) if keepalive_url else None

    logging.info("%s Shaxsiy AI Yordamchisi muvaffaqiyatli ishga tushdi! To'xtatish uchun: Ctrl + C", EGA_ISMI)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        if keepalive_task:
            keepalive_task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
