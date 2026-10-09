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
import base64
import csv
import glob
import hashlib
import html
import io
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
# Google Sheets dan mijoz ma'lumotini o'qish kaliti (Apps Script birinchi so'rovda eslab qoladi).
# Berilmasa - BOT_TOKEN dan hosil qilinadi (maxfiy va doimiy, alohida sozlash shart emas).
SHEETS_KALIT = os.getenv("SHEETS_KALIT", "").strip() or (
    hashlib.sha256(f"umatic-sheets:{BOT_TOKEN}".encode()).hexdigest()[:32] if BOT_TOKEN else "")
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
# Tijorat taklifi rejimi:
#   mavjudlik (standart) - avval ombor mavjudlikni tasdiqlaydi (tugmalar), keyin mijozga PDF (narxsiz, "Omborda" ustuni)
#   narx                 - ombor narx va qoldiqni kiritadi, taklif narx va to'lov sharti bilan (eski NARX_OMBORDAN=1)
#   darhol               - ombor tekshiruvisiz darhol narxsiz PDF
_eski_narx_rejimi = os.getenv("NARX_OMBORDAN", "0").strip().lower() in ("1", "true", "ha", "yes")
TAKLIF_REJIMI = os.getenv("TAKLIF_REJIMI", "narx" if _eski_narx_rejimi else "mavjudlik").strip().lower()
if TAKLIF_REJIMI not in ("mavjudlik", "narx", "darhol"):
    TAKLIF_REJIMI = "mavjudlik"
NARX_OMBORDAN = TAKLIF_REJIMI == "narx"
OMBOR_ORQALI = TAKLIF_REJIMI in ("mavjudlik", "narx")

# gpt-oss-120b - Groq production modeli (preview modellar istalgan vaqtda o'chirilishi mumkin),
# sinovlarda tilni (lotin/kirill/rus) eng to'g'ri ushlagan model.
MODEL = os.getenv("MODEL", "openai/gpt-oss-120b")
ZAXIRA_MODELLAR = [
    m.strip() for m in os.getenv("FALLBACK_MODELS", "qwen/qwen3.8-27b").split(",") if m.strip()
]
# Sozlamalarda (MODEL/FALLBACK_MODELS) nima bo'lishidan qat'i nazar, shu modellar ham har doim sinaladi.
# (Masalan, Render'da eski MODEL=qwen qolib ketsa ham bot bitta modelga bog'lanib qolmaydi.)
# (gpt-oss-20b o'zbek tilida sifatsiz, llama esa Groq'dan olib tashlangan - shuning uchun qo'shilmagan.
#  Ikkalasi ham ishlamasa, kod o'zi katalogdan foydali zaxira javob beradi.)
ASOSIY_ZANJIR = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]
WHISPER_MODEL = "whisper-large-v3-turbo"

# Serverdagi kod versiyasi (Render RENDER_GIT_COMMIT ni o'zi beradi) - /stats va /health da ko'rinadi
VERSIYA = (os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "lokal")[:7]
OXIRGI_AI_XATOSI = {"vaqt": "", "xato": ""}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEADLAR_FAYLI = os.getenv("CSV_PATH") or os.path.join(BASE_DIR, "leadlar.csv")
BILIMLAR_PAPKASI = os.getenv("BILIMLAR_PAPKASI") or os.path.join(BASE_DIR, "bilimlar")

MAX_TARIX = 10                                                   # AI ga beriladigan oxirgi xabarlar soni
# Suhbatda shuncha daqiqa hech kim yozmasa - suhbat tugagan: keyingi xabarda bot qaytadan o'zini tanishtiradi
# va boshidan boshlaydi (eski suhbat tarixi va eski takliflar AI ga ko'rsatilmaydi; CRM saqlanadi)
SESSIYA_DAQIQA = int(os.getenv("SESSIYA_DAQIQA", "60"))
SKLAD_ESLATMA_DAQIQA = int(os.getenv("SKLAD_ESLATMA_DAQIQA", "30"))  # ombor javob bermasa eslatish
KUZATISH_SOAT = int(os.getenv("KUZATISH_SOAT", "6"))             # taklifga javob bo'lmasa menejerga eslatish
# Menejer chatga o'zi yozsa, bot FAQAT o'sha chatda shuncha daqiqa jim turadi (oxirgi xabaridan hisoblanadi)
EGA_PAUZA_DAQIQA = int(os.getenv("EGA_PAUZA_DAQIQA", "5"))
KEEPALIVE_ORALIQ = 10 * 60
FON_TEKSHIRUV_ORALIQ = 5 * 60
# Mijoz shuncha daqiqa yozmasa - suhbat tugagan hisoblanadi va egaga mijoz kartochkasi yuboriladi
SUHBAT_YAKUNI_DAQIQA = int(os.getenv("SUHBAT_YAKUNI_DAQIQA", "5"))
# Suhbat tarixi formati/uslubi o'zgarganda oshiriladi: ishga tushganda eski suhbat tarixi bir marta tozalanadi
SUHBAT_VERSIYASI = "umatic-savdo-3"
TABIIY_MIN, TABIIY_MAX = 1.5, 3.5                                 # javob tezligi: juda tez ham emas (soniya)
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
KATALOG: dict[str, list[dict]] = {}
KATALOG_FAYLI = "katalog.json"   # tools/katalog_yangilash.py yaratadi (umatic.uz dan)


