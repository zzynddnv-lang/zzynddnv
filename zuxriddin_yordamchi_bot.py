"""
UMATIC SAVDO MENEJERI - Telegram AI sotuv boti
Telegram Business va shaxsiy chat (Groq Qwen / GPT-OSS & Whisper Turbo)

Vazifasi:
  - Mijozlarga kompaniya mahsulotlarini tanishtirish, ehtiyojini aniqlash, sotuvga olib borish
  - Narx va qoldiqni ombor mas'ulidan Telegram orqali so'rash (AI narx O'YLAB TOPMAYDI)
  - Tijorat taklifini dastur orqali hisoblab (to'lov shartlari bilan) mijozga yuborish
  - Barcha ma'lumotlarni CRM ga (SQLite + CSV + Google Sheets) yig'ish

Bilimlar (kompaniya, mahsulotlar, sotuv qoidalari): bilimlar/*.md fayllari.

Ishga tushirish:
    pip install -r requirements.txt
    python zuxriddin_yordamchi_bot.py   (yoki run.bat)
"""

import asyncio
import csv
import glob
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
import sotuv
import taklif_pdf
from sotuv import matn as tmatn


# =====================================================================
#  SOZLAMALAR (.env faylidan o'qiladi)
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
KOMPANIYA_NOMI = sotuv.KOMPANIYA_NOMI


def _idlarni_oqish(qiymat: str) -> set[int]:
    """'123, 456' ko'rinishidagi matndan Telegram ID lar to'plamini ajratadi."""
    return {int(q) for q in re.split(r"[,\s]+", qiymat or "") if q.lstrip("-").isdigit()}


# Bot egasi(lari) / menejerlar. Faqat shu ID lar admin buyruqlaridan foydalanadi va bildirishnomalar oladi.
OWNER_IDS = _idlarni_oqish(os.getenv("OWNER_ID", ""))

# Ombor mas'uli yoki ombor guruhi chat ID si (narx so'rovlari shu yerga boradi).
# Bo'sh bo'lsa - so'rovlar bot egalariga yuboriladi.
_sklad = os.getenv("SKLAD_CHAT_ID", "").strip()
SKLAD_CHAT_ID = int(_sklad) if _sklad.lstrip("-").isdigit() else None

# Narx rejimi:
#   0 (standart) - narxsiz: pozitsiya va miqdor aniq bo'lgach mijozga narxsiz PDF tijorat taklifi yuboriladi,
#                  narxni menejer alohida bildiradi.
#   1            - ombor orqali: omborga narx so'rovi ketadi, ombor narx kiritgach taklif (narx bilan) yuboriladi.
NARX_OMBORDAN = os.getenv("NARX_OMBORDAN", "0").strip().lower() in ("1", "true", "ha", "yes")

# gpt-oss-120b - Groq production modeli (preview modellar istalgan vaqtda o'chirilishi mumkin),
# sinovlarda tilni (lotin/kirill/rus) eng to'g'ri ushlagan model.
MODEL = os.getenv("MODEL", "openai/gpt-oss-120b")
ZAXIRA_MODELLAR = [
    m.strip() for m in os.getenv("FALLBACK_MODELS", "qwen/qwen3.8-27b").split(",") if m.strip()
]
WHISPER_MODEL = "whisper-large-v3-turbo"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADLAR_FAYLI = os.getenv("CSV_PATH") or os.path.join(BASE_DIR, "leadlar.csv")
BILIMLAR_PAPKASI = os.getenv("BILIMLAR_PAPKASI") or os.path.join(BASE_DIR, "bilimlar")

MAX_TARIX = 10                                                   # AI ga beriladigan oxirgi xabarlar soni
SESSIYA_SOAT = int(os.getenv("SESSIYA_SOAT", "72"))              # shundan keyin suhbat xotirasi yangilanadi
SKLAD_ESLATMA_DAQIQA = int(os.getenv("SKLAD_ESLATMA_DAQIQA", "30"))  # ombor javob bermasa eslatish
KUZATISH_SOAT = int(os.getenv("KUZATISH_SOAT", "6"))             # taklifga javob bo'lmasa menejerga eslatish
EGA_PAUZA_DAQIQA = 30                                            # menejer o'zi yozsa, bot shuncha jim turadi
KEEPALIVE_ORALIQ = 10 * 60
FON_TEKSHIRUV_ORALIQ = 5 * 60
LIMIT_KUTISH = 15                                                # hamma modellar limitda bo'lsa, kutish (soniya)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

bot = None
dp = Dispatcher()
groq_client = None   # Whisper (ovoz) uchun
groq_chat = None     # AI javoblari uchun: avtomatik qayta urinishsiz (limitda darhol zaxira modelga o'tiladi)

egalar: dict[str, int] = {}
chat_locks = defaultdict(asyncio.Lock)
csv_lock = asyncio.Lock()


# =====================================================================
#  BILIMLAR BAZASI VA AI KO'RSATMASI
# =====================================================================

BILIMLAR = ""


def bilimlarni_yuklash() -> str:
    """bilimlar/*.md fayllarini o'qiydi. <!-- izohlar --> botga ko'rinmaydi."""
    qismlar = []
    for yol in sorted(glob.glob(os.path.join(BILIMLAR_PAPKASI, "*.md"))):
        with open(yol, encoding="utf-8") as f:
            matn = f.read()
        matn = re.sub(r"<!--.*?-->", "", matn, flags=re.DOTALL)
        matn = re.sub(r"\n{3,}", "\n\n", matn).strip()
        if matn:
            qismlar.append(matn)
    natija = "\n\n".join(qismlar)
    if not natija:
        logging.warning("Bilimlar bazasi bo'sh! %s papkasini tekshiring.", BILIMLAR_PAPKASI)
    elif len(natija) > 12000:
        logging.warning(
            "Bilimlar hajmi katta (%s belgi). Groq bepul tarifi daqiqasiga 8000 token - qisqartirish tavsiya etiladi.",
            len(natija),
        )
    return natija


# Suhbat tarixida taqdimot o'rniga saqlanadigan qisqa belgi (AI uchun yetarli, tokenni tejaydi)
TAQDIMOT_BELGISI = (
    "[Mijozga kompaniya taqdimoti yuborildi: UMATIC, rasmiy vakil; 4 tur dvigatel - umumsanoat AIR, "
    "kran MTN/MTKN, portlashdan himoyalangan VA/VAO, sinxron SD/VDS; kVt va ob/min so'raldi]"
)


def tanishtiruv_matni(til: str) -> str:
    """
    Mijozning birinchi xabariga yuboriladigan tayyor taqdimot (kompaniya + mahsulotlar + chaqiriq).
    AI ga bog'liq emas - har doim to'liq va to'g'ri chiqadi. Tahrirlash: bilimlar/tanishtiruv/<til>.txt
    """
    for t in (til, "uz_latn"):
        yol = os.path.join(BILIMLAR_PAPKASI, "tanishtiruv", f"{t}.txt")
        if os.path.exists(yol):
            with open(yol, encoding="utf-8") as f:
                matn = f.read().strip()
            if matn:
                return matn
    return tmatn("start", til).format(kompaniya=KOMPANIYA_NOMI)


def tizim_korsatmasi() -> str:
    # Ixcham yozilgan: Groq bepul tarifida bitta so'rov 7000 tokendan oshmasligi kerak
    return f"""Sen "{KOMPANIYA_NOMI}" kompaniyasining Telegramdagi AI savdo menejerisan. Kompaniya ELEKTR DVIGATELLAR sotadi.
Vazifang: dvigatellarni tanishtirish, ehtiyojni aniqlash, mijozni qiziqtirib sotuvga olib borish, CRM uchun ma'lumot yig'ish.

QOIDALAR:
1. Mijoz yozgan til va yozuvda javob ber (o'zbek lotin / o'zbek kirill / rus).
2. Faqat BILIMLARdagi faktlar. Narx, qoldiq, muddat, chegirma, kafolat, yo'q model yoki xususiyatni O'YLAB TOPMA. Modelni "katalogimizda bor" deb tanishtir, lekin "omborda bor", "mavjud", "yo'q", "mavjud emas" DEMA - mavjudlikni menejer aytadi. O'zingcha hisoblab model tavsiya qilma.
3. {_narx_qoidasi()}
4. FAOL SOTUVCHI BO'L, quruq so'roq qilma:
 - aniq ehtiyoj aytilmasa - mos dvigatel turlarini qisqa tanishtir va qaysi biri kerakligini so'ra;
 - kVt/ob/min aytilsa - KATALOGdan mos modelni nomi va xususiyatlari bilan darhol taklif qil ("katalogimizda ... bor");
 - mexanizm aytilsa (nasos, kran, konveyer, kompressor, shaxta) - mos turni va foydasini ayt;
 - har javobda bitta foyda (original, muhandislik tanlovi, KPD/energiya tejash, to'xtab qolmaslik) va keyingi qadamga savol.
5. Javob 2-4 gap. Salomlashma, "Rahmat/Tushundim/Ajoyib" bilan boshlama (minnatdorchilik butun suhbatda ko'pi bilan 1 marta). Suhbat boshida kompaniya taqdimoti yuborilgan - uni takrorlama.
6. Bir savolni ko'pi bilan 1 marta qayta so'ra. Mijoz bilmasa - oldinga o't. kVt, ob/min va miqdor ma'lum bo'lsa narx_sorash=true.
7. Sen AI yordamchisan, odam ekanligingni da'vo qilma. Rasm/faylni ko'ra olmaysan - u menejerga yuborilgan.
8. Boshqa mahsulot (nasos va h.k.) so'ralsa - hozircha faqat dvigatellar bilan ishlashimizni ayt, menejer_kerak=true.
9. menejer_kerak=true FAQAT: chegirma, bilimlarda javobi yo'q texnik savol, shikoyat, qo'ng'iroq/uchrashuv so'rovi.
10. buyurtma_tasdiqlandi=true faqat mijoz yuborilgan taklifni aniq qabul qilsa.

JSON: mahsulotlar - suhbatdagi barcha pozitsiyalarning so'nggi holati (miqdor noma'lum = 0); mijoz - faqat mijoz o'zi aytgani; xulosa - menejer uchun 1-2 gap.
Kalitlar: javob, til, mijoz{{ism, telefon, kompaniya, lavozim, soha}}, ehtiyoj, mahsulotlar[{{nomi, parametrlar, miqdor, birlik}}], narx_sorash, buyurtma_tasdiqlandi, bosqich, harorat, menejer_kerak, menejer_sababi, xulosa.

BILIMLAR:
{BILIMLAR}"""


