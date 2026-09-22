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

TIZIM_KORSATMASI = f"""Sen {EGA_ISMI}ning shaxsiy savdo yordamchisi va AKFA mahsulotlari bo'yicha PROFESSIONAL, AQLLI SUN'IY INTELLEKT (FULL AI) maslahatchisisan. Telegram Business orqali mijozlar bilan muloqot qilasan.

SENING ASOSIY XARAKTERING VA QOIDALARING:

1. FAQAT BIRINCHI XABARDA SALOMLASH:
   - Agar suhbat endi boshlangan bo'lsa (tarix bo'sh bo'lsa yoki mijoz salomlashsa), bir marta samimiy salomlash va o'zingni {EGA_ISMI}ning yordamchisi deb tanishtir.
   - AGAR SUHBAT ALLAQACHON KETAYOTGAN BO'LSA (tarixda kamida bitta xabar bo'lsa), QAYTA SALOMLASHMA! Har gapda "Salom", "Assalomu alaykum", "Xush kelibsiz" so'zlarini takrorlash QAT'IYAN MAN ETILADI! To'g'ridan-to'g'ri berilgan savolga mos javob ber.

2. FULL AI — HAR QANDAY SAVOLGA MOS VA JONLI JAVOB BER:
   - Mijoz faqat 3-4 ta savol bilan cheklanmaydi. U mahsulot sifati, texnik farqlari (plastik vs alyuminiy), yetkazib berish va o'rnatish muddati, oyna qalinligi, profil kameralari, to'lov usullari, ustasi borligi yoki manzili haqida har qanday savol berishi mumkin.
   - Hech qanday tayyor qoliplarga (shablonga) yopishib olma! Savolning asl mazmunini tushunib, jonli, tabiiy, do'stona va professional tilda javob ber.
   - "Zuxriddin o'zi aytadi" deb javobdan qochma! Barcha ma'lumotlarni o'zing aniq va tushunarli qilib aytib ber.
   - Javoblaringni ortiqcha cho'zma, lo'nda (2-4 gapda yoki qisqa punktlarda) yoz, mijoz zerikmasin.

3. AKFA MAHSULOTLARI VA XIZMATLAR BILIMLAR BAZASI:
   • 🚪 Eshiklar: 1 dona sifatli AKFA eshigi narxi 1 000 000 so'mdan boshlanadi (xona eshiklari, kirish eshiklari, sanuzel/vanna uchun namlikka chidamli eshiklar va zamonaviy surilma slayding tizimlar).
   • 🪟 Derazalar (romlar): 1 dona standart AKFA oynasi narxi 1 000 000 so'mdan boshlanadi (o'lchami, profili va shishasiga qarab).
   • Profil turlari:
     - AKFA Plastik (PVX): Trio (3 kamerali, qulay va tejamkor), Quattro (4 kamerali, shovqin va sovuqdan yuqori himoya), Engelberg (premium daraja).
     - AKFA Alyuminiy: Aldoks (engil va chidamli), Termo seriya (qishda sovuq o'tkazmaydigan termo-ko'prikli alyuminiy, katta o'lchamli vitraj va eshiklar uchun eng baquvvat yechim).
   • Shishalar: Energiya tejamkor Solar shishalar (yozda oftob qizdirmaydi, qishda xona issig'ini saqlaydi), 1 va 2 kamerali germetik paketlar.
   • Qo'shimcha: 🦟 Moskitka (chivin to'rlari: oddiy va plisse/garmoshka), sifatli turk va nemis furnituralari, podokonniklar.
   • Xizmatlar va Qulayliklar:
     - 📏 BEPUL O'LCHASH (ZAMER) — mutaxassisimiz uyingizga borib bepul o'lchab beradi va aniq hisoblab beradi.
     - 🛡 10 yilgacha rasmiy kafolat.
     - 🚚 Yetkazib berish va o'rnatish odatda 3-5 kunda bajariladi. Agar mijozning o'z ustasi bo'lsa, faqat romning o'zini sifatli tayyorlab berish ham mumkin.
     - 💳 To'lov: Naqd, karta (Click, Payme), kelishilgan holda.

4. MIJOZ RAQAM YOKI BUYURTMA QILGANDA:
   - Aniq narx hisoblash yoki mutaxassisimiz bepul o'lchab berishi uchun mijozning ismi va telefon raqamini so'ra.
   - Agar mijoz telefon raqamini qoldirsa, minnatdorchilik bildir va Zuxriddin hamda mutaxassis tez orada bog'lanishini ayt.
   - Matn oxirida bot egasi ({EGA_ISMI}) uchun yangi qatordan maxsus hisobot tegi yoz:
     [LEAD: Ism, Telefon, Buyurtma tafsilotlari]
     (Agar telefon raqami olinmagan bo'lsa, [LEAD: ...] yozma!)

Javobingni to'g'ridan-to'g'ri o'zbek tilida, tabiiy, lo'nda va chiroyli matn ko'rinishida yoz."""


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
    # Agar bu birinchi xabar bo'lmasa, AI qayta salomlashmasligi uchun maxsus dinamik eslatma
    qoshimcha = []
    if len(tarix) > 1:
        qoshimcha = [{
            "role": "system",
            "content": "ESLATMA: Suhbat allaqachon ketmoqda. Qayta 'Salom' yoki 'Assalomu alaykum' deb salomlashma! To'g'ridan-to'g'ri berilgan savolga mos, lo'nda va professional javob ber."
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
                max_tokens=400,
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
    """Mijoz suhbati va xulosasidan to'liq professional CRM Lid Kartochkasini shakllantiradi."""
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
        "ism": mijoz.full_name or "Noma'lum mijoz",
        "telefon": tel_topildi or "Ko'rsatilmagan",
        "username": username,
        "telegram_id": mijoz.id,
        "mahsulot": "AKFA rom va eshiklar",
        "profil": "Standart",
        "shisha": "Standart",
        "miqdor": "Aniqlanmoqda",
        "manzil": "Ko'rsatilmagan",
        "zamer": "Kerak (bepul)",
        "izoh": raw_xulosa,
        "holat": "🟡 Yangi lid",
    }

    # AI orqali har bir maydonni aniq ajratib olish (JSON)
    prompt = (
        "Quyidagi mijoz suhbati asosida AKFA savdo tizimi uchun aniq JSON formatida LID KARTOCHKASI tuz.\n"
        "Faqat quyidagi kalitlar bilan toza JSON qaytar, boshqa hech narsa yozma:\n"
        "{\n"
        '  "ism": "Mijoz ismi (suhbatda aytilgan bo\'lsa)",\n'
        '  "telefon": "Telefon raqami",\n'
        '  "mahsulot": "Deraza (rom) / Eshik / Vitraj / Moskitka / Boshqa",\n'
        '  "profil": "Trio / Quattro / Termo / Aldoks / Plastik / Alyuminiy",\n'
        '  "shisha": "Solar / 2 qavatli / Oddiy",\n'
        '  "miqdor": "O\'lcham yoki miqdor (masalan: 3 ta rom, 1 ta eshik)",\n'
        '  "manzil": "Shahar yoki tuman (agar aytilgan bo\'lsa)",\n'
        '  "zamer": "Kerak (bepul) / Kerak emas",\n'
        '  "izoh": "Mijozning asosiy talabi va xulosasi (1-2 gap)"\n'
        "}\n\n"
        f"Telegram ismi: {mijoz.full_name}\n"
        f"Oxirgi xulosa: {raw_xulosa}\n"
        f"Suhbat:\n" + "\n".join([f"{m.get('role')}: {m.get('content')}" for m in tarix[-6:]])
    )

    try:
        resp = await groq_client.chat.completions.create(
            model=MODEL,
            temperature=0.1,
            max_tokens=300,
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
                if data.get("mahsulot"):
                    karta["mahsulot"] = str(data["mahsulot"]).strip()
                if data.get("profil"):
                    karta["profil"] = str(data["profil"]).strip()
                if data.get("shisha"):
                    karta["shisha"] = str(data["shisha"]).strip()
                if data.get("miqdor"):
                    karta["miqdor"] = str(data["miqdor"]).strip()
                if data.get("manzil"):
                    karta["manzil"] = str(data["manzil"]).strip()
                if data.get("zamer"):
                    karta["zamer"] = str(data["zamer"]).strip()
                if data.get("izoh"):
                    karta["izoh"] = str(data["izoh"]).strip()
    except Exception as e:
        logging.warning("Lid kartochkasini AI orqali tuzishda xatolik: %s", e)

    return karta


async def google_sheetsga_yozish(karta: dict):
    """Yangi lead (Lid kartochkasi)ni Google Sheets onlayn jadvaliga webhook orqali avtomatik yozadi."""
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
                    logging.info("Google Sheets Lid Kartochkasiga muvaffaqiyatli saqlandi: %s (%s)", karta.get("ism"), karta.get("telefon"))
                else:
                    logging.warning("Google Sheetsga yuborishda server statusi: %s", resp.status)
    except Exception as e:
        logging.error("Google Sheetsga yozishda xatolik: %s", e)


async def leadni_saqla(chat_id: int, mijoz: types.User, karta: dict):
    """Lead kartochkasini SQLite bazaga, CSV zaxira fayliga va Google Sheetsga saqlaydi."""
    username = karta.get("username", "")
    sana = karta.get("sana", datetime.now().strftime("%Y-%m-%d %H:%M"))
    profil_shisha = f"{karta.get('profil', '')} / {karta.get('shisha', '')}".strip(" /")
    
    # 1) SQLite bazaga saqlash
    db.save_lead(
        chat_id=chat_id,
        full_name=karta.get("ism", mijoz.full_name),
        username=username,
        telegram_id=mijoz.id,
        xulosa=karta.get("izoh", ""),
        telefon=karta.get("telefon", ""),
        mahsulot=karta.get("mahsulot", ""),
        profil=profil_shisha,
        miqdor=karta.get("miqdor", ""),
        manzil=karta.get("manzil", ""),
        zamer=karta.get("zamer", ""),
        holat=karta.get("holat", "🟡 Yangi lid"),
    )

    # 2) CSV zaxira fayliga yozish
    async with csv_lock:
        yangi_fayl = not os.path.exists(LEADLAR_FAYLI)
        try:
            with open(LEADLAR_FAYLI, "a", newline="", encoding="utf-8-sig") as f:
                yozuvchi = csv.writer(f)
                if yangi_fayl:
                    yozuvchi.writerow([
                        "Sana", "Mijoz Ismi", "Telefon", "Telegram", "Telegram ID",
                        "Mahsulot", "Profil va Oyna", "Miqdori / O'lchami", "Manzil", "Zamer", "Xulosa / Izoh", "Holati"
                    ])
                yozuvchi.writerow([
                    sana,
                    karta.get("ism", mijoz.full_name),
                    karta.get("telefon", ""),
                    username,
                    mijoz.id,
                    karta.get("mahsulot", ""),
                    profil_shisha,
                    karta.get("miqdor", ""),
                    karta.get("manzil", ""),
                    karta.get("zamer", ""),
                    karta.get("izoh", ""),
                    karta.get("holat", "🟡 Yangi lid"),
                ])
        except Exception as e:
            logging.error("Leadni CSV ga saqlashda xatolik: %s", e)

    # 3) Google Sheets onlayn jadvaliga avtomatik yuborish
    asyncio.create_task(google_sheetsga_yozish(karta))


async def egaga_xabar(ega_id: int, mijoz: types.User, karta: dict):
    """Suhbat yakunlanganda bot egasiga chiroyli Lid Kartochkasi ko'rinishida hisobot yuboradi."""
    username_matn = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    mijoz_link = f"<a href='tg://user?id={mijoz.id}'>{karta.get('ism', mijoz.full_name)}</a>"
    
    tel = karta.get("telefon", "")
    tel_link = ""
    if tel and tel != "Ko'rsatilmagan":
        tel_toza = re.sub(r'[^\d+]', '', tel)
        tel_link = f"\n📞 <b>Telefon:</b> <a href='tel:{tel_toza}'>{tel}</a>"
    else:
        tel_link = f"\n📞 <b>Telefon:</b> Ko'rsatilmagan"

    profil_shisha = f"{karta.get('profil', '')} / {karta.get('shisha', '')}".strip(" /")

    matn = (
        "📇 <b>YANGI LID KARTOCHKASI (AKFA CRM)</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz_link} ({username_matn})\n"
        f"🆔 <b>Telegram ID:</b> <code>{mijoz.id}</code>{tel_link}\n"
        f"🪟 <b>Mahsulot:</b> {karta.get('mahsulot', 'AKFA')}\n"
        f"🧱 <b>Profil & Oyna:</b> {profil_shisha or 'Standart'}\n"
        f"📐 <b>Miqdori / O'lchami:</b> {karta.get('miqdor', 'Aniqlanmoqda')}\n"
        f"📍 <b>Manzil / Hudud:</b> {karta.get('manzil', 'Ko\'rsatilmagan')}\n"
        f"📏 <b>Bepul Zamer:</b> {karta.get('zamer', 'Kerak')}\n\n"
        f"📝 <b>Batafsil izoh:</b>\n{karta.get('izoh', '')}\n\n"
        f"📊 <b>Holati:</b> {karta.get('holat', '🟡 Yangi lid')} <i>(Google Sheetsga yozildi)</i>\n"
        "💡 <i>Mijoz profiliga o'tish uchun ismini bosing.</i>"
    )
    try:
        await bot.send_message(chat_id=ega_id, text=matn, parse_mode="HTML")
    except Exception as xato:
        logging.warning("Sizga xabar yuborib bo'lmadi. Bot chatiga kirib /start bosing. (%s)", xato)


async def egaga_qoshimcha_xabar(ega_id: int, mijoz: types.User, karta: dict):
    """Mijoz qo'shimcha ma'lumot yozganda bot egasiga yangilangan Lid Kartochkasi bildirishnomasi."""
    username = f"@{mijoz.username}" if mijoz.username else "username yo'q"
    mijoz_link = f"<a href='tg://user?id={mijoz.id}'>{karta.get('ism', mijoz.full_name)}</a>"
    profil_shisha = f"{karta.get('profil', '')} / {karta.get('shisha', '')}".strip(" /")
    matn = (
        "🔄 <b>YANGILANGAN LID KARTOCHKASI:</b>\n\n"
        f"👤 <b>Mijoz:</b> {mijoz_link} ({username})\n"
        f"📞 <b>Telefon:</b> {karta.get('telefon', 'Ko\'rsatilmagan')}\n"
        f"🪟 <b>Mahsulot:</b> {karta.get('mahsulot', 'AKFA')}\n"
        f"🧱 <b>Profil & Oyna:</b> {profil_shisha}\n"
        f"📐 <b>Miqdor:</b> {karta.get('miqdor', '')}\n"
        f"📍 <b>Manzil:</b> {karta.get('manzil', '')}\n\n"
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
        f"🤖 Men sizning (<b>{EGA_ISMI}</b>) AKFA mahsulotlari bo'yicha Telegram Business savdo yordamchingizman.\n"
        "Mijozlarga deraza, eshik, narxlar va sifat bo'yicha mustaqil maslahat beraman, matnli, rasm va <b>ovozli (voice)</b> xabarlarni tushunaman!\n\n"
        "Buyruqlar:\n"
        "• /leads — Oxirgi kelgan buyurtmalar (Lid kartochkalari) ro'yxati\n"
        "• /export — Barcha buyurtmalarni Excel (CSV) faylda yuklab olish\n"
        "• /stats — Umumiy statistika (Baza bo'yicha)\n"
        "• /resume &lt;chat_id&gt; — Chatda botni qayta faollashtirish\n"
        "• /reset &lt;chat_id&gt; — Chat xotirasini tozalash\n"
        "• /help — Yordam va qo'llanma",
        parse_mode="HTML"
    )


@dp.message(Command("leads"))
async def leads_komandasi(message: types.Message):
    """Oxirgi kelgan mijozlarni SQLite bazasidan Lid Kartochkasi ko'rinishida ko'rsatish."""
    oxirgi_leadlar = db.get_recent_leads(limit=5)
    if not oxirgi_leadlar:
        await message.answer("Hozircha yangi murojaatlar (leadlar) mavjud emas.")
        return

    javob = "📇 <b>Oxirgi 5 ta Lid Kartochkasi:</b>\n\n"
    for idx, row in enumerate(oxirgi_leadlar, 1):
        keys = row.keys() if hasattr(row, 'keys') else []
        username_matn = f"@{row['username']}" if row['username'] and not str(row['username']).startswith('@') else (row['username'] or 'yo\'q')
        mijoz_link = f"<a href='tg://user?id={row['telegram_id']}'>{row['full_name']}</a>"
        tel = row['telefon'] if 'telefon' in keys and row['telefon'] else 'Aniqlanmagan'
        mahsulot = row['mahsulot'] if 'mahsulot' in keys and row['mahsulot'] else 'AKFA'
        miqdor = row['miqdor'] if 'miqdor' in keys and row['miqdor'] else ''
        miqdor_matn = f" | {miqdor}" if miqdor else ""
        
        javob += (
            f"<b>{idx}. {mijoz_link}</b> ({username_matn}) — <i>{row['created_at']}</i>\n"
            f"📞 <code>{tel}</code> | 🪟 {mahsulot}{miqdor_matn}\n"
            f"📝 {row['xulosa']}\n\n"
        )

    await message.answer(javob, parse_mode="HTML")


@dp.message(Command("export"))
@dp.message(Command("excel"))
async def export_komandasi(message: types.Message):
    """Leadlar ro'yxatini to'liq Lid Kartochkasi ustunlari bilan Excel/CSV fayl ko'rinishida yuboradi."""
    all_leads = db.get_all_leads()
    if not all_leads:
        await message.answer("Hozircha saqlangan buyurtmalar (leadlar) mavjud emas.")
        return

    # CSV faylni to'liq va yangilangan holda shakllantiramiz
    async with csv_lock:
        try:
            with open(LEADLAR_FAYLI, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID", "Sana", "Mijoz Ismi", "Telefon", "Telegram", "Telegram ID",
                    "Mahsulot", "Profil va Oyna", "Miqdori / O'lchami", "Manzil", "Zamer", "Xulosa / Izoh", "Holati"
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
                        r["mahsulot"] if "mahsulot" in keys else "",
                        r["profil"] if "profil" in keys else "",
                        r["miqdor"] if "miqdor" in keys else "",
                        r["manzil"] if "manzil" in keys else "",
                        r["zamer"] if "zamer" in keys else "",
                        r["xulosa"] if "xulosa" in keys else "",
                        r["holat"] if "holat" in keys else "Yangi lid",
                    ])
        except Exception as e:
            logging.error("CSV yozishda xato: %s", e)

    try:
        fayl = types.FSInputFile(LEADLAR_FAYLI, filename=f"AKFA_Lid_Kartochkalari_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        await message.answer_document(
            document=fayl,
            caption="📊 <b>Barcha AKFA Lid Kartochkalari ro'yxati</b>\nUshbu faylni Excel dasturida to'liq jadval ko'rinishida ko'rishingiz mumkin.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"Faylni yuborishda xatolik yuz berdi: {e}")


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
        "💡 <b>AKFA Savdo Boti Qo'llanmasi:</b>\n\n"
        "1. Bot Telegram Business orqali shaxsiy akkauntingizga ulangan bo'lishi kerak.\n"
        "2. Yangi mijoz yozganda AI AKFA derazalari, eshiklari, narxlari va sifati bo'yicha mustaqil maslahat beradi.\n"
        "3. Mijoz matn, <b>ovoz (voice)</b>, <b>video-xabar (kruglyash)</b>, <b>rasm (izohi bilan)</b>, <b>kontakt</b> yoki <b>lokatsiya</b> yuborsa ham bot to'liq tushunadi.\n"
        "4. Mijozning telefon raqami va buyurtma tafsilotlari aniqlangach, sizga bildirishnoma keladi va Excelga yoziladi.\n"
        "5. Agar siz mijozga o'zingiz yozsangiz, bot 30 daqiqa davomida suhbatga xalaqit bermaydi. Qayta faollashtirish uchun: <code>/resume &lt;chat_id&gt;</code>.",
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
        # Mijoz Telegram orqali telefon raqamini (kontakt) ulashdi
        tel = message.contact.phone_number
        ism = f"{message.contact.first_name or ''} {message.contact.last_name or ''}".strip()
        xabar_matni = f"Mening ismim: {ism}, telefon raqamim: {tel}. Bepul o'lchash (zamer) uchun ma'lumot qoldirdim."
    elif message.photo:
        # Mijoz rasm yubordi (masalan rom yoki eshik rasmi)
        caption = message.caption.strip() if message.caption else ""
        if caption:
            xabar_matni = f"[Mijoz rom/eshik rasmini yubordi va izoh yozdi]: {caption}"
        else:
            xabar_matni = "Mijoz xona yoki oyna rasmini yubordi. Rasm uchun rahmat aytib, o'lchamlari va qanday mahsulot kerakligini so'ra."
    elif message.location:
        # Mijoz zamer uchun lokatsiya yubordi
        lat, lon = message.location.latitude, message.location.longitude
        xabar_matni = f"Mijoz zamer uchun manzil lokatsiyasini yubordi (Kenglik: {lat}, Uzunlik: {lon}). Zamer manzili qabul qilinganini ayt."
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

        # Agar mijoz xabarida telefon raqami bo'lsa, zaxira sifatida lead deb belgilaymiz
        if not tayyor and PHONE_REGEX.search(xabar_matni):
            tayyor = True
            if not xulosa:
                xulosa = f"Mijoz telefon raqami qoldirdi: {xabar_matni}"

        db.add_message(chat_id, "assistant", javob)
        await yubor(message, javob)

        # Agar ma'lumotlar yig'ilgan yoki yangilangan bo'lsa (Lid kartochkasi shakllantiriladi)
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