def _izohsiz(matn: str) -> str:
    matn = re.sub(r"<!--.*?-->", "", matn, flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", matn).strip()


def bilimlarni_yuklash() -> str:
    """
    bilimlar/*.md fayllarini o'qiydi (<!-- izohlar --> botga ko'rinmaydi).
    Katalog (katalog.json, 104 ta mahsulot) alohida yuklanadi: har so'rovga faqat mijozga mos qismi qo'shiladi.
    """
    global KATALOG
    qismlar = []
    for yol in sorted(glob.glob(os.path.join(BILIMLAR_PAPKASI, "*.md"))):
        with open(yol, encoding="utf-8") as f:
            matn = _izohsiz(f.read())
        if matn:
            qismlar.append(matn)
    katalog_yoli = os.path.join(BILIMLAR_PAPKASI, KATALOG_FAYLI)
    try:
        with open(katalog_yoli, encoding="utf-8") as f:
            KATALOG = sotuv.katalogni_tayyorlash(json.load(f))
    except (OSError, ValueError) as e:
        logging.error("Katalog yuklanmadi (%s): %s", katalog_yoli, e)
        KATALOG = {}
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
    "[Mijozga taqdimot yuborildi: bot o'zini UMATIC AI savdo yordamchisi deb tanishtirdi; 3 yo'nalish - elektr dvigatellar "
    "(АИР, МТН/МТКН, ВА/ВАО, СД/ВДС), nasos agregatlari (ЭЦВ, Д, К, Гном), elektroizolyatsiya (ПЭТВ-2 sim, o'ram "
    "seksiyalari, kiper lenta, qo'lqoplar); parametrlar so'raldi]"
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


def tizim_korsatmasi(katalog: str = "", tafsilot: str = "") -> str:
    # Ixcham yozilgan: Groq bepul tarifida bitta so'rov 7000 tokendan oshmasligi kerak
    return f"""Sen "{KOMPANIYA_NOMI}" kompaniyasining Telegramdagi AI savdo menejerisan. Kompaniya 3 yo'nalishda sotadi: ELEKTR DVIGATELLAR, NASOS AGREGATLARI, ELEKTROIZOLYATSIYA MATERIALLARI (emal sim, stator o'ram seksiyalari, kiper lenta, ish qo'lqoplari).
Vazifang: mahsulotlarni tanishtirish, ehtiyojni aniqlash, mijozni qiziqtirib sotuvga olib borish, CRM uchun ma'lumot yig'ish.

QOIDALAR:
1. Mijoz yozgan til va yozuvda javob ber (o'zbek lotin / o'zbek kirill / rus).
2. FAQAT BILIMLAR, KATALOG va TAFSILOTdagi faktlarni ayt. Har bir raqam (kVt, ob/min, A, kg, %, V, m³/soat, m) AYNAN o'sha modelning katalog qatoridan bo'lsin - bir modelning raqamini boshqasiga yozma. Ma'lumotlarda yo'q narsa so'ralsa (kafolat, yetkazish muddati, brend nomi, sertifikat, qoldiq...) - "bu bo'yicha aniq ma'lumotni menejerimiz beradi" de, O'YLAB TOPMA. Narx, qoldiq, muddat, chegirma, kafolat, yo'q model yoki xususiyatni O'YLAB TOPMA. Modelni "katalogimizda bor" deb tanishtir, lekin "omborda bor", "mavjud", "yo'q", "mavjud emas" DEMA - omborda borligini ombor tasdiqlaydi. Saytdagi 3 yo'nalishning birortasini "sotmaymiz" dema. O'zingcha hisoblab model tavsiya qilma.
3. {_narx_qoidasi()}
4. FAOL SOTUVCHI BO'L, quruq so'roq qilma:
 - aniq ehtiyoj aytilmasa - 3 yo'nalishni va mos turlarni qisqa tanishtir, nima kerakligini so'ra;
 - parametr aytilsa (dvigatel: kVt, ob/min; nasos: sarf m³/soat, napor m; sim: diametr) - KATALOGdan mos modelni nomi va xususiyatlari bilan darhol taklif qil;
 - mexanizm yoki vazifa aytilsa (kran, konveyer, quduq, drenaj, shaxta, o'ram) - mos turni va foydasini ayt;
 - afzallik va qo'llanish sohasini FAQAT TAFSILOTdagi "QO'LLANILISHI VA AFZALLIKLARI" matnidan yoki BILIMLARdan ayt (mijoz tiliga o'girib), o'zingdan qo'shma; oxirida keyingi qadamga bitta savol.
5. AVVAL mijozning savoliga TO'LIQ javob ber: u so'ragan HAR BIR narsaga (masalan, tok, vazn VA qayerda ishlatilishi) javob bo'lsin. Texnik ma'lumot so'ralsa - qisqa ro'yxat qilib yozish mumkin. Oddiy javob 2-5 gap. Salomlashma, "Rahmat/Tushundim/Ajoyib" bilan boshlama (minnatdorchilik butun suhbatda ko'pi bilan 1 marta). Suhbat boshida kompaniya taqdimoti yuborilgan - uni takrorlama.
6. Bir savolni ko'pi bilan 1 marta qayta so'ra. Mijoz bilmasa - oldinga o't. Asosiy parametrlar va miqdor ma'lum bo'lsa narx_sorash=true.
6b. Model va seriya nomlarini KATALOGDAGIDEK kirill harflarida yoz (АИР132М4У1, МТН 411-8, ЭЦВ 8-25-100, ПЭТВ-2) - hech qachon lotinga o'girma.
6c. TAFSILOT va KATALOG ruscha - ularni mijoz tiliga O'GIRIB yoz, ruscha gaplarni ko'chirma (faqat model nomlari kirillda qoladi). Texnik savolga TAFSILOT bo'limidagi ma'lumot bilan javob ber: mijoz so'ragan parametrlar, "to'liq ma'lumot" so'ralsa - eng muhim 8-10 tasi qisqa ro'yxatda va 1-2 gap qo'llanilishi, oxirida mahsulot sahifasi havolasi (javob 900 belgidan oshmasin).
7. Sen AI yordamchisan, odam ekanligingni da'vo qilma; "kimsiz?" desa - UMATIC ning AI savdo yordamchisi ekaningni ayt. Mijoz rasm so'rasa - katalog rasmi javobingdan keyin avtomatik yuboriladi (JORIY HOLATda ko'rsatiladi): "tizim" so'zini ishlatma, qisqa "mana, rasmi" mazmunida ayt. Mijoz rasm yuborsa - uning avtomatik tavsifi [Mijoz rasm yubordi ...] ichida beriladi: shildik ma'lumoti bo'lsa shu parametrlarga katalogdan mos model tavsiya qil. [Mijoz stiker yubordi ...] - stiker ma'nosiga mos qisqa, samimiy javob berib suhbatni davom ettir (👍 - rozilik, 🙏 - minnatdorchilik, 😂 - hazil).
7a. "(Menejer yozdi)" bilan boshlangan xabarlarni jonli menejer yozgan: ularga zid gapirma, uning aytganlarini davom ettir, bu belgini o'zing yozma.
8a. Har qanday savolga O'ZING to'liq javob ber (bilimlar va katalog asosida) va ehtiyojga qarab aniq mahsulot tavsiya qil. "Menejer siz bilan bog'lanadi" deb FAQAT narx, chegirma, omborda borligi yoki yetkazib berish so'ralganda ayt - butun suhbatda ko'pi bilan 1 marta. Texnik va umumiy savollarni menejerga yo'naltirma.
9. menejer_kerak=true FAQAT: chegirma, bilimlarda javobi yo'q texnik savol, shikoyat, qo'ng'iroq/uchrashuv so'rovi.
10. buyurtma_tasdiqlandi=true faqat mijoz yuborilgan taklifni aniq qabul qilsa.
11. Ism va telefonni suhbat boshida va o'rtasida SO'RAMA. Faqat mijoz qaror qilgandan keyin (model tanladi, taklif/narx so'radi, buyurtma bermoqchi) bir marta, majburiy emasligini aytib so'ra: "Xohlasangiz, ismingiz va telefon raqamingizni qoldiring - majburiy emas". Bermasa - qayta so'rama. Doimiy mijoz haqidagi ko'rsatma JORIY HOLATda beriladi.
12. Mijoz "bu", "shu motor", "этот" desa yoki bot xabariga javoban yozsa - gap o'sha ko'rsatilgan model haqida: "qaysi model?" deb qayta so'rama, shu model haqida to'liq javob ber.

JSON: mahsulotlar - suhbatdagi barcha pozitsiyalarning so'nggi holati (miqdor noma'lum = 0); mijoz - faqat mijoz o'zi aytgani; xulosa - menejer uchun 1-2 gap.
Kalitlar: javob, til, mijoz{{ism, telefon, kompaniya, lavozim, soha}}, ehtiyoj, mahsulotlar[{{nomi, parametrlar, miqdor, birlik}}], narx_sorash, buyurtma_tasdiqlandi, bosqich, harorat, menejer_kerak, menejer_sababi, xulosa.

BILIMLAR:
{BILIMLAR}

KATALOG (umatic.uz; dvigatel: model | kVt | ob/min | V | IP | KPD; nasos: model | sarf | napor | kVt | ob/min):
{katalog or "Mijoz parametr yoki tur aytganda mos modellar shu yerda beriladi. Hozircha yo'nalishlarni va turlarni tanishtir."}{chr(10) + chr(10) + "TAFSILOT (mijoz tilga olgan modellar, to'liq texnik ma'lumot):" + chr(10) + tafsilot if tafsilot else ""}"""


def _narx_qoidasi() -> str:
    if NARX_OMBORDAN:
        return (
            "NARX AYTMA - narxni ombor tasdiqlaydi; pozitsiya va miqdor aniq bo'lsa narx_sorash=true qil. "
            f"Yuborilgan taklifdagi raqamlarnigina aytish mumkin. {sotuv.tolov_sharti_matni()}"
        )
    if TAKLIF_REJIMI == "mavjudlik":
        return (
            "NARX AYTMA (hech qanday raqam yoki oraliq). Narxni menejer bildiradi. narx_sorash=true bo'lsa tizim avval "
            "OMBORDA MAVJUDLIGINI tekshiradi, ombor tasdiqlagach mijozga PDF tijorat taklifi yuboriladi - buni qisqa ayt "
            "mijoz tilida, boshqa tildagi so'z aralashtirmasdan."
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
        tur = "mavjudlik" if TAKLIF_REJIMI == "mavjudlik" else "narx"
        qatorlar.append(
            f"- Omborga {tur} so'rovi #{faol['id']} yuborilgan, javob kutilmoqda: "
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
    qatorlar += [f"- {q}" for q in holat.get("qoshimcha", [])]
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
    if db.suhbat_versiyasini_yangilash(SUHBAT_VERSIYASI):
        logging.warning("Suhbat versiyasi yangilandi (%s): eski suhbat tarixi tozalandi, CRM saqlandi.", SUHBAT_VERSIYASI)
    BILIMLAR = bilimlarni_yuklash()
    logging.info("Bilimlar yuklandi: %s belgi | kod versiyasi: %s | AI modellari: %s", len(BILIMLAR), VERSIYA,
                 ", ".join(dict.fromkeys([MODEL] + ZAXIRA_MODELLAR + ASOSIY_ZANJIR)))

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


class YozmoqdaHolati:
    """Javob tayyorlanayotganda mijozga "yozmoqda..." ni uzluksiz ko'rsatib turadi (Telegram uni ~5 s da o'chiradi)."""

    def __init__(self, chat_id: int, bcid: str | None):
        self.chat_id, self.bcid, self._task = chat_id, bcid, None

    async def _loop(self):
        while True:
            try:
                await bot.send_chat_action(chat_id=self.chat_id, action="typing", business_connection_id=self.bcid)
            except Exception:
                pass
            await asyncio.sleep(4)

    async def __aenter__(self):
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc):
        self._task.cancel()


def tabiiy_kutish(matn: str, boshlangan: float) -> float:
    """
    Javob juda tez (robotdek) kelmasligi uchun: kamida ~1,5–3,5 s (matn uzunligiga qarab).
    AI allaqachon shuncha vaqt olgan bo'lsa - qo'shimcha kutilmaydi.
    """
    maqsad = min(TABIIY_MIN + len(matn or "") / 300, TABIIY_MAX)
    return max(0.0, maqsad - (asyncio.get_running_loop().time() - boshlangan))


_RASM_KESH: dict[str, bytes] = {}


async def _rasmni_yuklash(url: str) -> bytes | None:
    """Katalog rasmini yuklab, Telegram uchun JPEG ga o'giradi (sayt webp beradi). Natija keshlanadi."""
    if url in _RASM_KESH:
        return _RASM_KESH[url]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return None
                xom = await resp.read()

        def _jpeg(b: bytes) -> bytes:
            from io import BytesIO
            from PIL import Image
            rasm = Image.open(BytesIO(b)).convert("RGB")
            chiqish = BytesIO()
            rasm.save(chiqish, format="JPEG", quality=88)
            return chiqish.getvalue()

        jpeg = await asyncio.to_thread(_jpeg, xom)
        if len(_RASM_KESH) < 60:
            _RASM_KESH[url] = jpeg
        return jpeg
    except Exception as e:
        logging.warning("Rasmni yuklab bo'lmadi (%s): %s", url, e)
        return None


async def rasm_yuborish(chat_id: int, bcid: str | None, mahsulot: dict, til: str) -> bool:
    """
    Katalogdagi mahsulot rasmini qisqa texnik ma'lumot va sayt havolasi bilan yuboradi.
    Bir necha usul sinaladi, mijoz hech qachon javobsiz qolmaydi:
    1) rasm yuklab olinib JPEG qilib; 2) to'g'ridan-to'g'ri havola orqali (Telegram o'zi yuklaydi);
    3) bo'lmasa - mahsulot sahifasi havolasi matn ko'rinishida.
    """
    izoh = qisqartir(f"{mahsulot['model']}\n{mahsulot.get('_qator', '').split(' | ', 1)[-1]}\n{mahsulot['url']}", 1000)
    usullar = []
    if mahsulot.get("rasm"):
        jpeg = await _rasmni_yuklash(mahsulot["rasm"])
        if jpeg:
            usullar.append(types.BufferedInputFile(jpeg, filename=f"{sotuv.model_kaliti(mahsulot['model'])}.jpg"))
        usullar.append(mahsulot["rasm"])
    for photo in usullar:
        try:
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=izoh, business_connection_id=bcid or None)
            await asyncio.to_thread(db.add_message, chat_id, "assistant", f"[Rasm yuborildi: {mahsulot['model']}]")
            return True
        except TelegramAPIError as e:
            logging.warning("Rasmni yuborib bo'lmadi (chat %s, %s): %s", chat_id, type(photo).__name__, e)
    # Oxirgi chora: rasm sahifasi havolasi (sahifada rasm bor)
    if await mijozga_yuborish(chat_id, bcid, f"🖼 {izoh}") is None:
        await asyncio.to_thread(db.add_message, chat_id, "assistant", f"[Rasm havolasi yuborildi: {mahsulot['model']}]")
        return True
    return False


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
        matn = str(e).lower()
        if not any(k in matn for k in ("json_validate_failed", "response_format", "json_schema", "structured")):
            raise
        logging.info("Model '%s' qat'iy sxemani bajarmadi/qo'llamaydi, oddiy JSON rejimida qayta so'ralmoqda.", model)
        resp = await groq_chat.chat.completions.create(response_format={"type": "json_object"}, **umumiy)
    natija = sotuv.ai_natijasini_ajratish(resp.choices[0].message.content or "")
    if natija is not None and getattr(resp.choices[0], "finish_reason", None) == "length":
        natija["javob"] = sotuv.kesilganni_tozalash(natija["javob"])
    return natija


def _javob_muammolari(natija: dict, til: str, taklif_bor: bool, oldingilar: list[str] = ()) -> list[str]:
    """AI javobini mijozga yuborishdan oldin tekshiradi."""
    muammolar = []
    if not taklif_bor and sotuv.narx_aytilganmi(natija["javob"]):
        muammolar.append("Javobingda narx yoki summa bor. Narx AYTMA - uni faqat ombor beradi.")
    if not sotuv.yozuv_mosmi(natija["javob"], til):
        muammolar.append(f"Javob noto'g'ri tilda. \"javob\" ni FAQAT {TIL_NOMLARI.get(til, til)} tilida yoz.")
    if sotuv.ichki_takrormi(natija["javob"]):
        muammolar.append("Javobingda bir xil so'zlar qayta-qayta takrorlanyapti. Qisqa va aniq yoz, takrorlama.")
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
    # Katalogdan faqat mijoz so'roviga mos qism (token tejash -> limitga kamroq urilish -> tezroq javob)
    mijoz_matni = " ".join(m["content"] for m in tarix if m.get("role") == "user")
    katalog = sotuv.katalog_tanlash(KATALOG, mijoz_matni)
    # Mijoz (yoki bot oxirgi javobida) tilga olingan aniq modellar - to'liq texnik ma'lumot
    oxirgi_xabarlar = " ".join(m["content"] for m in tarix[-3:])
    joriy_matn = tarix[-1]["content"] if tarix and tarix[-1].get("role") == "user" else ""
    tafsilot_modellari = sotuv.topilgan_modellar(KATALOG, joriy_matn, limit=2)
    if holat.get("ishora_modeli") and holat["ishora_modeli"] not in tafsilot_modellari:
        tafsilot_modellari.append(holat["ishora_modeli"])
    tafsilot_modellari += [m for m in sotuv.topilgan_modellar(KATALOG, oxirgi_xabarlar, limit=2)
                           if m not in tafsilot_modellari][: max(0, 2 - len(tafsilot_modellari))]
    # Mijoz aytgan kVt va ob/min ga AYNAN mos modellar dasturda topiladi (AI raqamlarni adashtirmasin)
    mos = sotuv.aniq_mos_modellar(KATALOG, mijoz_matni, limit=2)
    tafsilot_modellari += [m for m in mos if m not in tafsilot_modellari][: max(0, 3 - len(tafsilot_modellari))]
    tafsilot = "\n".join(sotuv.tafsilot_matni(m, til) for m in tafsilot_modellari)
    if mos and not tafsilot_modellari[:1] == mos[:1]:
        holat = {**holat, "qoshimcha": list(holat.get("qoshimcha", [])) + [
            "Mijoz parametrlariga katalogdan AYNAN mos: " + ", ".join(m["model"] for m in mos)
            + ". Model tavsiya qilsang - shularni (TAFSILOTdagi raqamlar bilan) taklif qil."]}
    messages = (
        [{"role": "system", "content": tizim_korsatmasi(katalog, tafsilot)}]
        + tarix
        + [{"role": "system", "content": holat_matni(holat, birinchi, til)}]
    )
    modellar = list(dict.fromkeys([MODEL] + ZAXIRA_MODELLAR + ASOSIY_ZANJIR))
    # Narxli taklif yuborilgan bo'lsagina AI undagi raqamlarni aytishi mumkin
    taklif_bor = holat.get("taklif") is not None and bool(holat["taklif"]["narxlar"])
    oxirgi_xato = None

    oldingilar = [m["content"] for m in tarix if m.get("role") == "assistant"][-2:]

    for urinish in range(2):
        natija, oxirgi_xato, hammasi_limit = await _modellarni_sinash(modellar, messages, til, taklif_bor, oldingilar)
        if natija is not None:
            natija["_birinchi"] = birinchi
            natija["_mos"] = mos
            return natija
        if not hammasi_limit or urinish == 1:
            break
        kutish = _kutish_vaqti(oxirgi_xato)
        logging.warning("Barcha modellar limitda, %.1f soniya kutilmoqda...", kutish)
        await asyncio.sleep(kutish)

    raise oxirgi_xato or RuntimeError("Barcha modellar yaroqsiz javob qaytardi")


def _kutish_vaqti(xato: Exception | None) -> float:
    """
    Groq limit xabaridagi aniq kutish vaqtini oladi ("try again in 6.0s", "in 1m2.5s").
    Topilmasa - LIMIT_KUTISH. Juda uzoq kutilmaydi (mijoz kutib qolmasligi uchun ko'pi bilan 20 s).
    """
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", str(xato or ""))
    if not m:
        return float(LIMIT_KUTISH)
    soniya = int(m.group(1) or 0) * 60 + float(m.group(2))
    return min(max(soniya + 0.5, 2.0), 20.0)


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
            OXIRGI_AI_XATOSI.update(vaqt=datetime.now().strftime("%d.%m %H:%M:%S"), xato=f"{m}: {str(e)[:300]}")
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

async def sheets_holati() -> str:
    """
    Google Sheets webhook HAQIQATAN ishlayaptimi (jadvalga yozmasdan, GET bilan tekshiriladi).
    Apps Script dagi doGet {"ok": true} qaytaradi; 403 - deploy "Anyone" ruxsatisiz yoki o'chirilgan.
    """
    url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not url:
        return "ulanmagan (GOOGLE_SHEET_WEBHOOK_URL yo'q)"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                matn = await resp.text()
                if resp.status == 200 and '"ok":true' in matn.replace(" ", ""):
                    return "ishlayapti ✅"
                if resp.status == 200:
                    return "havola ochiladi, lekin eski skript ⚠️ (google_apps_script.gs ni qayta joylang)"
                if resp.status in (401, 403):
                    return f"❌ {resp.status} ruxsat yo'q — Apps Script'ni «Who has access: Anyone» bilan qayta deploy qiling"
                return f"❌ xato {resp.status}"
    except Exception as e:
        return f"❌ ulanib bo'lmadi: {str(e)[:80]}"


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
    """Mijoz kartochkasini (va bot xotirasini) CSV va Google Sheetsga yuboradi."""
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    if not lead:
        return None
    await csv_yangilash()
    meta = await asyncio.to_thread(db.get_chat_meta, chat_id)
    joriy = await asyncio.to_thread(db.joriy_suhbat_mazmuni, chat_id)
    return await google_sheetsga_yozish({
        "kalit": SHEETS_KALIT,
        "sessiya_soni": meta["sessiya_soni"] if meta else 1,
        "mijoz_ismi": (meta["mijoz_ismi"] or "") if meta else "",
        "oldingi_suhbat": joriy or ((meta["oldingi_suhbat"] or "") if meta else ""),
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


_SHEETS_SINX_VAQTI: dict[int, float] = {}


def xotirani_sinxronlash_fonda(chat_id: int, majburiy: bool = False, oraliq: float = 120.0):
    """Bot xotirasini Sheetsga fonda yuboradi (bir chat uchun ko'pi bilan 2 daqiqada bir marta)."""
    if not os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip():
        return
    hozir = asyncio.get_running_loop().time()
    if not majburiy and hozir - _SHEETS_SINX_VAQTI.get(chat_id, -1e9) < oraliq:
        return
    _SHEETS_SINX_VAQTI[chat_id] = hozir

    async def ish():
        try:
            await crmga_sinxronlash(chat_id)
        except Exception as e:
            logging.warning("Xotirani Sheetsga yozib bo'lmadi (chat %s): %s", chat_id, e)

    asyncio.create_task(ish())


async def sheetsdan_tiklash(chat_id: int, mijoz_id: int) -> bool:
    """
    Bazada yo'q mijozni (Render qayta ishga tushgandan keyin) Google Sheets dan tiklaydi.
    Qaytaradi: tiklandimi. Jadval ulanmagan yoki mijoz topilmasa - False (bot oddiy ishlayveradi).
    """
    url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()
    if not url or not mijoz_id:
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"telegram_id": str(mijoz_id), "kalit": SHEETS_KALIT},
                                   allow_redirects=True, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return False
                data = json.loads(await resp.text())
    except Exception as e:
        logging.warning("Sheetsdan mijozni tiklab bo'lmadi (%s): %s", mijoz_id, e)
        return False
    if not isinstance(data, dict) or not data.get("topildi") or not isinstance(data.get("karta"), dict):
        return False
    k = data["karta"]
    try:
        soni = int(float(k.get("sessiya_soni") or 1))
    except ValueError:
        soni = 1
    # Oxirgi yangilanishdan beri 1 soatdan ko'p o'tgan bo'lsa - bu yangi murojaat
    try:
        oxirgi = datetime.strptime(str(k.get("yangilangan_vaqt", ""))[:16], "%Y-%m-%d %H:%M")
        if (datetime.now() - oxirgi).total_seconds() > SESSIYA_DAQIQA * 60:
            soni += 1
    except ValueError:
        soni += 1
    await asyncio.to_thread(
        db.mijozni_tiklash, chat_id, mijoz_id, soni, k.get("mijoz_ismi", ""), k.get("oldingi_suhbat", ""),
        full_name=k.get("ism", ""), telefon=k.get("telefon", ""), username=k.get("username", ""),
        telegram_id=mijoz_id, tashkilot=k.get("tashkilot", ""), lavozim=k.get("lavozim", ""),
        mavzu=k.get("ehtiyoj", ""), mahsulot=k.get("mahsulot", ""), xulosa=k.get("izoh", ""),
    )
    logging.info("Chat %s: mijoz Google Sheets dan tiklandi (%s-murojaat).", chat_id, soni)
    return True


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
        if OMBOR_ORQALI:
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

async def pdf_yuborish(sorov_id: int, chat_id: int, bcid: str | None, til: str, pozitsiyalar: list[dict],
                      ism: str, kompaniya: str, telefon: str, ega_id: int | None,
                      mavjudlik: list[int] | None = None, izoh_qoshimcha: str = "") -> bool:
    """
    UMATIC shablonidagi PDF tijorat taklifini mijozga yuboradi va nusxasini egalarga yuboradi.
    So'rov holati "yuborildi" bo'ladi. Qaytaradi: mijozga yuborildimi.
    """
    raqam = taklif_pdf.taklif_raqami(sorov_id)
    predmet = tmatn("taklif_predmeti", til).format(soni=len(pozitsiyalar))
    try:
        pdf = await asyncio.to_thread(taklif_pdf.taklif_pdf, sorov_id, til, pozitsiyalar, ism, kompaniya, telefon,
                                      predmet, None, mavjudlik)
    except Exception as e:
        logging.exception("Taklif PDF yaratishda xato: %s", e)
        return False
    fayl_nomi = taklif_pdf.fayl_nomi(sorov_id, til)
    izoh = tmatn("taklif_izoh", til).format(raqam=raqam) + (f"\n{izoh_qoshimcha}" if izoh_qoshimcha else "")
    try:
        await bot.send_document(chat_id=chat_id, document=types.BufferedInputFile(pdf, filename=fayl_nomi),
                                caption=izoh, business_connection_id=bcid or None)
        yuborildi = True
    except TelegramAPIError as e:
        logging.error("Taklif PDF ni mijozga yuborib bo'lmadi (chat %s): %s", chat_id, e)
        yuborildi = False

    lead = await asyncio.to_thread(db.get_lead, chat_id)
    if yuborildi:
        await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, db.FAOL_SOROV_HOLATLARI + ("yuborilmoqda",), "yuborildi")
        await asyncio.to_thread(db.update_sorov, sorov_id, yuborilgan_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        await asyncio.to_thread(db.add_message, chat_id, "assistant", f"[PDF: {raqam}] {izoh}")
        await asyncio.to_thread(db.upsert_lead, chat_id, bosqich=sotuv.bosqichni_birlashtirish(
            lead["bosqich"] if lead else "", "taklif_berildi"))
        sarlavha = f"📄 <b>TIJORAT TAKLIFI {raqam} MIJOZGA YUBORILDI</b>"
        keyingi = "➡️ Mijozga narxni bildiring."
    else:
        sarlavha = f"⚠️ <b>TAKLIF {raqam} MIJOZGA YUBORILMADI</b>"
        keyingi = "➡️ Faylni mijozga o'zingiz yuboring (Telegram Business: mijoz oxirgi 24 soatda yozgan bo'lishi kerak)."

    sheets = await crmga_sinxronlash(chat_id)
    lead = await asyncio.to_thread(db.get_lead, chat_id)
    matn = (lead_kartochkasi(lead, sarlavha) if lead else sarlavha) + f"\n\n{keyingi}\n<i>{_sheets_matni(sheets)}</i>"
    for target in await asyncio.to_thread(hisobot_oluvchilar, ega_id):
        try:
            await bot.send_document(chat_id=target, document=types.BufferedInputFile(pdf, filename=fayl_nomi),
                                    caption=qisqartir(matn, 1000), parse_mode="HTML")
        except Exception as e:
            logging.warning("Taklif nusxasini egaga (%s) yuborib bo'lmadi: %s", target, e)
    return yuborildi


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
    if TAKLIF_REJIMI == "mavjudlik":
        return types.InlineKeyboardMarkup(inline_keyboard=[
            [_tugma("✅ Hammasi bor", f"s:hb:{sorov_id}"), _tugma("✏️ Sonini kiritish", f"s:n:{sorov_id}")],
            [_tugma("❌ Omborda yo'q", f"s:y:{sorov_id}")],
        ])
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        _tugma("💰 Narx kiritish", f"s:n:{sorov_id}"),
        _tugma("❌ Omborda yo'q", f"s:y:{sorov_id}"),
    ]])