def _narx_qoidasi() -> str:
    if NARX_OMBORDAN:
        return (
            "NARX AYTMA - narxni ombor tasdiqlaydi; pozitsiya va miqdor aniq bo'lsa narx_sorash=true qil. "
            f"Yuborilgan taklifdagi raqamlarnigina aytish mumkin. {sotuv.tolov_sharti_matni()}"
        )
    return (
        "NARX AYTMA (hech qanday raqam yoki oraliq). Narxni menejer bildiradi. narx_sorash=true bo'lsa tizim "
        "mijozga PDF tijorat taklifini (pozitsiyalar va miqdor; narx va yetkazish YO'Q) yuboradi - buni va "
        "narx bo'yicha menejer bog'lanishini qisqa ayt."
    )


def _pozitsiyalar_qisqa(pozitsiyalar: list[dict]) -> str:
    return "; ".join(
        f"{p['nomi']}{' (' + p['parametrlar'] + ')' if p['parametrlar'] else ''}"
        + (f" - {p['miqdor']} {p['birlik']}" if p["miqdor"] else " - miqdor aniqlanmagan")
        for p in pozitsiyalar
    )


def suhbat_holati(chat_id: int) -> dict:
    """AI ga beriladigan joriy holat: faol narx so'rovi va yuborilgan taklif."""
    faol = db.get_faol_sorov(chat_id)
    taklif = db.get_oxirgi_taklif(chat_id)
    return {"faol": faol, "taklif": taklif}


def holat_matni(holat: dict, birinchi: bool, til: str = "uz_latn") -> str:
    qatorlar = ["JORIY HOLAT:"]
    qatorlar.append(
        f"- MIJOZ TILI: {TIL_NOMLARI.get(til, til)}. \"javob\" matnini FAQAT shu tilda va yozuvda yoz, \"til\" = \"{til}\"."
    )
    qatorlar.append("- Bu suhbatdagi BIRINCHI javob." if birinchi else "- Suhbat davom etmoqda, salomlashma.")
    faol = holat.get("faol")
    if faol:
        qatorlar.append(
            f"- Omborga narx so'rovi #{faol['id']} yuborilgan, javob kutilmoqda: "
            f"{_pozitsiyalar_qisqa(json.loads(faol['pozitsiyalar']))}. Pozitsiyalar o'zgarmasa, qayta so'rov shart emas."
        )
    taklif = holat.get("taklif")
    if taklif and not taklif["narxlar"]:
        qatorlar.append(
            f"- Mijozga narxsiz tijorat taklifi {taklif_pdf.taklif_raqami(taklif['id'])} (PDF) yuborilgan: "
            f"{_pozitsiyalar_qisqa(json.loads(taklif['pozitsiyalar']))}. Narxni menejer bildiradi - narx aytma."
        )
    elif taklif:
        pozlar = json.loads(taklif["pozitsiyalar"])
        narxlar = json.loads(taklif["narxlar"] or "[]")
        hisob, jami = sotuv.hisoblash(pozlar, narxlar)
        tafsilot = "; ".join(
            f"{q['nomi']}: {q['sotiladi']} {q['birlik']} x {sotuv.son_format(q['narx'])} so'm" if q["sotiladi"]
            else f"{q['nomi']}: omborda yo'q"
            for q in hisob
        )
        qatorlar.append(
            f"- Mijozga tijorat taklifi #{taklif['id']} yuborilgan: {tafsilot}. Jami {sotuv.son_format(jami)} so'm. "
            "Narx haqida faqat shu raqamlarni ayt."
        )
    if not faol and not taklif:
        qatorlar.append("- Hali tijorat taklifi yuborilmagan. Narx aytma.")
    return "\n".join(qatorlar)


# =====================================================================
#  ISHGA TUSHIRISH
# =====================================================================

def init_runtime():
    """Bot va Groq API klientini yaratadi, bazani va bilimlarni tayyorlaydi."""
    global bot, groq_client, groq_chat, BILIMLAR

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! .env fayliga yoki Render 'Environment' bo'limiga BOT_TOKEN ni kiriting.")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY topilmadi! .env fayliga yoki Render 'Environment' bo'limiga GROQ_API_KEY ni kiriting.")

    if bot is None:
        bot = Bot(token=BOT_TOKEN)
    if groq_client is None:
        groq_client = AsyncGroq(api_key=GROQ_API_KEY)
    if groq_chat is None:
        groq_chat = AsyncGroq(api_key=GROQ_API_KEY, max_retries=0, timeout=60)

    db.init_db()
    BILIMLAR = bilimlarni_yuklash()
    logging.info("Bilimlar yuklandi: %s belgi", len(BILIMLAR))

    if OWNER_IDS:
        logging.info("Bot egalari (OWNER_ID): %s", ", ".join(map(str, sorted(OWNER_IDS))))
    else:
        logging.warning("OWNER_ID o'rnatilmagan! Xavfsizlik uchun .env ga Telegram ID raqamingizni OWNER_ID sifatida yozing.")
    if SKLAD_CHAT_ID is None:
        logging.warning("SKLAD_CHAT_ID o'rnatilmagan - narx so'rovlari bot egalariga yuboriladi.")

    return bot, dp, groq_client


# =====================================================================
#  EGA (ADMIN) VA OMBOR HUQUQLARI
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
    """Bildirishnomalar yuboriladigan egalar ro'yxati."""
    idlar = set(OWNER_IDS)
    if ega_id:
        idlar.add(ega_id)
    if not OWNER_IDS:
        idlar.update(db.get_owner_ids())
    return idlar


def ombor_chatlari() -> list[int]:
    """Narx so'rovlari yuboriladigan chat(lar)."""
    if SKLAD_CHAT_ID is not None:
        return [SKLAD_CHAT_ID]
    return sorted(hisobot_oluvchilar(None))


def omborga_ruxsat(user_id: int | None, chat_id: int) -> bool:
    """Narx kiritish tugmalari va javoblariga kim ruxsatli: ombor chati a'zolari yoki egalar."""
    return (SKLAD_CHAT_ID is not None and chat_id == SKLAD_CHAT_ID) or egami(user_id)


class EgaFilter(Filter):
    """Admin buyruqlarini faqat bot egasiga ruxsat beruvchi filtr."""

    async def __call__(self, message: types.Message) -> bool:
        return egami(message.from_user.id if message.from_user else None)


# =====================================================================
#  YORDAMCHI FUNKSIYALAR
# =====================================================================

PHONE_REGEX = re.compile(r'(\+?998[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}|(?:\b[389]\d[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b))')

TIL_NOMLARI = {"uz_latn": "O'zbek (lotin)", "uz_cyrl": "O'zbek (kirill)", "ru": "Rus"}
BOSQICH_NOMLARI = {
    "yangi": "🆕 Yangi", "qiziqish": "👀 Qiziqish", "ehtiyoj_aniqlanmoqda": "🔍 Ehtiyoj aniqlanmoqda",
    "narx_sorovi": "💰 Narx so'rovi", "taklif_berildi": "📄 Taklif berildi", "muzokara": "🤝 Muzokara",
    "kelishildi": "✅ Kelishildi", "rad_etdi": "❌ Rad etdi",
}
HARORAT_NOMLARI = {"sovuq": "🧊 Sovuq", "iliq": "🌤 Iliq", "issiq": "🔥 Issiq"}


def h(qiymat) -> str:
    """Telegram HTML xabarlari uchun matnni xavfsiz qiladi (<, >, & belgilar)."""
    return html.escape(str(qiymat if qiymat is not None else ""), quote=True)


def qisqartir(matn: str, n: int = 400) -> str:
    matn = str(matn or "")
    return matn if len(matn) <= n else matn[: n - 1] + "…"


def mijoz_havolasi(user_id: int, ism: str, username: str = "") -> str:
    un = f" ({h(username)})" if username else ""
    return f"<a href='tg://user?id={user_id}'>{h(ism or 'Mijoz')}</a>{un}"


async def ega_id_ol(connection_id: str) -> int:
    """Telegram Business ulanishidan egasining chat_id sini aniqlaydi."""
    if connection_id not in egalar:
        conn = await bot.get_business_connection(connection_id)
        egalar[connection_id] = conn.user.id
    return egalar[connection_id]


async def mijozga_yuborish(chat_id: int, business_connection_id: str | None, matn: str) -> str | None:
    """Mijozga xabar yuboradi. Muvaffaqiyatli bo'lsa None, aks holda xato matni."""
    try:
        await bot.send_message(chat_id=chat_id, text=matn, business_connection_id=business_connection_id or None)
        return None
    except TelegramAPIError as e:
        logging.error("Mijozga xabar yuborishda xato (chat_id: %s): %s", chat_id, e)
        return str(e)


async def javob_yubor(message: types.Message, matn: str, is_business: bool = True):
    """Mijozga kelgan xabar kanali orqali javob yuboradi."""
    bcid = message.business_connection_id if is_business else None
    await mijozga_yuborish(message.chat.id, bcid, matn)