def sorov_matni(sorov_id: int, pozitsiyalar: list[dict], lead, til: str, ehtiyoj: str) -> str:
    sarlavha = "📦 <b>MAVJUDLIK SO'ROVI" if TAKLIF_REJIMI == "mavjudlik" else "🆕 <b>NARX SO'ROVI"
    qatorlar = [f"{sarlavha} #{sorov_id}</b>"]
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
    qatorlar.append(
        "\nOmborda bor-yo'qligini belgilang 👇 (tasdiqlagach mijozga PDF taklif ketadi)" if TAKLIF_REJIMI == "mavjudlik"
        else "\nNarx va mavjudlikni kiriting 👇"
    )
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
    if TAKLIF_REJIMI == "mavjudlik":
        qatorlar.append(f"✍️ So'rov #{sorov_id}: SHU XABARGA JAVOB (reply) qilib, har bir pozitsiya uchun omborda NECHTA borligini yozing:\n")
        for i, p in enumerate(pozitsiyalar, 1):
            qatorlar.append(f"{i}) {h(p['nomi'])} — so'ralgan {p['miqdor']} {h(p['birlik'])}")
        qatorlar.append(
            "\nMasalan:\n<code>3</code>\n<code>yo'q</code>  ← omborda yo'q\n"
            "<code>izoh: 2 kunda tayyor bo'ladi</code>  ← ixtiyoriy, mijozga ko'rinadi"
        )
        return "\n".join(qatorlar)
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
        reply_markup=types.ForceReply(selective=True, input_field_placeholder="3" if TAKLIF_REJIMI == "mavjudlik" else "12 500 000 ; 3"),
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

    elif amal == "hb":  # Mavjudlik rejimi: hammasi bor - tasdiqlash uchun ko'rsatish
        if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, db.FAOL_SOROV_HOLATLARI, "tasdiq_kutilmoqda"):
            await callback.answer(f"So'rov #{sorov_id} allaqachon yakunlangan ({sorov['holat']})", show_alert=True)
            return
        narxlar = [{"narx": 0, "mavjud": p["miqdor"]} for p in pozitsiyalar]
        await asyncio.to_thread(db.update_sorov, sorov_id, narxlar=json.dumps(narxlar), ombor_izohi="")
        await _mavjudlik_tasdiq_sorash(callback.message, sorov_id, pozitsiyalar, narxlar)
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

    elif amal == "ok" and TAKLIF_REJIMI == "mavjudlik":  # Ombor tasdiqladi - PDF taklif mijozga
        if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("tasdiq_kutilmoqda",), "yuborilmoqda"):
            await callback.answer("So'rov allaqachon yuborilgan yoki o'zgargan", show_alert=True)
            return
        await callback.answer("Yuborilmoqda...")
        mavjudlar = [n.get("mavjud", 0) for n in json.loads(sorov["narxlar"] or "[]")]
        lead = await asyncio.to_thread(db.get_lead, sorov["chat_id"])
        async with chat_locks[sorov["chat_id"]]:
            if not any(mavjudlar):
                await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("yuborilmoqda",), "yoq")
                xabar = tmatn("hech_yoq", sorov["til"] or "uz_latn")
                if await mijozga_yuborish(sorov["chat_id"], sorov["business_connection_id"], xabar) is None:
                    await asyncio.to_thread(db.add_message, sorov["chat_id"], "assistant", xabar)
                await _sklad_xabarini_belgilash(callback, f"❌ Hech biri omborda yo'q — mijozga xabar berildi ({kim})")
                return
            yuborildi = await pdf_yuborish(
                sorov_id, sorov["chat_id"], sorov["business_connection_id"], sorov["til"] or "uz_latn", pozitsiyalar,
                lead["full_name"] if lead else "", (lead["tashkilot"] or "") if lead else "", (lead["telefon"] or "") if lead else "",
                None, mavjudlik=mavjudlar, izoh_qoshimcha=sorov["ombor_izohi"] or "",
            )
        if yuborildi:
            await _sklad_xabarini_belgilash(callback, f"✅ PDF taklif mijozga yuborildi ({kim})")
        else:
            await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov_id, ("yuborilmoqda",), "tasdiq_kutilmoqda")
            await callback.message.reply("⚠️ Mijozga yuborib bo'lmadi. Keyinroq «✅ Mijozga yuborish» ni qayta bosing yoki mijozga o'zingiz yozing.")

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


async def _mavjudlik_tasdiq_sorash(xabar, sorov_id: int, pozitsiyalar: list[dict], narxlar: list[dict]):
    """Ombor mas'uliga: mijozga yuboriladigan mavjudlikni ko'rsatish va tasdiqlash tugmalari."""
    await xabar.reply(
        f"👀 <b>Tekshiring — so'rov #{sorov_id}</b>\n\n{h(sotuv.mavjudlik_korinishi(pozitsiyalar, narxlar))}\n\n"
        "Tasdiqlasangiz, mijozga PDF tijorat taklifi («Omborda» ustuni bilan) yuboriladi.",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
            _tugma("✅ Mijozga yuborish", f"s:ok:{sorov_id}"),
            _tugma("✏️ Qayta kiritish", f"s:q:{sorov_id}"),
        ]]),
    )


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
        if TAKLIF_REJIMI == "mavjudlik":
            javob = sotuv.ombor_mavjudlik_tahlil(message.text, pozitsiyalar)
        else:
            javob = sotuv.ombor_javobini_tahlil(message.text, pozitsiyalar)
    except ValueError as e:
        await narx_kiritishni_sorash(message.chat.id, sorov, xato=str(e), reply_to=message.message_id)
        return

    if not await asyncio.to_thread(db.sorov_holatini_ozgartirish, sorov["id"], ("narx_kiritilmoqda",), "tasdiq_kutilmoqda"):
        await message.reply("So'rov holati o'zgargan, qayta urinib ko'ring.")
        return

    if TAKLIF_REJIMI == "mavjudlik":
        await asyncio.to_thread(db.update_sorov, sorov["id"], narxlar=json.dumps(javob.narxlar), ombor_izohi=javob.izoh)
        await _mavjudlik_tasdiq_sorash(message, sorov["id"], pozitsiyalar, javob.narxlar)
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
        await asyncio.to_thread(db.taqdimot_belgilash, message.chat.id)
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
    sheets = await sheets_holati()
    await message.answer(
        f"📊 <b>{h(KOMPANIYA_NOMI)} savdo boti statistikasi</b>\n\n"
        f"👥 Mijozlar: <b>{stats['total_leads']}</b>\n"
        f"✅ Buyurtma tasdiqlagan suhbatlar: <b>{stats['completed_chats']}</b>\n"
        f"⏳ Javob kutayotgan narx so'rovlari: <b>{len(db.get_faol_sorovlar())}</b>\n\n"
        f"🏷 Kod versiyasi: <code>{h(VERSIYA)}</code>\n"
        f"🧠 AI modellari: <code>{h(', '.join(dict.fromkeys([MODEL] + ZAXIRA_MODELLAR + ASOSIY_ZANJIR)))}</code>\n"
        f"🔑 Groq kaliti: {'bor ✅' if GROQ_API_KEY else 'YOQ ❌'}\n"
        f"⚠️ Oxirgi AI xatosi: {h(OXIRGI_AI_XATOSI['vaqt'] + ' ' + OXIRGI_AI_XATOSI['xato']) if OXIRGI_AI_XATOSI['xato'] else 'yo`q ✅'}\n"
        f"📚 Bilimlar: {len(BILIMLAR)} belgi\n"
        f"🏬 Ombor chati: <code>{SKLAD_CHAT_ID if SKLAD_CHAT_ID is not None else 'egalar'}</code>\n"
        f"📄 Google Sheets: {sheets}",
        parse_mode="HTML",
    )