async def egalarga_yuborish(matn: str, ega_id: int | None = None, reply_markup=None):
    """HTML xabarni barcha bot egalariga yuboradi."""
    maqsadli_idlar = await asyncio.to_thread(hisobot_oluvchilar, ega_id)
    if not maqsadli_idlar:
        logging.warning("Ega Telegram ID si topilmadi. .env ga OWNER_ID yozing yoki botga /start yuboring.")
        return
    for target_id in maqsadli_idlar:
        try:
            await bot.send_message(chat_id=target_id, text=matn, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as xato:
            logging.warning("Ega (%s) ga xabar yuborib bo'lmadi: %s", target_id, xato)


async def ovozni_matnga_aylantirish(file_id: str, fayl_nomi: str = "voice.ogg") -> str:
    """Telegram ovozli xabarini yuklab olib, Groq Whisper orqali matnga o'giradi."""
    try:
        file_info = await bot.get_file(file_id)
        file_bytes_io = await bot.download_file(file_info.file_path)
        transcription = await groq_client.audio.transcriptions.create(
            file=(fayl_nomi, file_bytes_io.read()),
            model=WHISPER_MODEL,
        )
        matn = transcription.text.strip()
        logging.info("Ovoz matnga aylantirildi: '%s'", matn)
        return matn
    except Exception as e:
        logging.error("Whisper orqali ovozni tanishda xatolik: %s", e)
        return ""


# =====================================================================
#  AI JAVOBI (Groq Structured Outputs)
# =====================================================================

def _model_parametrlari(model: str) -> dict:
    """
    Reasoning modellar uchun parametrlar: fikrlash matni javobga aralashmasligi va token tejash.
    max_completion_tokens: JSON javob ~300-500 token. Qwen bepul tarifida daqiqasiga 1000 chiqish tokeni
    (OTPM) limiti bor - kattaroq so'ralsa Groq so'rovni umuman qabul qilmaydi.
    """
    if model.startswith("qwen/"):
        return {"reasoning_effort": "none", "reasoning_format": "hidden", "max_completion_tokens": 700}
    if "gpt-oss" in model:
        # gpt-oss "low" rejimda ham qisqa fikrlaydi - fikrlash tokenlari ham shu limitga kiradi
        return {"reasoning_effort": "low", "include_reasoning": False, "max_completion_tokens": 1200}
    return {"max_completion_tokens": 800}


async def _groq_sorov(model: str, messages: list) -> dict | None:
    """
    Groq Structured Outputs (qat'iy JSON sxema). Model sxemaga mos JSON bera olmasa (Groq 400
    json_validate_failed), oddiy JSON rejimida qayta so'raladi - natija baribir dasturda tekshiriladi.
    """
    umumiy = dict(model=model, temperature=0.4, messages=messages, **_model_parametrlari(model))
    try:
        resp = await groq_chat.chat.completions.create(
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "sotuv_javobi", "strict": True, "schema": sotuv.JAVOB_SXEMASI},
            },
            **umumiy,
        )
    except Exception as e:
        if "json_validate_failed" not in str(e):
            raise
        logging.info("Model '%s' qat'iy sxemani bajarmadi, oddiy JSON rejimida qayta so'ralmoqda.", model)
        resp = await groq_chat.chat.completions.create(response_format={"type": "json_object"}, **umumiy)
    return sotuv.ai_natijasini_ajratish(resp.choices[0].message.content or "")


def _javob_muammolari(natija: dict, til: str, taklif_bor: bool, oldingilar: list[str] = ()) -> list[str]:
    """AI javobini mijozga yuborishdan oldin tekshiradi."""
    muammolar = []
    if not taklif_bor and sotuv.narx_aytilganmi(natija["javob"]):
        muammolar.append("Javobingda narx yoki summa bor. Narx AYTMA - uni faqat ombor beradi.")
    if not sotuv.yozuv_mosmi(natija["javob"], til):
        muammolar.append(f"Javob noto'g'ri tilda. \"javob\" ni FAQAT {TIL_NOMLARI.get(til, til)} tilida yoz.")
    if sotuv.takrorlanganmi(natija["javob"], oldingilar):
        muammolar.append(
            "Javobing oldingi javobingni deyarli so'zma-so'z takrorlayapti. Mijozning oxirgi xabariga "
            "javob ber va suhbatni keyingi qadamga olib bor; javobsiz qolgan savolni qayta talab qilma."
        )
    return muammolar


def _narx_bor(natija: dict | None, taklif_bor: bool) -> bool:
    return natija is not None and not taklif_bor and sotuv.narx_aytilganmi(natija["javob"])


async def ai_javob(tarix: list, holat: dict, til: str = "uz_latn") -> dict:
    """
    AI dan tuzilgan (JSON) javob oladi va tekshiradi (narx o'ylab topilmagan, til to'g'ri).
    Muammo bo'lsa bir marta qayta so'raydi. Model ishlamasa - zaxira modellarga o'tadi.
    """
    birinchi = not any(m.get("role") == "assistant" for m in tarix)
    messages = (
        [{"role": "system", "content": tizim_korsatmasi()}]
        + tarix
        + [{"role": "system", "content": holat_matni(holat, birinchi, til)}]
    )
    modellar = list(dict.fromkeys([MODEL] + ZAXIRA_MODELLAR))
    # Narxli taklif yuborilgan bo'lsagina AI undagi raqamlarni aytishi mumkin
    taklif_bor = holat.get("taklif") is not None and bool(holat["taklif"]["narxlar"])
    oxirgi_xato = None

    oldingilar = [m["content"] for m in tarix if m.get("role") == "assistant"][-2:]

    for urinish in range(2):
        natija, oxirgi_xato, hammasi_limit = await _modellarni_sinash(modellar, messages, til, taklif_bor, oldingilar)
        if natija is not None:
            natija["_birinchi"] = birinchi
            return natija
        if not hammasi_limit or urinish == 1:
            break
        logging.warning("Barcha modellar limitda, %s soniya kutilmoqda...", LIMIT_KUTISH)
        await asyncio.sleep(LIMIT_KUTISH)

    raise oxirgi_xato or RuntimeError("Barcha modellar yaroqsiz javob qaytardi")


def _limit_xatosimi(e: Exception) -> bool:
    return e.__class__.__name__ == "RateLimitError" or "429" in str(e) or "rate_limit" in str(e)


async def _modellarni_sinash(modellar: list, messages: list, til: str, taklif_bor: bool, oldingilar: list[str] = ()):
    """
    Modellarni navbat bilan sinaydi. Qaytaradi: (natija | None, oxirgi_xato, hammasi_limitdami).
    - Narx o'ylab topilsa va tuzatilmasa: xavfsiz tayyor matn bilan almashtiriladi.
    - Til noto'g'ri yoki javob takroriy bo'lib qolsa: keyingi model sinaladi. Hech bir model to'g'ri
      javob bermasa - faqat TO'G'RI TILDAGI nomzod (takroriy bo'lsa ham) yuboriladi. Noto'g'ri tildagi
      javob hech qachon yuborilmaydi: bu holat limit kabi hisoblanib, kutib qayta urinish qilinadi.
    """
    oxirgi_xato = None
    limitlar = 0
    nomzod = None  # to'g'ri tildagi, narxsiz, lekin takroriy javob - oxirgi chora
    til_xatolari = 0
    for m in modellar:
        try:
            natija = await _groq_sorov(m, messages)
            if natija is None:
                logging.warning("Model '%s' yaroqsiz javob qaytardi, zaxira model tekshirilmoqda...", m)
                continue

            muammolar = _javob_muammolari(natija, til, taklif_bor, oldingilar)
            if muammolar:
                logging.warning("Model '%s' javobida muammo: %s Qayta so'ralmoqda.", m, " ".join(muammolar))
                if nomzod is None and _nomzod_bolaoladimi(natija, til, taklif_bor):
                    nomzod = natija
                try:
                    qayta = await _groq_sorov(m, messages + [
                        {"role": "assistant", "content": json.dumps(natija, ensure_ascii=False)},
                        {"role": "system", "content": "Javobni tuzat: " + " ".join(muammolar)},
                    ])
                except Exception as e:
                    logging.warning("Model '%s' qayta so'rovida xato: %s", m, e)
                    qayta = None

                if qayta is not None and not _javob_muammolari(qayta, til, taklif_bor, oldingilar):
                    natija = qayta
                elif _narx_bor(natija, taklif_bor) and (qayta is None or _narx_bor(qayta, taklif_bor)):
                    # Narx o'ylab topilishi eng xavfli xato - xavfsiz tayyor matn yuboriladi
                    natija["javob"] = tmatn("kutish" if natija["narx_sorash"] else "narx_aniqlanadi", til)
                else:
                    if qayta is not None and _nomzod_bolaoladimi(qayta, til, taklif_bor):
                        nomzod = qayta
                    if not sotuv.yozuv_mosmi((qayta or natija)["javob"], til):
                        til_xatolari += 1
                    continue  # til/takror muammosi qoldi - keyingi model sinaladi

            if m != MODEL:
                logging.info("Javob zaxira model '%s' orqali olindi.", m)
            natija["til"] = til
            return natija, None, False
        except Exception as e:
            oxirgi_xato = e
            if _limit_xatosimi(e):
                limitlar += 1
                logging.warning("Model '%s' limitda (429), zaxira modelga o'tilmoqda.", m)
            else:
                logging.warning("Model '%s' da xato: %s. Zaxira model tekshirilmoqda...", m, e)

    if nomzod is not None:
        logging.warning("Hech bir model to'liq to'g'ri javob bermadi - to'g'ri tildagi nomzod yuborilmoqda.")
        nomzod["til"] = til
        return nomzod, None, False
    if til_xatolari:
        oxirgi_xato = oxirgi_xato or RuntimeError("Modellar mijoz tilida javob bera olmadi")
    # Noto'g'ri til ham vaqtinchalik muammo (odatda asosiy model limitda bo'lganda) - kutib qayta urinamiz
    return None, oxirgi_xato, limitlar + til_xatolari == len(modellar)


def _nomzod_bolaoladimi(natija: dict, til: str, taklif_bor: bool) -> bool:
    """Oxirgi chora sifatida yuborish mumkinmi: narx yo'q va til to'g'ri (faqat takroriy bo'lishi mumkin)."""
    return not _narx_bor(natija, taklif_bor) and sotuv.yozuv_mosmi(natija["javob"], til)


# =====================================================================
#  CRM: SQLite + CSV + GOOGLE SHEETS
# =====================================================================

async def google_sheetsga_yozish(karta: dict) -> bool | None:
    """
    Mijoz kartochkasini Google Sheets jadvaliga webhook (Apps Script) orqali yozadi.
    Qaytaradi: None - webhook sozlanmagan, True - muvaffaqiyatli, False - xatolik.
    """
    webhook_url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url, json=karta, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status < 400:
                    logging.info("Google Sheets jadvaliga saqlandi: %s", karta.get("ism"))
                    return True
                logging.warning("Google Sheetsga yuborishda server statusi: %s", resp.status)
                return False
    except Exception as e:
        logging.error("Google Sheetsga yozishda xatolik: %s", e)
        return False


_CSV_USTUNLARI = [
    ("id", "ID"), ("created_at", "Sana"), ("updated_at", "Yangilangan"), ("full_name", "Mijoz"),
    ("telefon", "Telefon"), ("username", "Telegram"), ("telegram_id", "Telegram ID"),
    ("tashkilot", "Kompaniya"), ("lavozim", "Lavozim"), ("mavzu", "Ehtiyoj"), ("mahsulot", "Mahsulot"),
    ("bosqich", "Bosqich"), ("harorat", "Harorat"), ("summa", "Taklif summasi"), ("xulosa", "Xulosa"),
]


def _csv_faylni_yozish(leadlar) -> None:
    with open(LEADLAR_FAYLI, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([nom for _, nom in _CSV_USTUNLARI])
        for r in leadlar:
            writer.writerow([r[k] if r[k] is not None else "" for k, _ in _CSV_USTUNLARI])


async def csv_yangilash() -> bool:
    """CSV zaxira faylini bazadan to'liq qayta shakllantiradi (dublikatlarsiz)."""
    async with csv_lock:
        try:
            leadlar = await asyncio.to_thread(db.get_all_leads)
            await asyncio.to_thread(_csv_faylni_yozish, leadlar)
            return True
        except Exception as e:
            logging.error("CSV ga yozishda xatolik: %s", e)
            return False


def _sheets_matni(holat: bool | None) -> str:
    if holat is True:
        return "✅ Google Sheetsga yozildi"
    if holat is False:
        return "⚠️ Google Sheetsga yozib bo'lmadi"
    return "ℹ️ Google Sheets ulanmagan"


async def crmga_sinxronlash(chat_id: int) -> bool | None:
    """Mijoz kartochkasini CSV va Google Sheetsga yuboradi."""
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    if not lead:
        return None
    await csv_yangilash()
    return await google_sheetsga_yozish({
        "sana": lead["created_at"],
        "ism": lead["full_name"],
        "telefon": lead["telefon"] or "",
        "username": lead["username"] or "",
        "telegram_id": lead["telegram_id"],
        "tashkilot": lead["tashkilot"] or "",
        "lavozim": lead["lavozim"] or "",
        "ehtiyoj": lead["mavzu"] or "",
        "mahsulot": lead["mahsulot"] or "",
        "bosqich": BOSQICH_NOMLARI.get(lead["bosqich"], lead["bosqich"] or ""),
        "harorat": HARORAT_NOMLARI.get(lead["harorat"], lead["harorat"] or ""),
        "summa": lead["summa"] or "",
        "izoh": lead["xulosa"] or "",
        "chat_id": chat_id,
    })


def lead_kartochkasi(lead, sarlavha: str) -> str:
    """Egaga yuboriladigan mijoz kartochkasi (HTML)."""
    qatorlar = [
        f"{sarlavha}\n",
        f"👤 <b>Mijoz:</b> {mijoz_havolasi(lead['telegram_id'], lead['full_name'], lead['username'] or '')}",
        f"📞 <b>Telefon:</b> {h(lead['telefon'] or 'hali aytilmagan')}",
    ]
    if lead["tashkilot"] or lead["lavozim"]:
        qatorlar.append(f"🏢 <b>Kompaniya:</b> {h(', '.join(x for x in (lead['tashkilot'], lead['lavozim']) if x))}")
    if lead["mavzu"]:
        qatorlar.append(f"🎯 <b>Ehtiyoj:</b> {h(qisqartir(lead['mavzu'], 300))}")
    if lead["mahsulot"]:
        qatorlar.append(f"📦 <b>Mahsulot:</b> {h(qisqartir(lead['mahsulot'], 500))}")
    qatorlar.append(
        f"📊 <b>Bosqich:</b> {h(BOSQICH_NOMLARI.get(lead['bosqich'], lead['bosqich'] or '-'))} | "
        f"{h(HARORAT_NOMLARI.get(lead['harorat'], ''))}"
    )
    if lead["xulosa"]:
        qatorlar.append(f"📝 {h(qisqartir(lead['xulosa'], 500))}")
    return "\n".join(qatorlar)


def _telefon_topish(natija: dict, xabar_matni: str) -> str:
    """Telefon: avval mijoz xabaridan (aniq), keyin AI ajratganidan (tekshirilgan holda)."""
    m = PHONE_REGEX.search(xabar_matni or "")
    if m:
        return m.group(0)
    m = PHONE_REGEX.search(natija["mijoz"]["telefon"])
    return m.group(0) if m else ""


async def crm_yangilash(chat_id: int, mijoz: types.User, natija: dict, holat: dict,
                        xabar_matni: str, business_connection_id: str | None, ega_id: int | None):
    """AI natijasi asosida mijoz kartochkasini yangilaydi, omborga so'rov va egalarga bildirishnoma yuboradi."""
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    eski_bosqich = lead["bosqich"] if lead else ""
    bosqich = sotuv.bosqichni_birlashtirish(eski_bosqich, natija["bosqich"])
    taklif = holat.get("taklif")
    kelishildi_yangi = natija["buyurtma_tasdiqlandi"] and taklif is not None and eski_bosqich != "kelishildi"
    if kelishildi_yangi:
        bosqich = "kelishildi"
    elif bosqich == "kelishildi" and taklif is None:
        # Taklif (narx) yuborilmasdan "kelishildi" bo'lishi mumkin emas
        logging.info("AI 'kelishildi' dedi, lekin taklif yuborilmagan - muzokara deb belgilandi (chat %s).", chat_id)
        bosqich = sotuv.bosqichni_birlashtirish(eski_bosqich, "muzokara")

    pozitsiyalar = natija["mahsulotlar"]
    telefon = _telefon_topish(natija, xabar_matni)
    mazmunli = bool(lead) or bool(pozitsiyalar) or bool(telefon) or any(natija["mijoz"].values())
    if not mazmunli:
        return

    username = f"@{mijoz.username}" if mijoz.username else ""
    yangi = await asyncio.to_thread(
        db.upsert_lead, chat_id,
        full_name=natija["mijoz"]["ism"] or (lead["full_name"] if lead else "") or mijoz.full_name,
        username=username,
        telegram_id=mijoz.id,
        telefon=telefon,
        tashkilot=natija["mijoz"]["kompaniya"],
        lavozim=natija["mijoz"]["lavozim"],
        mavzu=natija["ehtiyoj"],
        mahsulot=_pozitsiyalar_qisqa(pozitsiyalar) if pozitsiyalar else "",
        bosqich=bosqich,
        harorat=natija["harorat"],
        xulosa=natija["xulosa"],
    )

    if yangi or bosqich != eski_bosqich:
        sheets = await crmga_sinxronlash(chat_id)
        if yangi:
            lead = await asyncio.to_thread(db.get_lead, chat_id)
            await egalarga_yuborish(
                lead_kartochkasi(lead, "🔔 <b>YANGI MIJOZ</b>") + f"\n\n<i>{_sheets_matni(sheets)}</i>", ega_id
            )

    # Pozitsiya va miqdor aniq bo'lsa: omborga narx so'rovi yoki mijozga narxsiz PDF taklif
    if natija["narx_sorash"] and pozitsiyalar and all(p["miqdor"] > 0 for p in pozitsiyalar):
        if NARX_OMBORDAN:
            await narx_sorovi_yaratish(chat_id, mijoz, natija, business_connection_id)
        else:
            await pdf_taklif_yuborish(chat_id, mijoz, natija, business_connection_id, ega_id)

    if kelishildi_yangi:
        await asyncio.to_thread(db.mark_chat_completed, chat_id)
        lead = await asyncio.to_thread(db.get_lead, chat_id)
        taklif_qatori = f"📄 Taklif {taklif_pdf.taklif_raqami(taklif['id'])}"
        if taklif["narxlar"]:
            _, jami = sotuv.hisoblash(json.loads(taklif["pozitsiyalar"]), json.loads(taklif["narxlar"]))
            oldindan, qolgan = sotuv.tolov_qismlari(jami)
            tolov = f"{sotuv.son_format(oldindan)} so'm oldindan" + (f", {sotuv.son_format(qolgan)} so'm olib ketishdan oldin" if qolgan else "")
            taklif_qatori += f": <b>{sotuv.son_format(jami)} so'm</b>\n💳 {h(tolov)}"
        await egalarga_yuborish(
            lead_kartochkasi(lead, "🎉 <b>MIJOZ BUYURTMANI TASDIQLADI</b>")
            + f"\n\n{taklif_qatori}\n➡️ Mijoz bilan bog'lanib, narx va schyotni rasmiylashtiring.",
            ega_id,
        )
    elif natija["menejer_kerak"] and await asyncio.to_thread(db.menejer_chaqirish_mumkinmi, chat_id, 60):
        lead = await asyncio.to_thread(db.get_lead, chat_id)
        await egalarga_yuborish(
            lead_kartochkasi(lead, "🙋 <b>MENEJER ARALASHUVI KERAK</b>")
            + f"\n\n❗️ <b>Sabab:</b> {h(natija['menejer_sababi'] or '-')}"
            + f"\n💬 <b>Oxirgi xabar:</b> {h(qisqartir(xabar_matni, 300))}"
            + f"\n🆔 Chat: <code>{chat_id}</code>",
            ega_id,
        )


# =====================================================================
#  NARXSIZ PDF TIJORAT TAKLIFI (NARX_OMBORDAN=0)
# =====================================================================

async def pdf_taklif_yuborish(chat_id: int, mijoz: types.User, natija: dict,
                              business_connection_id: str | None, ega_id: int | None):
    """
    UMATIC shablonidagi narxsiz tijorat taklifini (PDF) mijozga yuboradi, nusxasini menejerga yuboradi.
    Aynan shu pozitsiyalarga taklif allaqachon yuborilgan bo'lsa - takrorlanmaydi.
    """
    pozitsiyalar = natija["mahsulotlar"]
    kalit = sotuv.mahsulotlar_kaliti(pozitsiyalar)
    oxirgi = await asyncio.to_thread(db.get_oxirgi_taklif, chat_id)
    if oxirgi and oxirgi["kalit"] == kalit:
        return

    til = natija["til"] or "uz_latn"
    sorov_id = await asyncio.to_thread(
        db.create_sorov, chat_id, mijoz.id, business_connection_id, til,
        json.dumps(pozitsiyalar, ensure_ascii=False), kalit, natija["ehtiyoj"],
    )
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    raqam = taklif_pdf.taklif_raqami(sorov_id)
    predmet = tmatn("taklif_predmeti", til).format(soni=len(pozitsiyalar))
    try:
        pdf = await asyncio.to_thread(
            taklif_pdf.taklif_pdf, sorov_id, til, pozitsiyalar,
            natija["mijoz"]["ism"],
            natija["mijoz"]["kompaniya"] or (lead["tashkilot"] if lead else ""),
            lead["telefon"] if lead and lead["telefon"] else "",
            predmet,
        )
    except Exception as e:
        logging.exception("Taklif PDF yaratishda xato: %s", e)
        await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("kutilmoqda",), "bekor")
        return
    fayl_nomi = taklif_pdf.fayl_nomi(sorov_id, til)
    izoh = tmatn("taklif_izoh", til).format(raqam=raqam)

    try:
        await bot.send_document(
            chat_id=chat_id,
            document=types.BufferedInputFile(pdf, filename=fayl_nomi),
            caption=izoh,
            business_connection_id=business_connection_id or None,
        )
        yuborildi = True
    except TelegramAPIError as e:
        logging.error("Taklif PDF ni mijozga yuborib bo'lmadi (chat %s): %s", chat_id, e)
        yuborildi = False

    if yuborildi:
        await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("kutilmoqda",), "yuborildi")
        await asyncio.to_thread(db.update_sorov, sorov_id, yuborilgan_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        await asyncio.to_thread(db.add_message, chat_id, "assistant", f"[PDF: {raqam}] {izoh}")
        await asyncio.to_thread(db.upsert_lead, chat_id, bosqich=sotuv.bosqichni_birlashtirish(
            lead["bosqich"] if lead else "", "taklif_berildi"))
        sarlavha = f"📄 <b>TIJORAT TAKLIFI {raqam} MIJOZGA YUBORILDI</b>"
        keyingi = "➡️ Mijozga narxni bildiring."
    else:
        await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("kutilmoqda",), "bekor")
        sarlavha = f"⚠️ <b>TAKLIF {raqam} MIJOZGA YUBORILMADI</b>"
        keyingi = "➡️ Faylni mijozga o'zingiz yuboring."

    sheets = await crmga_sinxronlash(chat_id)
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    matn = (lead_kartochkasi(lead, sarlavha) if lead else sarlavha) + f"\n\n{keyingi}\n<i>{_sheets_matni(sheets)}</i>"
    for target in await asyncio.to_thread(hisobot_oluvchilar, ega_id):
        try:
            await bot.send_document(
                chat_id=target,
                document=types.BufferedInputFile(pdf, filename=fayl_nomi),
                caption=qisqartir(matn, 1000),
                parse_mode="HTML",
            )
        except Exception as e:
            logging.warning("Taklif nusxasini egaga (%s) yuborib bo'lmadi: %s", target, e)