@dp.message(Command("bilim"), EgaFilter())
async def bilim_komandasi(message: types.Message):
    global BILIMLAR
    BILIMLAR = bilimlarni_yuklash()  # katalog ham qayta yuklanadi
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
            "2. Pozitsiya va miqdor aniq bo'lgach, ombor chatiga <b>MAVJUDLIK SO'ROVI</b> keladi.\n"
            "3. Ombor mas'uli «✅ Hammasi bor» yoki «✏️ Sonini kiritish» ni bosadi.\n"
            "4. «✅ Mijozga yuborish» bosilgach, mijozga PDF taklif («Omborda» ustuni bilan) ketadi.\n"
            if TAKLIF_REJIMI == "mavjudlik" else
            "2. Pozitsiya va miqdor aniq bo'lgach, ombor chatiga <b>NARX SO'ROVI</b> keladi.\n"
            "3. Ombor mas'uli «💰 Narx kiritish» ni bosib, narx va qoldiqni yozadi.\n"
            "4. Bot jami summa va to'lov shartini o'zi hisoblab ko'rsatadi — «✅ Mijozga yuborish» bosilgach, taklif mijozga ketadi.\n"
            if TAKLIF_REJIMI == "narx" else
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


RASM_MODELI = os.getenv("RASM_MODELI", "qwen/qwen3.8-27b")


async def rasmni_tahlil_qilish(file_id: str) -> str:
    """
    Mijoz yuborgan rasmni ko'radigan model (Groq, Qwen) orqali matnga aylantiradi: nima tasvirlangan va
    shildik/hujjat bo'lsa undagi yozuvlar. Ishlamasa - bo'sh qator (bot baribir javob beradi).
    """
    try:
        fayl = await bot.get_file(file_id)
        if fayl.file_size and fayl.file_size > 10 * 1024 * 1024:
            return ""
        xom = await bot.download_file(fayl.file_path)
        jpeg = await asyncio.to_thread(_jpegga, xom.read() if hasattr(xom, "read") else xom)
        if not jpeg:
            return ""
        resp = await groq_chat.chat.completions.create(
            model=RASM_MODELI,
            temperature=0.1,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": sotuv.RASM_TAHLIL_KORSATMASI},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
            ]}],
            **_model_parametrlari(RASM_MODELI),
        )
        return re.sub(r"\s+", " ", resp.choices[0].message.content or "").strip()[:700]
    except Exception as e:
        logging.warning("Rasmni tahlil qilib bo'lmadi: %s", e)
        return ""


def _jpegga(xom: bytes) -> bytes | None:
    """Rasmni (jpg/png/webp) kichraytirib JPEG ga o'giradi - token va trafik tejaladi."""
    try:
        from PIL import Image
        rasm = Image.open(io.BytesIO(xom)).convert("RGB")
        rasm.thumbnail((1280, 1280))
        chiqish = io.BytesIO()
        rasm.save(chiqish, "JPEG", quality=85)
        return chiqish.getvalue()
    except Exception as e:
        logging.warning("Rasmni JPEG ga o'girib bo'lmadi: %s", e)
        return None


async def xabar_matnini_olish(message: types.Message, is_business: bool) -> str | None:
    """Xabar turini aniqlab matnga aylantiradi (ovoz - Whisper, rasm - ko'ruvchi model, stiker - emoji)."""
    if message.text:
        return message.text.strip()
    if message.sticker:
        emoji = message.sticker.emoji or ""
        return f"[Mijoz stiker yubordi {emoji}]".replace(" ]", "]")
    if message.contact:
        ism = f"{message.contact.first_name or ''} {message.contact.last_name or ''}".strip()
        return f"[Mijoz kontakt ulashdi] Ismi: {ism}, telefon: {message.contact.phone_number}"
    if message.photo or message.document:
        rasmmi = bool(message.photo) or (message.document.mime_type or "").startswith("image/")
        turi = "rasm" if rasmmi else "fayl"
        await mediani_menejerga_yuborish(message, turi)
        caption = f" Izohi: {message.caption.strip()}" if message.caption else ""
        if rasmmi:
            file_id = message.photo[-1].file_id if message.photo else message.document.file_id
            tavsif = await rasmni_tahlil_qilish(file_id)
            if tavsif:
                return f"[Mijoz rasm yubordi. Rasmda (avtomatik tahlil): {tavsif}]{caption}"
        return f"[Mijoz {turi} yubordi (mazmunini o'qib bo'lmadi, u menejerga yuborildi).{caption}]"
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


def iqtibos_matni(message: types.Message) -> str:
    """Mijoz qaysi xabarga javoban yozdi (Telegram "reply" yoki qisman iqtibos) - matni yoki rasm izohi."""
    quote = getattr(message, "quote", None)
    if quote is not None and getattr(quote, "text", None):
        return re.sub(r"\s+", " ", quote.text).strip()[:300]
    javob = getattr(message, "reply_to_message", None)
    if javob is None:
        return ""
    return re.sub(r"\s+", " ", javob.text or javob.caption or "").strip()[:300]


def doimiy_mijoz_korsatmasi(meta, lead, tarix: list[dict]) -> list[str]:
    """Doimiy (qaytib kelgan) mijozni tanish, ism bilan murojaat va kontaktni faqat qarordan keyin so'rash."""
    qatorlar = []
    soni = meta["sessiya_soni"] if meta else 1
    ism = meta["mijoz_ismi"] if meta else ""
    if soni >= 2:
        qatorlar.append(
            f"DOIMIY MIJOZ ({soni}-murojaati). "
            + (f"Ismi: {ism} - unga ismi bilan murojaat qil (tabiiy, har gapda emas)."
               if ism else "Ismi noma'lum: suhbat davomida BIR MARTA xushmuomala so'ra (\"Sizga qanday murojaat qilsam bo'ladi?\").")
            + (f" Oldingi suhbatdan: {meta['oldingi_suhbat'][-700:]}" if meta and meta["oldingi_suhbat"] else "")
            + (f" CRM: qiziqqan - {lead['mahsulot']}; {lead['xulosa'] or ''}" if lead and lead["mahsulot"] else "")
            + " Oldingi qiziqishini kerak bo'lsa eslat, lekin hozirgi savoliga javob ber."
        )
    elif ism:
        qatorlar.append(f"Mijoz ismini aytgan: {ism}.")
    else:
        qatorlar.append("Yangi mijoz: ismini so'rama va o'zi aytmaguncha ism bilan murojaat qilma.")
    telefon_bor = bool(lead and lead["telefon"])
    soralgan = any(m.get("role") == "assistant" and re.search(r"telefon|телефон|raqam|рақам|номер", m["content"], re.IGNORECASE)
                   for m in tarix)
    if telefon_bor or soralgan:
        qatorlar.append("Telefon " + ("ma'lum" if telefon_bor else "allaqachon so'ralgan") + " - qayta so'rama.")
    return qatorlar