# =====================================================================
#  OMBOR BILAN ISHLASH (NARX_OMBORDAN=1): NARX SO'ROVI -> NARX KIRITISH -> TASDIQ -> MIJOZGA TAKLIF
# =====================================================================

def _tugma(matn: str, data: str) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(text=matn, callback_data=data)


def sorov_tugmalari(sorov_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        _tugma("💰 Narx kiritish", f"s:n:{sorov_id}"),
        _tugma("❌ Omborda yo'q", f"s:y:{sorov_id}"),
    ]])


def sorov_matni(sorov_id: int, pozitsiyalar: list[dict], lead, til: str, ehtiyoj: str) -> str:
    qatorlar = [f"🆕 <b>NARX SO'ROVI #{sorov_id}</b>"]
    if lead:
        qatorlar.append(
            f"👤 {mijoz_havolasi(lead['telegram_id'], lead['full_name'], lead['username'] or '')}"
            + (f" | 📞 {h(lead['telefon'])}" if lead["telefon"] else "")
            + (f" | 🏢 {h(lead['tashkilot'])}" if lead["tashkilot"] else "")
        )
    qatorlar.append(f"🌐 Mijoz tili: {TIL_NOMLARI.get(til, til)}\n")
    for i, p in enumerate(pozitsiyalar, 1):
        qatorlar.append(f"<b>{i}. {h(p['nomi'])}</b> — <b>{p['miqdor']} {h(p['birlik'])}</b>")
        if p["parametrlar"]:
            qatorlar.append(f"    ⚙️ {h(p['parametrlar'])}")
    if ehtiyoj:
        qatorlar.append(f"\n🎯 {h(qisqartir(ehtiyoj, 300))}")
    qatorlar.append("\nNarx va mavjudlikni kiriting 👇")
    return "\n".join(qatorlar)


async def narx_sorovi_yaratish(chat_id: int, mijoz: types.User, natija: dict, business_connection_id: str | None):
    """Omborga narx so'rovi yuboradi. Bir xil so'rov takrorlanmaydi, o'zgargan so'rov eskisini bekor qiladi."""
    pozitsiyalar = natija["mahsulotlar"]
    kalit = sotuv.mahsulotlar_kaliti(pozitsiyalar)

    faol = await asyncio.to_thread(db.get_faol_sorov, chat_id)
    if faol and faol["kalit"] == kalit:
        return
    taklif = await asyncio.to_thread(db.get_oxirgi_taklif, chat_id)
    if not faol and taklif and taklif["kalit"] == kalit:
        return  # Aynan shu pozitsiyalarga taklif allaqachon yuborilgan

    if faol and await asyncio.to_thread(db.sorov_holatini_ozgartirish, faol["id"], db.FAOL_SOROV_HOLATLARI, "bekor"):
        if faol["sklad_chat_id"] and faol["sklad_msg_id"]:
            try:
                await bot.send_message(
                    chat_id=faol["sklad_chat_id"],
                    text=f"🚫 So'rov #{faol['id']} bekor qilindi: mijoz pozitsiyalarni o'zgartirdi (yangi so'rov yuborildi).",
                    reply_to_message_id=faol["sklad_msg_id"],
                )
            except TelegramAPIError as e:
                logging.warning("Bekor qilish xabarini yuborib bo'lmadi: %s", e)

    til = natija["til"] or "uz_latn"
    sorov_id = await asyncio.to_thread(
        db.create_sorov, chat_id, mijoz.id, business_connection_id, til,
        json.dumps(pozitsiyalar, ensure_ascii=False), kalit, natija["ehtiyoj"],
    )
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    await asyncio.to_thread(db.upsert_lead, chat_id, bosqich=sotuv.bosqichni_birlashtirish(
        lead["bosqich"] if lead else "", "narx_sorovi"))

    matn = sorov_matni(sorov_id, pozitsiyalar, lead, til, natija["ehtiyoj"])
    yuborildi = False
    for target in ombor_chatlari():
        try:
            msg = await bot.send_message(chat_id=target, text=matn, parse_mode="HTML", reply_markup=sorov_tugmalari(sorov_id))
            if not yuborildi:
                await asyncio.to_thread(db.update_sorov, sorov_id, sklad_chat_id=target, sklad_msg_id=msg.message_id)
            yuborildi = True
        except Exception as e:
            logging.error("Narx so'rovini omborga (%s) yuborib bo'lmadi: %s", target, e)
    if not yuborildi:
        logging.error("Narx so'rovi #%s hech kimga yuborilmadi! SKLAD_CHAT_ID / OWNER_ID ni tekshiring.", sorov_id)


def _narx_kiritish_korsatmasi(sorov_id: int, pozitsiyalar: list[dict], xato: str = "") -> str:
    qatorlar = []
    if xato:
        qatorlar.append(f"⚠️ {xato}\n")
    qatorlar.append(f"✍️ So'rov #{sorov_id}: SHU XABARGA JAVOB (reply) qilib, har bir pozitsiya uchun bitta qator yozing:")
    qatorlar.append("<code>1 dona narxi ; omborda nechta bor</code>\n")
    for i, p in enumerate(pozitsiyalar, 1):
        qatorlar.append(f"{i}) {h(p['nomi'])} — {p['miqdor']} {h(p['birlik'])}")
    qatorlar.append(
        "\nMasalan:\n<code>12 500 000 ; 3</code>\n<code>4.2 mln</code>  ← hammasi bor bo'lsa sonini yozmasa ham bo'ladi\n"
        "<code>yo'q</code>  ← bu pozitsiya omborda yo'q\n"
        "<code>izoh: yetkazib berish 2 kun</code>  ← ixtiyoriy, mijozga ko'rinadi"
    )
    return "\n".join(qatorlar)


async def narx_kiritishni_sorash(chat_id: int, sorov, xato: str = "", reply_to: int | None = None):
    """Ombor mas'uliga narx kiritish uchun ForceReply xabar yuboradi va uni so'rovga bog'laydi."""
    pozitsiyalar = json.loads(sorov["pozitsiyalar"])
    msg = await bot.send_message(
        chat_id=chat_id,
        text=_narx_kiritish_korsatmasi(sorov["id"], pozitsiyalar, xato),
        parse_mode="HTML",
        reply_to_message_id=reply_to,
        reply_markup=types.ForceReply(selective=True, input_field_placeholder="12 500 000 ; 3"),
    )
    await asyncio.to_thread(db.update_sorov, sorov["id"], prompt_msg_id=msg.message_id, sklad_chat_id=chat_id)


async def _sklad_xabarini_belgilash(callback: types.CallbackQuery, qoshimcha: str):
    """Ombor chatidagi xabar ostiga natijani yozadi va tugmalarni olib tashlaydi."""
    try:
        await callback.message.edit_text(
            (callback.message.html_text or "") + f"\n\n{qoshimcha}", parse_mode="HTML", reply_markup=None,
        )
    except TelegramAPIError:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass


@dp.callback_query(F.data.startswith("s:"))
async def ombor_tugmasi(callback: types.CallbackQuery):
    """Ombor chatidagi tugmalar: narx kiritish, yo'q, tasdiqlash, mijozga yuborish."""
    try:
        _, amal, sid = callback.data.split(":")
        sorov_id = int(sid)
    except ValueError:
        await callback.answer()
        return

    chat_id = callback.message.chat.id if callback.message else None
    if chat_id is None or not omborga_ruxsat(callback.from_user.id, chat_id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    sorov = await asyncio.to_thread(db.get_sorov, sorov_id)
    if not sorov:
        await callback.answer("So'rov topilmadi", show_alert=True)
        return
    pozitsiyalar = json.loads(sorov["pozitsiyalar"])
    kim = h(callback.from_user.full_name)

    if amal in ("n", "q"):  # Narx kiritish / qayta kiritish
        if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, db.FAOL_SOROV_HOLATLARI, "narx_kiritilmoqda"):
            await callback.answer(f"So'rov #{sorov_id} allaqachon yakunlangan ({sorov['holat']})", show_alert=True)
            return
        await narx_kiritishni_sorash(chat_id, sorov, reply_to=callback.message.message_id)
        if amal == "q":
            await _sklad_xabarini_belgilash(callback, f"✏️ Qayta kiritilmoqda ({kim})")
        await callback.answer()

    elif amal == "y":  # Omborda yo'q - tasdiq so'rash (tasodifiy bosishdan himoya)
        await callback.message.edit_reply_markup(reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            _tugma("✅ Ha, mijozga aytish", f"s:yh:{sorov_id}"),
            _tugma("↩️ Orqaga", f"s:o:{sorov_id}"),
        ]]))
        await callback.answer("Mijozga 'omborda yo'q' deb yuborilsinmi?")

    elif amal == "o":  # Orqaga
        await callback.message.edit_reply_markup(reply_markup=sorov_tugmalari(sorov_id))
        await callback.answer()

    elif amal == "yh":  # Omborda yo'q - tasdiqlandi
        if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, db.FAOL_SOROV_HOLATLARI, "yoq"):
            await callback.answer("So'rov allaqachon yakunlangan", show_alert=True)
            return
        til = sorov["til"] or "uz_latn"
        xabar = tmatn("hech_yoq", til)
        async with chat_locks[sorov["chat_id"]]:
            xato = await mijozga_yuborish(sorov["chat_id"], sorov["business_connection_id"], xabar)
            if not xato:
                await asyncio.to_thread(db.add_message, sorov["chat_id"], "assistant", xabar)
        natija = "❌ Omborda yo'q — mijozga xabar berildi" if not xato else f"❌ Omborda yo'q — ⚠️ mijozga yuborib bo'lmadi: {h(xato)}"
        await _sklad_xabarini_belgilash(callback, f"{natija} ({kim})")
        lead = await asyncio.to_thread(db.get_lead, sorov["chat_id"])
        if lead:
            await egalarga_yuborish(
                lead_kartochkasi(lead, f"📭 <b>SO'ROV #{sorov_id}: OMBORDA YO'Q</b>")
                + "\n\n➡️ Mijozga muqobil variant yoki buyurtma asosida yetkazib berishni taklif qiling."
            )
        await callback.answer()

    elif amal == "ok":  # Tijorat taklifini mijozga yuborish
        if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("tasdiq_kutilmoqda",), "yuborilmoqda"):
            await callback.answer("So'rov allaqachon yuborilgan yoki o'zgargan", show_alert=True)
            return
        narxlar = json.loads(sorov["narxlar"] or "[]")
        taklif, jami = sotuv.taklif_matni(sorov_id, pozitsiyalar, narxlar, sorov["til"], sorov["ombor_izohi"] or "")
        async with chat_locks[sorov["chat_id"]]:
            xato = await mijozga_yuborish(sorov["chat_id"], sorov["business_connection_id"], taklif)
            if xato:
                await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("yuborilmoqda",), "tasdiq_kutilmoqda")
                await callback.message.reply(
                    f"⚠️ Taklif #{sorov_id} mijozga yuborilmadi: {h(xato)}\n"
                    "Telegram Business orqali bot faqat mijoz oxirgi 24 soat ichida yozgan chatga xabar yubora oladi. "
                    "Mijozga o'zingiz yozing yoki keyinroq «✅ Mijozga yuborish» ni qayta bosing.",
                    parse_mode="HTML",
                )
                await callback.answer("Yuborib bo'lmadi", show_alert=True)
                return
            await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("yuborilmoqda",), "yuborildi")
            await asyncio.to_thread(db.update_sorov, sorov_id, summa=jami, yuborilgan_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            await asyncio.to_thread(db.add_message, sorov["chat_id"], "assistant", taklif)

        lead = await asyncio.to_thread(db.get_lead, sorov["chat_id"])
        await asyncio.to_thread(
            db.upsert_lead, sorov["chat_id"],
            bosqich=sotuv.bosqichni_birlashtirish(lead["bosqich"] if lead else "", "taklif_berildi"),
            summa=jami,
        )
        sheets = await crmga_sinxronlash(sorov["chat_id"])
        await _sklad_xabarini_belgilash(
            callback, f"✅ Mijozga yuborildi ({kim}). Jami: {sotuv.son_format(jami)} so'm. <i>{_sheets_matni(sheets)}</i>"
        )
        await callback.answer("Yuborildi ✅")

    else:
        await callback.answer()


_PROMPT_REGEX = re.compile(r"So'rov #(\d+): SHU XABARGA JAVOB")


class OmborJavobiFilter(Filter):
    """
    Ombor mas'uli bot so'ragan narx kiritish xabariga javob (reply) yozganini aniqlaydi.
    So'rov raqami javob berilgan xabar matnidan olinadi - bir nechta mas'ul bir vaqtda ishlasa ham chalkashmaydi.
    """

    async def __call__(self, message: types.Message) -> bool | dict:
        reply = message.reply_to_message
        if not reply or not message.text or not reply.from_user or reply.from_user.id != bot.id:
            return False
        m = _PROMPT_REGEX.search(reply.text or "")
        if not m:
            return False
        sorov = await asyncio.to_thread(db.get_sorov, int(m.group(1)))
        if not sorov:
            return False
        return {"sorov": sorov}


@dp.message(OmborJavobiFilter())
async def ombor_narx_javobi(message: types.Message, sorov):
    """Ombor mas'uli kiritgan narxlarni tekshiradi va mijozga yuborishdan oldin ko'rsatadi."""
    if not omborga_ruxsat(message.from_user.id if message.from_user else None, message.chat.id):
        return
    if sorov["holat"] != "narx_kiritilmoqda":
        await message.reply(f"So'rov #{sorov['id']} allaqachon yakunlangan ({sorov['holat']}).")
        return

    pozitsiyalar = json.loads(sorov["pozitsiyalar"])
    try:
        javob = sotuv.ombor_javobini_tahlil(message.text, pozitsiyalar)
    except ValueError as e:
        await narx_kiritishni_sorash(message.chat.id, sorov, xato=str(e), reply_to=message.message_id)
        return

    if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov["id"], ("narx_kiritilmoqda",), "tasdiq_kutilmoqda"):
        await message.reply("So'rov holati o'zgargan, qayta urinib ko'ring.")
        return

    taklif, jami = sotuv.taklif_matni(sorov["id"], pozitsiyalar, javob.narxlar, sorov["til"], javob.izoh)
    await asyncio.to_thread(
        db.update_sorov, sorov["id"],
        narxlar=json.dumps(javob.narxlar), ombor_izohi=javob.izoh, summa=jami,
    )
    await message.reply(
        f"👀 <b>Tekshiring — mijozga aynan shunday yuboriladi</b> ({TIL_NOMLARI.get(sorov['til'], '')}):\n\n"
        f"<pre>{h(taklif)}</pre>",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            _tugma("✅ Mijozga yuborish", f"s:ok:{sorov['id']}"),
            _tugma("✏️ Qayta kiritish", f"s:q:{sorov['id']}"),
        ]]),
    )


# =====================================================================
#  BOT EGASI UCHUN ADMIN BUYRUQLARI
# =====================================================================

BUYRUQLAR_MATNI = (
    "Buyruqlar:\n"
    "• /leads — Oxirgi mijozlar\n"
    "• /sorovlar — Javob kutayotgan narx so'rovlari\n"
    "• /export — Barcha mijozlar (Excel/CSV)\n"
    "• /stats — Statistika\n"
    "• /bilim — Bilimlar bazasi holati\n"
    "• /chatid — Joriy chat ID (ombor guruhini sozlash uchun)\n"
    "• /resume &lt;chat_id&gt; — Chatda botni qayta yoqish\n"
    "• /reset &lt;chat_id&gt; — Chat xotirasini tozalash\n"
    "• /help — Qo'llanma"
)


@dp.message(CommandStart())
async def start_komandasi(message: types.Message):
    """Ega /start bossa - ro'yxatga olinadi. Mijoz bossa - savdo salomlashuvi."""
    user = message.from_user
    if user is None:
        return

    ega = egami(user.id)
    # OWNER_ID o'rnatilmagan va hali hech kim ro'yxatdan o'tmagan bo'lsa - birinchi foydalanuvchi ega bo'ladi
    if not ega and not OWNER_IDS and not db.get_owner_ids() and not egalar:
        ega = True
        logging.warning("Birinchi ega /start orqali ro'yxatga olindi: %s. OWNER_ID ni .env ga yozish tavsiya etiladi.", user.id)

    if not ega:
        if message.chat.type != "private":
            return
        til = "ru" if (user.language_code or "").startswith("ru") else "uz_latn"
        salom = tanishtiruv_matni(til)
        await asyncio.to_thread(db.save_chat_meta, message.chat.id, user.id, None, til)
        await asyncio.to_thread(db.add_message, message.chat.id, "assistant", TAQDIMOT_BELGISI)
        await message.answer(salom)
        return

    db.save_owner_id(user.id)
    await message.answer(
        f"Assalomu alaykum, <b>{h(user.full_name)}</b>!\n\n"
        f"🤖 Men <b>{h(KOMPANIYA_NOMI)}</b> savdo menejeri botiman: mijozlarga mahsulotlarni tanishtiraman, "
        "ehtiyojini aniqlayman, narxni ombordan so'rab tijorat taklifi yuboraman va hammasini CRM ga yig'aman.\n\n"
        f"🆔 Sizning Telegram ID: <code>{user.id}</code>"
        + ("" if OWNER_IDS else "\n⚠️ Xavfsizlik uchun ushbu raqamni <code>.env</code> / Render sozlamalariga <code>OWNER_ID</code> sifatida yozing.")
        + "\n\n" + BUYRUQLAR_MATNI,
        parse_mode="HTML",
    )