async def xabarni_qayta_ishlash(message: types.Message, is_business: bool = True):
    """Mijoz xabarini qayta ishlaydi: AI javobi, CRM, narx so'rovi."""
    chat_id = message.chat.id
    ega_id = None
    bcid = message.business_connection_id if is_business else None

    if is_business and bcid:
        # Botning o'zi business akkaunt nomidan yuborgan xabar ham update bo'lib qaytadi -
        # uni menejer yozgan deb hisoblamaslik kerak (aks holda bot o'zini pauzaga qo'yib qo'yadi)
        if message.sender_business_bot is not None:
            return
        ega_id = await ega_id_ol(bcid)
        # Menejer (akkaunt egasi) o'zi yozsa - FAQAT shu chatda bot pauza qiladi (boshqa chatlarda ishlayveradi).
        # Pauza menejerning OXIRGI xabaridan EGA_PAUZA_DAQIQA o'tgach o'zi tugaydi.
        if message.from_user is None or message.from_user.id == ega_id:
            await asyncio.to_thread(db.record_owner_activity, chat_id)
            # Menejer yozganlari bot xotirasiga - pauzadan keyin bot suhbatni davom ettira olsin
            if message.text and not message.text.startswith("/"):
                await asyncio.to_thread(db.add_message, chat_id, "assistant", f"(Menejer yozdi) {message.text.strip()}")
            return
        if await asyncio.to_thread(db.is_owner_recently_active, chat_id, EGA_PAUZA_DAQIQA):
            logging.info("Chat %s da menejer faol (pauza %s daqiqa), bot aralashmaydi.", chat_id, EGA_PAUZA_DAQIQA)
            # Mijoz yozganlari ham xotiraga - pauzadan keyin bot kontekstni bilsin
            if message.text and message.text.strip():
                await asyncio.to_thread(db.add_message, chat_id, "user", message.text.strip())
            return

    if message.from_user is None:
        return

    xabar_matni = await xabar_matnini_olish(message, is_business)
    if not xabar_matni:
        return

    async with chat_locks[chat_id]:
        if await asyncio.to_thread(db.get_chat_meta, chat_id) is None:
            await sheetsdan_tiklash(chat_id, message.from_user.id)
        oxirgi_vaqt = await asyncio.to_thread(db.get_last_message_time, chat_id)
        if oxirgi_vaqt and (datetime.now() - oxirgi_vaqt).total_seconds() > SESSIYA_DAQIQA * 60:
            logging.info("Chat %s: %s daqiqadan ko'p jimlik - yangi suhbat boshlanadi.", chat_id, SESSIYA_DAQIQA)
            await asyncio.to_thread(db.clear_chat_history, chat_id)
            xotirani_sinxronlash_fonda(chat_id, majburiy=True)

        tarix = await asyncio.to_thread(db.get_chat_history, chat_id, MAX_TARIX)
        boshlangan = asyncio.get_running_loop().time()

        # Mijoz tilini dastur aniqlaydi (AI ga ishonib qolinmaydi): javob va taklif shu tilda bo'ladi
        meta = await asyncio.to_thread(db.get_chat_meta, chat_id)
        sorangan_til = sotuv.til_sorovi(xabar_matni)
        if sorangan_til:
            # Mijoz tilni o'zi tanladi - keyingi xabarlarda ham shu tilda (u boshqa tilda yozsa ham)
            await asyncio.to_thread(db.til_tanlovini_saqlash, chat_id, sorangan_til)
            til = sorangan_til
        elif meta and meta["til_tanlov"]:
            til = meta["til_tanlov"]
        else:
            til = sotuv.tilni_aniqlash(xabar_matni, meta["til"] if meta else "")

        # Mijoz bot xabariga (masalan, model rasmiga) javoban yozgan bo'lsa - o'sha xabar ham kontekstga kiradi
        iqtibos = iqtibos_matni(message)
        tarix_matni = f"{xabar_matni}\n[Mijoz shu xabarga javoban yozdi: «{iqtibos}»]" if iqtibos else xabar_matni
        await asyncio.to_thread(db.add_message, chat_id, "user", tarix_matni)
        await asyncio.to_thread(db.save_chat_meta, chat_id, message.from_user.id, bcid, til)
        tarix.append({"role": "user", "content": tarix_matni})
        lead = await asyncio.to_thread(db.get_lead, chat_id)
        doimiy = bool(meta and meta["sessiya_soni"] >= 2)

        # Bot bu chatda birinchi marta javob beryapti: AI dan oldin O'ZINI TANISHTIRADI.
        # Menejer (Zuxriddin) shu odam bilan oxirgi 24 soatda yozishgan bo'lsa - qisqa tanishtiruv
        # (tirik suhbat o'rtasiga uzun e'lon tushmasligi uchun), aks holda to'liq taqdimot.
        taqdimot_hozir = False
        if not await asyncio.to_thread(db.taqdimot_yuborilganmi, chat_id):
            menejer_yozishgan = await asyncio.to_thread(db.is_owner_recently_active, chat_id, 24 * 60)
            if doimiy:
                # Qaytib kelgan mijoz: uzun taqdimot o'rniga - ismi va oldingi qiziqishi bilan qisqa salom
                ism = meta["mijoz_ismi"] or ""
                mahsulot = sotuv.mahsulot_qisqa(lead["mahsulot"]) if lead and lead["mahsulot"] else ""
                tanishtiruv = tmatn("qaytish", til).format(
                    ism=f", {ism}" if ism else "",
                    oldingi=tmatn("qaytish_oldingi", til).format(mahsulot=mahsulot) if mahsulot else "",
                )
            else:
                tanishtiruv = tmatn("qisqa_tanishtiruv", til) if menejer_yozishgan else tanishtiruv_matni(til)
            async with YozmoqdaHolati(chat_id, bcid):
                await asyncio.sleep(tabiiy_kutish(tanishtiruv, boshlangan))
            if await mijozga_yuborish(chat_id, bcid, tanishtiruv) is None:
                await asyncio.to_thread(db.taqdimot_belgilash, chat_id)
                await asyncio.to_thread(db.add_message, chat_id, "assistant", TAQDIMOT_BELGISI)
                tarix.append({"role": "assistant", "content": TAQDIMOT_BELGISI})
                taqdimot_hozir = True
                # Faqat salom yozgan bo'lsa - taqdimot yetarli, AI chaqirilmaydi (savol taqdimot oxirida bor)
                if sotuv.faqat_salommi(xabar_matni):
                    return

        holat = await asyncio.to_thread(suhbat_holati, chat_id)
        boshlangan = asyncio.get_running_loop().time()
        holat["qoshimcha"] = doimiy_mijoz_korsatmasi(meta, lead, tarix)
        # "bu motor haqida" - qaysi model ekanini dastur aniqlaydi (bot qayta so'rab o'tirmasin)
        if not sotuv.topilgan_modellar(KATALOG, tarix_matni, limit=1) and sotuv.ishora_bormi(xabar_matni):
            ishora = sotuv.oxirgi_korsatilgan_model(KATALOG, tarix[:-1])
            if ishora is None and meta and (meta["oldingi_suhbat"] or (lead and lead["mahsulot"])):
                oldingi = [{"role": "assistant", "content": (meta["oldingi_suhbat"] or "") + " " +
                            ((lead["mahsulot"] or "") if lead else "")}]
                ishora = sotuv.oxirgi_korsatilgan_model(KATALOG, oldingi)
            if ishora:
                holat["ishora_modeli"] = ishora
                holat["qoshimcha"].append(
                    f"Mijoz \"bu/shu\" deb oxirgi ko'rsatilgan {ishora['model']} ni nazarda tutyapti - aynan shu model "
                    "haqida TAFSILOT asosida to'liq javob ber, \"qaysi model?\" deb so'rama."
                )

        # Mijoz rasm so'radimi? Model shu xabarda yoki botning oxirgi javobida bo'lsa - katalog rasmi yuboriladi
        rasm_soraldi = sotuv.rasm_soraldimi(xabar_matni)
        rasm_modellari = []
        if rasm_soraldi:
            suhbat_matni = " ".join(m["content"] for m in tarix[-6:-1])
            joriy_rasm = tarix_matni + (" " + holat["ishora_modeli"]["model"] if holat.get("ishora_modeli") else "")
            rasm_modellari = sotuv.rasm_uchun_mahsulotlar(KATALOG, joriy_rasm, suhbat_matni)
            holat["qoshimcha"] += [
                f"Javobingdan keyin mijozga quyidagi mahsulotlar RASMI avtomatik yuboriladi: "
                f"{', '.join(m['model'] for m in rasm_modellari)}. Qisqa ayt (masalan: mana rasmi), "
                "\"rasm yo'q\" yoki \"rasm yubora olmayman\" DEMA."
            ]

        try:
            async with YozmoqdaHolati(chat_id, bcid):
                natija = await ai_javob(tarix, holat, til)
        except Exception as xato:
            logging.error("AI javob bera olmadi (chat %s): %s", chat_id, xato)
            OXIRGI_AI_XATOSI.update(vaqt=datetime.now().strftime("%d.%m %H:%M:%S"), xato=str(xato)[:300])
            # Menejerga yo'naltirish o'rniga foydali javob: mos katalog modellari yoki kerakli parametrlar
            mijoz_matni = " ".join(m["content"] for m in tarix if m.get("role") == "user")
            zaxira = sotuv.zaxira_javob(til, sotuv.katalog_tanlash(KATALOG, mijoz_matni))
            if await mijozga_yuborish(chat_id, bcid, zaxira) is None:
                await asyncio.to_thread(db.add_message, chat_id, "assistant", zaxira)
            if await asyncio.to_thread(db.menejer_chaqirish_mumkinmi, chat_id, 30):
                u = message.from_user
                await egalarga_yuborish(
                    "⚠️ <b>AI javob bera olmadi</b> (limit yoki xato). Mijozga avtomatik javob yuborildi.\n"
                    f"Xato: <code>{h(qisqartir(str(xato), 200))}</code>\n\n"
                    f"👤 {mijoz_havolasi(u.id, u.full_name, f'@{u.username}' if u.username else '')}\n"
                    f"💬 {h(qisqartir(xabar_matni, 400))}\n🆔 Chat: <code>{chat_id}</code>",
                    ega_id,
                )
            return

        javob = re.sub(r"^\s*\(Menejer yozdi\)\s*", "", natija["javob"])
        javob = sotuv.atamalarni_tuzatish(sotuv.model_nomlarini_tuzatish(javob, KATALOG))
        javob = sotuv.havolalarni_tuzatish(javob, KATALOG)
        # Katalogga zid raqam, yo'q model yoki kafolat/yetkazish va'dasi - mijozga bormaydi
        mijoz_matni = " ".join(m["content"] for m in tarix if m.get("role") == "user")
        tasdiqlangan = holat.get("taklif") is not None
        tozalangan = sotuv.faktlarni_tozalash(javob, KATALOG, mijoz_matni, til, natija.get("_mos") or [], tasdiqlangan)
        if tozalangan != javob:
            logging.warning("Chat %s: AI javobida tasdiqlanmagan fakt olib tashlandi: %s", chat_id,
                            sotuv.fakt_xatolari(javob, KATALOG, mijoz_matni, tasdiqlangan))
            javob = tozalangan or tmatn("narx_aniqlanadi", til)
        for poz in natija["mahsulotlar"]:  # PDF va CRM ga ham to'g'ri nom
            poz["nomi"] = sotuv.model_nomlarini_tuzatish(poz["nomi"], KATALOG)
            poz["parametrlar"] = sotuv.model_nomlarini_tuzatish(poz["parametrlar"], KATALOG)
        javob = sotuv.salomni_moslash(javob, natija["_birinchi"], til)
        if taqdimot_hozir and sotuv.taqdimotni_takrorlaydimi(javob, tanishtiruv_matni(til)) and not natija["narx_sorash"]:
            logging.info("AI javobi taqdimotni takrorlaydi - yuborilmadi (chat %s).", chat_id)
            await crm_yangilash_xavfsiz(chat_id, message.from_user, natija, holat, xabar_matni, bcid, ega_id)
            return

        # "Menejer siz bilan bog'lanadi" har javobda takrorlanmasin (narx/mavjudlik so'ralgandagina)
        oldin_menejer = any(m["role"] == "assistant" and sotuv.menejer_aytilganmi(m["content"]) for m in tarix[:-1])
        javob = sotuv.takroriy_menejerni_olib_tashlash(javob, oldin_menejer, sotuv.narx_savolimi(xabar_matni))

        # AI qo'shimcha parametr so'rab turib qolsa ham: asosiy ma'lumot yetarli bo'lsa - narx so'rovi yuboriladi
        if not natija["narx_sorash"] and sotuv.narx_sorash_mumkinmi(natija["mahsulotlar"]):
            kalit = sotuv.mahsulotlar_kaliti(natija["mahsulotlar"])
            if kalit not in [r["kalit"] for r in (holat.get("faol"), holat.get("taklif")) if r]:
                natija["narx_sorash"] = True
                kalit_matn = {"narx": "kutish", "mavjudlik": "mavjudlik_tekshirilmoqda"}.get(TAKLIF_REJIMI, "taklif_tayyorlanmoqda")
                javob = f"{javob}\n\n{tmatn(kalit_matn, til)}"
        # Ism/telefon bir marta so'raladi - AI ko'rsatmaga qaramay qayta so'rasa, o'sha gap olib tashlanadi
        kontakt_soralgan = (bool(lead and lead["telefon"]) or any(
            m["role"] == "assistant" and re.search(r"telefon|телефон|номер", m["content"], re.IGNORECASE) for m in tarix[:-1]))
        javob = sotuv.kontakt_takrorini_olib_tashlash(javob, kontakt_soralgan, til)
        # Suhbatda allaqachon minnatdorchilik bildirilgan bo'lsa - har javobda "Rahmat" takrorlanmaydi
        oldin_rahmat = any(m["role"] == "assistant" and sotuv.rahmat_aytilganmi(m["content"]) for m in tarix)
        javob = sotuv.takroriy_rahmatni_olib_tashlash(javob, oldin_rahmat, natija["mijoz"]["ism"])

        if len(javob) > 600:  # uzun javob model limitida o'rtada uzilib qolgan bo'lishi mumkin
            javob = sotuv.kesilganni_tozalash(javob)
        kutish = tabiiy_kutish(javob, boshlangan)
        if kutish:
            async with YozmoqdaHolati(chat_id, bcid):
                await asyncio.sleep(kutish)
        xato = await mijozga_yuborish(chat_id, bcid, javob)
        if xato:
            return
        await asyncio.to_thread(db.add_message, chat_id, "assistant", javob)
        for m in rasm_modellari:
            await rasm_yuborish(chat_id, bcid, m, til)

        await crm_yangilash_xavfsiz(chat_id, message.from_user, natija, holat, xabar_matni, bcid, ega_id)