@dp.message(Command("chatid"), EgaFilter())
async def chatid_komandasi(message: types.Message):
    await message.answer(
        f"Bu chat ID: <code>{message.chat.id}</code>\n"
        "Ombor guruhi uchun: botni guruhga qo'shing, shu buyruqni guruhda yuboring va raqamni SKLAD_CHAT_ID ga yozing.",
        parse_mode="HTML",
    )


@dp.message(Command("leads"), EgaFilter())
async def leads_komandasi(message: types.Message):
    oxirgi = db.get_recent_leads(limit=5)
    if not oxirgi:
        await message.answer("Hozircha mijozlar yo'q.")
        return
    bloklar = [lead_kartochkasi(r, f"<b>{i}.</b> <i>{h(r['updated_at'] or r['created_at'])}</i>") for i, r in enumerate(oxirgi, 1)]
    await message.answer(qisqartir("\n\n".join(bloklar), 4000), parse_mode="HTML")


@dp.message(Command("sorovlar"), EgaFilter())
async def sorovlar_komandasi(message: types.Message):
    sorovlar = db.get_faol_sorovlar()
    if not sorovlar:
        await message.answer("✅ Javob kutayotgan narx so'rovlari yo'q.")
        return
    qatorlar = [f"⏳ <b>Javob kutayotgan so'rovlar: {len(sorovlar)} ta</b>\n"]
    for s in sorovlar[:20]:
        qatorlar.append(f"#{s['id']} — {h(s['created_at'])} — {h(qisqartir(_pozitsiyalar_qisqa(json.loads(s['pozitsiyalar'])), 150))}")
    await message.answer("\n".join(qatorlar), parse_mode="HTML")


@dp.message(Command("export", "excel"), EgaFilter())
async def export_komandasi(message: types.Message):
    if not db.get_recent_leads(limit=1):
        await message.answer("Hozircha saqlangan mijozlar yo'q.")
        return
    if not await csv_yangilash():
        await message.answer("CSV faylni shakllantirishda xatolik yuz berdi.")
        return
    try:
        fayl = types.FSInputFile(LEADLAR_FAYLI, filename=f"{KOMPANIYA_NOMI}_Mijozlar_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        await message.answer_document(document=fayl, caption="📊 Barcha mijozlar (Excel'da ochiladi)")
    except Exception as e:
        await message.answer(f"Faylni yuborishda xatolik: {h(e)}", parse_mode="HTML")


@dp.message(Command("stats"), EgaFilter())
async def stats_komandasi(message: types.Message):
    stats = db.get_stats()
    sheets = "ulangan ✅" if os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip() else "ulanmagan"
    await message.answer(
        f"📊 <b>{h(KOMPANIYA_NOMI)} savdo boti statistikasi</b>\n\n"
        f"👥 Mijozlar: <b>{stats['total_leads']}</b>\n"
        f"✅ Buyurtma tasdiqlagan suhbatlar: <b>{stats['completed_chats']}</b>\n"
        f"⏳ Javob kutayotgan narx so'rovlari: <b>{len(db.get_faol_sorovlar())}</b>\n\n"
        f"🧠 AI modeli: <code>{h(MODEL)}</code>\n"
        f"🔁 Zaxira: <code>{h(', '.join(ZAXIRA_MODELLAR) or '-')}</code>\n"
        f"📚 Bilimlar: {len(BILIMLAR)} belgi\n"
        f"🏬 Ombor chati: <code>{SKLAD_CHAT_ID if SKLAD_CHAT_ID is not None else 'egalar'}</code>\n"
        f"📄 Google Sheets: {sheets}",
        parse_mode="HTML",
    )


@dp.message(Command("bilim"), EgaFilter())
async def bilim_komandasi(message: types.Message):
    global BILIMLAR
    BILIMLAR = bilimlarni_yuklash()
    fayllar = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(BILIMLAR_PAPKASI, "*.md")))]
    await message.answer(
        f"📚 Bilimlar qayta yuklandi: <b>{len(BILIMLAR)}</b> belgi\n"
        f"Fayllar: {h(', '.join(fayllar) or 'yoq')}\n\n"
        "Bilimlarni o'zgartirish: <code>bilimlar/</code> papkasidagi fayllarni tahrirlab, GitHub'ga yuklang — "
        "server qayta ishga tushganda yangilanadi.",
        parse_mode="HTML",
    )


def _chat_id_ajratish(message: types.Message) -> int | None:
    qismlar = (message.text or "").split()
    if len(qismlar) > 1 and qismlar[1].lstrip("-").isdigit():
        return int(qismlar[1])
    return None


@dp.message(Command("resume"), EgaFilter())
async def resume_komandasi(message: types.Message):
    target_id = _chat_id_ajratish(message)
    if target_id is None:
        await message.answer("Iltimos, chat ID sini kiriting. Masalan:\n<code>/resume 12345678</code>", parse_mode="HTML")
        return
    db.clear_owner_activity(target_id)
    await message.answer(f"✅ Chat <code>{target_id}</code> da bot qayta faollashtirildi.", parse_mode="HTML")


@dp.message(Command("reset"), EgaFilter())
async def reset_komandasi(message: types.Message):
    target_id = _chat_id_ajratish(message)
    if target_id is None:
        await message.answer("Iltimos, chat ID sini kiriting. Masalan:\n<code>/reset 12345678</code>", parse_mode="HTML")
        return
    db.clear_chat_history(target_id)
    await message.answer(f"✅ Chat <code>{target_id}</code> xotirasi tozalandi.", parse_mode="HTML")


@dp.message(Command("help"), EgaFilter())
async def help_komandasi(message: types.Message):
    await message.answer(
        f"💡 <b>{h(KOMPANIYA_NOMI)} savdo boti qo'llanmasi</b>\n\n"
        "1. Mijoz yozadi (Telegram Business yoki botning o'zi) — bot mahsulotni tanishtiradi va ehtiyojni aniqlaydi.\n"
        + (
            "2. Pozitsiya va miqdor aniq bo'lgach, ombor chatiga <b>NARX SO'ROVI</b> keladi.\n"
            "3. Ombor mas'uli «💰 Narx kiritish» ni bosib, narx va qoldiqni yozadi.\n"
            "4. Bot jami summa va to'lov shartini o'zi hisoblab ko'rsatadi — «✅ Mijozga yuborish» bosilgach, taklif mijozga ketadi.\n"
            if NARX_OMBORDAN else
            "2. Pozitsiya va miqdor aniq bo'lgach, bot mijozga <b>narxsiz tijorat taklifini (PDF)</b> yuboradi.\n"
            "3. Taklif nusxasi sizga ham keladi — mijozga narxni o'zingiz bildirasiz.\n"
            "4. Bot hech qachon narx aytmaydi.\n"
        )
        + "5. Yangi mijoz, buyurtma tasdiqlanishi va menejer kerak bo'lgan holatlar haqida sizga xabar keladi.\n"
        f"6. Siz mijozga o'zingiz yozsangiz, bot {EGA_PAUZA_DAQIQA} daqiqa jim turadi (<code>/resume &lt;chat_id&gt;</code>).\n\n"
        + BUYRUQLAR_MATNI,
        parse_mode="HTML",
    )


# =====================================================================
#  MIJOZ XABARLARINI QAYTA ISHLASH
# =====================================================================

@dp.business_connection()
async def ulanish_bildirishi(conn: types.BusinessConnection):
    """Telegram Business akkaunti ulanganda."""
    egalar[conn.id] = conn.user.id
    await asyncio.to_thread(db.save_owner_id, conn.user.id)
    logging.info("Biznes akkaunt ulandi: @%s (faol: %s)", conn.user.username, conn.is_enabled)


async def mediani_menejerga_yuborish(message: types.Message, turi: str):
    """Mijoz yuborgan rasm/hujjatni (masalan, dvigatel shildigi) menejer va omborga yuboradi - AI rasmni ko'rmaydi."""
    user = message.from_user
    izoh = (
        f"📎 {mijoz_havolasi(user.id, user.full_name, f'@{user.username}' if user.username else '')} {turi} yubordi"
        + (f":\n{h(qisqartir(message.caption, 500))}" if message.caption else "")
        + f"\n🆔 Chat: <code>{message.chat.id}</code>"
    )
    maqsadlar = set(ombor_chatlari()) | await asyncio.to_thread(hisobot_oluvchilar, None)
    for target in maqsadlar:
        try:
            if message.photo:
                await bot.send_photo(chat_id=target, photo=message.photo[-1].file_id, caption=izoh, parse_mode="HTML")
            elif message.document:
                await bot.send_document(chat_id=target, document=message.document.file_id, caption=izoh, parse_mode="HTML")
        except Exception as e:
            logging.warning("Mediani (%s) ga yuborib bo'lmadi: %s", target, e)


async def xabar_matnini_olish(message: types.Message, is_business: bool) -> str | None:
    """Xabar turini aniqlab matnga aylantiradi (ovoz - Whisper, rasm/hujjat - menejerga)."""
    if message.text:
        return message.text.strip()
    if message.contact:
        ism = f"{message.contact.first_name or ''} {message.contact.last_name or ''}".strip()
        return f"[Mijoz kontakt ulashdi] Ismi: {ism}, telefon: {message.contact.phone_number}"
    if message.photo or message.document:
        turi = "rasm" if message.photo else "fayl"
        await mediani_menejerga_yuborish(message, turi)
        caption = f" Izohi: {message.caption.strip()}" if message.caption else ""
        return f"[Mijoz {turi} yubordi (sen uni ko'ra olmaysan, u menejerga yuborildi).{caption}]"
    if message.location:
        return f"[Mijoz lokatsiya yubordi: {message.location.latitude}, {message.location.longitude}]"

    for media, fayl_nomi in (
        (message.voice, "voice.ogg"),
        (message.video_note, "video_note.mp4"),
        (message.audio, "audio.mp3"),
    ):
        if media:
            matn = await ovozni_matnga_aylantirish(media.file_id, fayl_nomi)
            if not matn:
                await javob_yubor(message, "Kechirasiz, ovozni aniq eshita olmadim. Iltimos, matn ko'rinishida yozing.", is_business)
                return None
            return matn

    await javob_yubor(message, "Iltimos, savolingizni matn yoki ovozli xabar ko'rinishida yuboring.", is_business)
    return None