async def crm_yangilash_xavfsiz(chat_id, mijoz, natija, holat, xabar_matni, bcid, ega_id):
    yangi_ism = False
    if sotuv.ism_togrimi(natija["mijoz"]["ism"]):
        try:
            meta = await asyncio.to_thread(db.get_chat_meta, chat_id)
            yangi_ism = not meta or meta["mijoz_ismi"] != natija["mijoz"]["ism"].strip()[:60]
            await asyncio.to_thread(db.mijoz_ismini_saqlash, chat_id, natija["mijoz"]["ism"])
        except Exception as e:
            logging.warning("Mijoz ismini saqlab bo'lmadi (chat %s): %s", chat_id, e)
    try:
        await crm_yangilash(chat_id, mijoz, natija, holat, xabar_matni, bcid, ega_id)
    except Exception as e:
        logging.exception("CRM yangilashda xatolik (chat %s): %s", chat_id, e)
    # Bot xotirasi (suhbat mazmuni, ism) Sheetsda ham bo'lsin - Render qayta ishga tushsa ham saqlanadi
    xotirani_sinxronlash_fonda(chat_id, majburiy=yangi_ism)


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
        matn = f"⏰ <b>So'rov #{s['id']}</b> ga {SKLAD_ESLATMA_DAQIQA} daqiqadan beri javob berilmadi — mijoz kutmoqda!"
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


async def suhbat_yakunlarini_yuborish():
    """
    Mijoz SUHBAT_YAKUNI_DAQIQA davomida yozmasa - suhbat tugagan: egaga odatdagi mijoz kartochkasi
    (kim, telefon, ehtiyoj, mahsulot, bosqich, xulosa) yuboriladi. Har bir yozishma uchun bir marta.
    """
    for r in await asyncio.to_thread(db.get_yakunlangan_suhbatlar, SUHBAT_YAKUNI_DAQIQA):
        await asyncio.to_thread(db.yakun_xabarini_belgilash, r["chat_id"])
        # Menejer o'zi suhbatni olib borgan bo'lsa (pauza) - u allaqachon xabardor
        if r["owner_last_active"] and r["owner_last_active"] >= r["oxirgi"]:
            continue
        lead = await asyncio.to_thread(db.get_lead, r["chat_id"])
        if lead:
            kartochka = lead_kartochkasi(lead, "💬 <b>SUHBAT YAKUNLANDI</b>")
        else:
            mijoz_id = r["mijoz_id"] or r["chat_id"]
            kartochka = (f"💬 <b>SUHBAT YAKUNLANDI</b>\n\n👤 <b>Mijoz:</b> {mijoz_havolasi(mijoz_id, 'Mijoz')}"
                         "\n📊 Ehtiyoj hali aniqlanmagan")
        # Ega biznes ulanishdan aniqlanadi - bot qayta ishga tushib, egalar ro'yxati bo'sh bo'lsa ham yetib boradi
        ega_id = None
        if r["business_connection_id"]:
            try:
                ega_id = await ega_id_ol(r["business_connection_id"])
            except Exception as e:
                logging.warning("Biznes ulanish egasini aniqlab bo'lmadi (chat %s): %s", r["chat_id"], e)
        await egalarga_yuborish(
            kartochka
            + f"\n\n🗨 Suhbatda {r['mijoz_xabarlari']} ta mijoz xabari"
            + (f"\n💬 <b>Oxirgi xabari:</b> {h(qisqartir(r['oxirgi_mijoz_xabari'] or '', 300))}"
               if r["oxirgi_mijoz_xabari"] else "")
            + f"\n🆔 Chat: <code>{r['chat_id']}</code>",
            ega_id,
        )


async def fon_loop():
    """Har daqiqada suhbat yakunlari, har FON_TEKSHIRUV_ORALIQ da ombor/taklif eslatmalari."""
    otgan = 0
    while True:
        await asyncio.sleep(60)
        otgan += 60
        try:
            await suhbat_yakunlarini_yuborish()
        except Exception as e:
            logging.exception("Suhbat yakunini yuborishda xatolik: %s", e)
        if otgan >= FON_TEKSHIRUV_ORALIQ:
            otgan = 0
            try:
                await fon_tekshiruvlari()
            except Exception as e:
                logging.exception("Fon tekshiruvida xatolik: %s", e)


# =====================================================================
#  RENDER CLOUD UCHUN HEALTH CHECK WEB SERVER VA ISHGA TUSHIRISH
# =====================================================================

async def handle_ping(request):
    return web.json_response({"status": "online", "service": f"{KOMPANIYA_NOMI} savdo boti", "versiya": VERSIYA})


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

    # Bot profili tavsifi + serverdagi kod versiyasi (Render'ga kirmasdan Telegram API orqali tekshirish mumkin)
    try:
        await bot.set_my_short_description(
            short_description=f"{KOMPANIYA_NOMI} AI savdo yordamchisi: elektr dvigatellar, nasoslar, izolyatsiya materiallari"
        )
        await bot.set_my_description(
            description=(
                f"{KOMPANIYA_NOMI} AI savdo yordamchisi. Elektr dvigatellar, nasos agregatlari va elektroizolyatsiya "
                f"materiallarini tanlashda yordam beradi, texnik ma'lumot va rasm yuboradi.\n\nversiya: {VERSIYA}"
            )
        )
    except Exception as e:
        logging.warning("Bot tavsifini yangilab bo'lmadi: %s", e)

    logging.info("%s savdo boti ishga tushdi (versiya %s)! To'xtatish uchun: Ctrl + C", KOMPANIYA_NOMI, VERSIYA)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for v in vazifalar:
            v.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