async def xabarni_qayta_ishlash(message: types.Message, is_business: bool = True):
    """Mijoz xabarini qayta ishlaydi: AI javobi, CRM, narx so'rovi."""
    chat_id = message.chat.id
    ega_id = None
    bcid = message.business_connection_id if is_business else None

    if is_business and bcid:
        # Botning o'zi business akkaunt nomidan yuborgan xabar ham update bo'lib qaytadi -
        # uni menejer yozgan deb hisoblamaslik kerak (aks holda bot o'zini 30 daqiqaga o'chirib qo'yadi)
        if message.sender_business_bot is not None:
            return
        ega_id = await ega_id_ol(bcid)
        # Menejer (akkaunt egasi) o'zi yozsa - bot jim turadi
        if message.from_user is None or message.from_user.id == ega_id:
            await asyncio.to_thread(db.record_owner_activity, chat_id)
            return
        if await asyncio.to_thread(db.is_owner_recently_active, chat_id, EGA_PAUZA_DAQIQA):
            logging.info("Chat %s da menejer faol, bot aralashmaydi.", chat_id)
            return

    if message.from_user is None:
        return

    xabar_matni = await xabar_matnini_olish(message, is_business)
    if not xabar_matni:
        return

    async with chat_locks[chat_id]:
        oxirgi_vaqt = await asyncio.to_thread(db.get_last_message_time, chat_id)
        if oxirgi_vaqt and (datetime.now() - oxirgi_vaqt).total_seconds() > SESSIYA_SOAT * 3600:
            await asyncio.to_thread(db.clear_chat_history, chat_id)

        tarix = await asyncio.to_thread(db.get_chat_history, chat_id, MAX_TARIX)

        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing", business_connection_id=bcid)
        except Exception:
            pass

        # Mijoz tilini dastur aniqlaydi (AI ga ishonib qolinmaydi): javob va taklif shu tilda bo'ladi
        meta = await asyncio.to_thread(db.get_chat_meta, chat_id)
        til = sotuv.tilni_aniqlash(xabar_matni, meta["til"] if meta else "")

        await asyncio.to_thread(db.add_message, chat_id, "user", xabar_matni)
        await asyncio.to_thread(db.save_chat_meta, chat_id, message.from_user.id, bcid, til)
        tarix.append({"role": "user", "content": xabar_matni})

        # Suhbatning birinchi xabari: AI dan oldin kompaniya va mahsulotlar taqdimoti yuboriladi
        taqdimot_hozir = False
        if not any(m.get("role") == "assistant" for m in tarix):
            tanishtiruv = tanishtiruv_matni(til)
            if await mijozga_yuborish(chat_id, bcid, tanishtiruv) is None:
                await asyncio.to_thread(db.add_message, chat_id, "assistant", TAQDIMOT_BELGISI)
                tarix.append({"role": "assistant", "content": TAQDIMOT_BELGISI})
                taqdimot_hozir = True
                # Faqat salom yozgan bo'lsa - taqdimot yetarli, AI chaqirilmaydi (savol taqdimot oxirida bor)
                if sotuv.faqat_salommi(xabar_matni):
                    return

        holat = await asyncio.to_thread(suhbat_holati, chat_id)

        try:
            natija = await ai_javob(tarix, holat, til)
        except Exception as xato:
            logging.error("AI javob bera olmadi (chat %s): %s", chat_id, xato)
            await javob_yubor(message, tmatn("ai_xato", til), is_business)
            if await asyncio.to_thread(db.menejer_chaqirish_mumkinmi, chat_id, 30):
                u = message.from_user
                await egalarga_yuborish(
                    "⚠️ <b>AI javob bera olmadi</b> (limit yoki xato). Mijozga «menejer javob beradi» deyildi.\n\n"
                    f"👤 {mijoz_havolasi(u.id, u.full_name, f'@{u.username}' if u.username else '')}\n"
                    f"💬 {h(qisqartir(xabar_matni, 400))}\n🆔 Chat: <code>{chat_id}</code>",
                    ega_id,
                )
            return

        javob = sotuv.salomni_moslash(natija["javob"], natija["_birinchi"], til)
        if taqdimot_hozir and sotuv.taqdimotni_takrorlaydimi(javob, tanishtiruv_matni(til)) and not natija["narx_sorash"]:
            logging.info("AI javobi taqdimotni takrorlaydi - yuborilmadi (chat %s).", chat_id)
            await crm_yangilash_xavfsiz(chat_id, message.from_user, natija, holat, xabar_matni, bcid, ega_id)
            return

        # AI qo'shimcha parametr so'rab turib qolsa ham: asosiy ma'lumot yetarli bo'lsa - narx so'rovi yuboriladi
        if not natija["narx_sorash"] and sotuv.narx_sorash_mumkinmi(natija["mahsulotlar"]):
            kalit = sotuv.mahsulotlar_kaliti(natija["mahsulotlar"])
            if kalit not in [r["kalit"] for r in (holat.get("faol"), holat.get("taklif")) if r]:
                natija["narx_sorash"] = True
                javob = f"{javob}\n\n{tmatn('kutish' if NARX_OMBORDAN else 'taklif_tayyorlanmoqda', til)}"
        # Suhbatda allaqachon minnatdorchilik bildirilgan bo'lsa - har javobda "Rahmat" takrorlanmaydi
        oldin_rahmat = any(m["role"] == "assistant" and sotuv.rahmat_aytilganmi(m["content"]) for m in tarix)
        javob = sotuv.takroriy_rahmatni_olib_tashlash(javob, oldin_rahmat, natija["mijoz"]["ism"])

        xato = await mijozga_yuborish(chat_id, bcid, javob)
        if xato:
            return
        await asyncio.to_thread(db.add_message, chat_id, "assistant", javob)

        await crm_yangilash_xavfsiz(chat_id, message.from_user, natija, holat, xabar_matni, bcid, ega_id)


async def crm_yangilash_xavfsiz(chat_id, mijoz, natija, holat, xabar_matni, bcid, ega_id):
    try:
        await crm_yangilash(chat_id, mijoz, natija, holat, xabar_matni, bcid, ega_id)
    except Exception as e:
        logging.exception("CRM yangilashda xatolik (chat %s): %s", chat_id, e)


@dp.business_message()
async def xabar_keldi_biznes(message: types.Message):
    await xabarni_qayta_ishlash(message, is_business=True)


@dp.message(F.chat.type == "private")
async def xabar_keldi_shaxsiy(message: types.Message):
    # Buyruqlar (shu jumladan ruxsatsiz admin buyruqlari) AI ga yuborilmaydi
    if message.text and message.text.startswith("/"):
        return
    await xabarni_qayta_ishlash(message, is_business=False)


# =====================================================================
#  FON VAZIFALARI: OMBORGA ESLATMA VA MIJOZNI KUZATISH
# =====================================================================

async def fon_tekshiruvlari():
    """Ombor javob bermagan so'rovlar va javobsiz qolgan takliflar haqida eslatadi."""
    for s in await asyncio.to_thread(db.get_eslatiladigan_sorovlar, SKLAD_ESLATMA_DAQIQA):
        await asyncio.to_thread(db.update_sorov, s["id"], eslatildi=1)
        matn = f"⏰ <b>Narx so'rovi #{s['id']}</b> ga {SKLAD_ESLATMA_DAQIQA} daqiqadan beri javob berilmadi — mijoz kutmoqda!"
        for target in ([s["sklad_chat_id"]] if s["sklad_chat_id"] else ombor_chatlari()):
            try:
                await bot.send_message(chat_id=target, text=matn, parse_mode="HTML",
                                       reply_to_message_id=s["sklad_msg_id"] if s["sklad_chat_id"] == target else None)
            except TelegramAPIError as e:
                logging.warning("Eslatmani yuborib bo'lmadi: %s", e)

    for s in await asyncio.to_thread(db.get_kuzatiladigan_takliflar, KUZATISH_SOAT):
        await asyncio.to_thread(db.update_sorov, s["id"], kuzatildi=1)
        oxirgi = await asyncio.to_thread(db.get_last_user_message_time, s["chat_id"])
        yuborilgan = datetime.strptime(s["yuborilgan_at"], "%Y-%m-%d %H:%M:%S")
        if oxirgi and oxirgi > yuborilgan:
            continue  # mijoz taklifdan keyin yozgan
        lead = await asyncio.to_thread(db.get_lead, s["chat_id"])
        if lead:
            await egalarga_yuborish(
                lead_kartochkasi(lead, f"📞 <b>TAKLIF {taklif_pdf.taklif_raqami(s['id'])} JAVOBSIZ QOLDI</b>")
                + f"\n\nTaklif yuborilganiga {KUZATISH_SOAT} soatdan oshdi, mijoz javob bermadi."
                + (f" Jami: {sotuv.son_format(s['summa'])} so'm." if s["summa"] else "")
                + "\n➡️ Qo'ng'iroq qilish tavsiya etiladi."
            )


async def fon_loop():
    while True:
        await asyncio.sleep(FON_TEKSHIRUV_ORALIQ)
        try:
            await fon_tekshiruvlari()
        except Exception as e:
            logging.exception("Fon tekshiruvida xatolik: %s", e)


# =====================================================================
#  RENDER CLOUD UCHUN HEALTH CHECK WEB SERVER VA ISHGA TUSHIRISH
# =====================================================================

async def handle_ping(request):
    return web.json_response({"status": "online", "service": f"{KOMPANIYA_NOMI} savdo boti"})


async def start_web_server():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("HTTP Health Check server %s-portda ishga tushdi.", port)
    return runner


async def keepalive_loop(url: str):
    """Render Free 15 daqiqa so'rov kelmasa uxlab qoladi - har 10 daqiqada o'ziga ping yuboramiz."""
    ping_url = url.rstrip("/") + "/health"
    logging.info("Keep-alive yoqildi: %s", ping_url)
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
    runner = await start_web_server()

    vazifalar = [asyncio.create_task(fon_loop())]
    keepalive_url = os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if keepalive_url:
        vazifalar.append(asyncio.create_task(keepalive_loop(keepalive_url)))

    logging.info("%s savdo boti ishga tushdi! To'xtatish uchun: Ctrl + C", KOMPANIYA_NOMI)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for v in vazifalar:
            v.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
