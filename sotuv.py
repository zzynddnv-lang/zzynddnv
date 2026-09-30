"""
SOTUV MANTIQ MODULI (Telegram va AI ga bog'liq emas - to'liq testlanadi).

Bu yerda xato qilish mumkin bo'lmagan hamma narsa DASTUR orqali hisoblanadi, AI orqali emas:
- AI javobini (JSON) tekshirish va tozalash
- Ombor mas'uli yozgan narxlarni tahlil qilish
- Jami summa va to'lov shartlarini hisoblash
- Mijozga yuboriladigan tijorat taklifi matni (3 tilda)
"""

import json
import os
import re
from dataclasses import dataclass, field

# =====================================================================
#  SOZLAMALAR
# =====================================================================

KOMPANIYA_NOMI = os.getenv("KOMPANIYA_NOMI", "UMATIC")
# Summa shu chegaradan OSHSA - qisman oldindan to'lov (so'm)
KATTA_BUYURTMA_CHEGARASI = int(os.getenv("KATTA_BUYURTMA_CHEGARASI", "100000000"))
OLDINDAN_TOLOV_FOIZI = int(os.getenv("OLDINDAN_TOLOV_FOIZI", "50"))
TAKLIF_MUDDATI_KUN = int(os.getenv("TAKLIF_MUDDATI_KUN", "3"))
# Narx haqida izoh, masalan: "QQS bilan". Bo'sh bo'lsa ko'rsatilmaydi.
NARX_IZOHI = os.getenv("NARX_IZOHI", "").strip()

TILLAR = ("uz_latn", "uz_cyrl", "ru")
BOSQICHLAR = (
    "yangi", "qiziqish", "ehtiyoj_aniqlanmoqda", "narx_sorovi",
    "taklif_berildi", "muzokara", "kelishildi", "rad_etdi",
)
HARORATLAR = ("sovuq", "iliq", "issiq")
MAX_POZITSIYA = 15
MIN_NARX = 1000  # so'm; bundan kichik narx - xato kiritilgan deb hisoblanadi


# =====================================================================
#  AI JAVOB SXEMASI (Groq Structured Outputs, strict)
# =====================================================================

def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


JAVOB_SXEMASI = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "javob", "til", "mijoz", "ehtiyoj", "mahsulotlar", "narx_sorash",
        "buyurtma_tasdiqlandi", "bosqich", "harorat", "menejer_kerak", "menejer_sababi", "xulosa",
    ],
    "properties": {
        "javob": _str("Mijozga yuboriladigan xabar matni (mijoz tilida)"),
        "til": {"type": "string", "enum": list(TILLAR), "description": "Mijoz yozayotgan til"},
        "mijoz": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ism", "telefon", "kompaniya", "lavozim", "soha"],
            "properties": {
                "ism": _str("Mijoz o'zi aytgan ismi, aytilmagan bo'lsa bo'sh"),
                "telefon": _str("Mijoz yozgan telefon raqami, bo'lmasa bo'sh"),
                "kompaniya": _str("Kompaniya / tashkilot nomi, bo'lmasa bo'sh"),
                "lavozim": _str("Lavozimi (bosh muhandis, xarid bo'limi...), bo'lmasa bo'sh"),
                "soha": _str("Faoliyat sohasi, bo'lmasa bo'sh"),
            },
        },
        "ehtiyoj": _str("Mijoz ehtiyoji va muammosi qisqacha"),
        "mahsulotlar": {
            "type": "array",
            "description": "Mijoz so'rayotgan aniq pozitsiyalar (butun suhbat bo'yicha, eng so'nggi holati)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["nomi", "parametrlar", "miqdor", "birlik"],
                "properties": {
                    "nomi": _str("Mahsulot nomi/turi"),
                    "parametrlar": _str("Texnik parametrlar: kVt, ob/min, V, o'rnatish, IP, sarf, napor..."),
                    "miqdor": {"type": "integer", "description": "Soni; noma'lum bo'lsa 0"},
                    "birlik": _str("dona, metr, kg, komplekt"),
                },
            },
        },
        "narx_sorash": {"type": "boolean", "description": "Pozitsiya va miqdor aniq, mijoz narx/taklif kutmoqda"},
        "buyurtma_tasdiqlandi": {"type": "boolean", "description": "Mijoz taklifni qabul qilib, buyurtmani aniq tasdiqladi"},
        "bosqich": {"type": "string", "enum": list(BOSQICHLAR)},
        "harorat": {"type": "string", "enum": list(HARORATLAR), "description": "Mijozning sotib olishga tayyorligi"},
        "menejer_kerak": {"type": "boolean", "description": "Jonli menejer aralashuvi kerak"},
        "menejer_sababi": _str("Nega menejer kerak (chegirma, murakkab texnik savol, shikoyat, qo'ng'iroq so'radi)"),
        "xulosa": _str("CRM uchun suhbat xulosasi, 1-2 gap"),
    },
}


# =====================================================================
#  AI JAVOBINI TEKSHIRISH
# =====================================================================

def _butun_son(qiymat) -> int:
    if isinstance(qiymat, bool):
        return 0
    if isinstance(qiymat, (int, float)):
        return max(0, int(qiymat))
    m = re.search(r"\d+", str(qiymat or ""))
    return int(m.group(0)) if m else 0


_BIRLIKLAR = {
    "штука": "шт", "штуки": "шт", "штук": "шт", "шт.": "шт", "штуку": "шт",
    "дона": "дона", "ta": "dona", "та": "дона", "donа": "dona",
    "комплект": "компл.", "комплекта": "компл.", "комплектов": "компл.",
}


def _birlikni_tozalash(birlik) -> str:
    """AI yozgan birlikni bir xil ko'rinishga keltiradi: '2 штука' -> '2 шт'."""
    b = str(birlik or "").strip()
    return _BIRLIKLAR.get(b.lower(), b)[:20] or "dona"


def mahsulotlarni_tozalash(royxat) -> list[dict]:
    """AI qaytargan pozitsiyalarni tekshiradi: bo'sh nomlilarini tashlaydi, miqdorni butun songa keltiradi."""
    natija = []
    if not isinstance(royxat, list):
        return natija
    for p in royxat[:MAX_POZITSIYA]:
        if not isinstance(p, dict):
            continue
        nomi = str(p.get("nomi") or "").strip()
        if not nomi:
            continue
        natija.append({
            "nomi": nomi[:200],
            "parametrlar": str(p.get("parametrlar") or "").strip()[:300],
            "miqdor": _butun_son(p.get("miqdor")),
            "birlik": _birlikni_tozalash(p.get("birlik")),
        })
    return natija


def narx_sorash_mumkinmi(royxat: list[dict]) -> bool:
    """
    Omborga narx so'rovi yuborish uchun yetarli ma'lumot bormi? Har bir pozitsiyada miqdor va
    kamida 2 ta texnik raqam (masalan kVt + ob/min yoki sarf + napor) bo'lishi kerak.
    AI ikkinchi darajali parametrni so'rab turib qolsa ham, so'rov kechikmasligi uchun.
    """
    return bool(royxat) and all(
        p["miqdor"] > 0 and len(re.findall(r"\d+(?:[.,]\d+)?", p["parametrlar"])) >= 2 for p in royxat
    )


def mahsulotlar_kaliti(royxat: list[dict]) -> str:
    """Ikki so'rov bir xil pozitsiyalardan iboratligini solishtirish uchun kalit."""
    return json.dumps(
        sorted((p["nomi"].lower(), p["parametrlar"].lower(), p["miqdor"], p["birlik"].lower()) for p in royxat),
        ensure_ascii=False,
    )


def _ichidan_javobni_olish(matn: str) -> str:
    """Buzilgan JSON ichidan "javob" maydonini ajratib olishga urinish."""
    m = re.search(r'"javob"\s*:\s*"((?:[^"\\]|\\.)*)"', matn, re.DOTALL)
    if not m:
        return ""
    try:
        return json.loads(f'"{m.group(1)}"')
    except ValueError:
        return m.group(1)


def ai_natijasini_ajratish(matn: str) -> dict | None:
    """
    AI javobini (JSON) tekshiradi va barcha maydonlarni to'g'ri turga keltiradi.
    Mijozga hech qachon xom JSON yuborilmasligi kafolatlanadi: yaroqsiz bo'lsa None.
    """
    matn = re.sub(r"<think>.*?</think>", "", matn or "", flags=re.DOTALL | re.IGNORECASE).strip()
    matn = re.sub(r"^```(?:json)?|```$", "", matn).strip()

    data = None
    json_match = re.search(r"\{.*\}", matn, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
        except ValueError:
            data = None

    if not isinstance(data, dict):
        javob = _ichidan_javobni_olish(matn)
        if not javob:
            return None
        data = {"javob": javob}

    javob = str(data.get("javob") or "").strip()
    if not javob or javob.startswith("{"):
        return None

    mijoz = data.get("mijoz") if isinstance(data.get("mijoz"), dict) else {}
    til = data.get("til") if data.get("til") in TILLAR else ""
    bosqich = data.get("bosqich") if data.get("bosqich") in BOSQICHLAR else ""
    harorat = data.get("harorat") if data.get("harorat") in HARORATLAR else ""

    return {
        "javob": javob,
        "til": til,
        "mijoz": {k: str(mijoz.get(k) or "").strip()[:150] for k in ("ism", "telefon", "kompaniya", "lavozim", "soha")},
        "ehtiyoj": str(data.get("ehtiyoj") or "").strip()[:500],
        "mahsulotlar": mahsulotlarni_tozalash(data.get("mahsulotlar")),
        "narx_sorash": data.get("narx_sorash") is True,
        "buyurtma_tasdiqlandi": data.get("buyurtma_tasdiqlandi") is True,
        "bosqich": bosqich,
        "harorat": harorat,
        "menejer_kerak": data.get("menejer_kerak") is True,
        "menejer_sababi": str(data.get("menejer_sababi") or "").strip()[:300],
        "xulosa": str(data.get("xulosa") or "").strip()[:600],
    }


def bosqichni_birlashtirish(eski: str, yangi: str) -> str:
    """Sotuv bosqichi orqaga ketmasligi uchun (kelishildi / rad_etdi har doim ustun)."""
    if yangi in ("kelishildi", "rad_etdi") or not eski or eski not in BOSQICHLAR:
        return yangi or eski
    if not yangi:
        return eski
    return yangi if BOSQICHLAR.index(yangi) >= BOSQICHLAR.index(eski) else eski


# =====================================================================
#  TILNI ANIQLASH
# =====================================================================

_UZ_KIRILL_HARFLAR = set("ўқғҳЎҚҒҲ")
_UZ_KIRILL_SOZLAR = (
    "ассалому", "салом", "керак", "борми", "нархи", "канча", "қанча", "ака", "рахмат", "раҳмат",
    "йук", "йўқ", "бор ", "булади", "бўлади", "качон", "қачон", "тулов", "тўлов", "яхши", "хоп",
)


def _harf_sonlari(matn: str) -> tuple[int, int]:
    """(kirill harflar soni, lotin harflar soni)."""
    kirill = sum(1 for c in matn if "Ѐ" <= c <= "ӿ")
    lotin = sum(1 for c in matn if c.isascii() and c.isalpha())
    return kirill, lotin


def tilni_aniqlash(matn: str, oldingi: str = "") -> str:
    """
    Matn yozilgan tilni aniqlaydi: uz_latn, uz_cyrl yoki ru.
    Matnda harf juda kam bo'lsa ("ok", "5", emoji) - oldingi aniqlangan til qoldiriladi.
    """
    matn = matn or ""
    kirill, lotin = _harf_sonlari(matn)
    if kirill + lotin < 3 and oldingi in TILLAR:
        return oldingi
    if kirill <= lotin:
        return "uz_latn"
    past = matn.lower()
    if any(c in _UZ_KIRILL_HARFLAR for c in matn) or any(s in past for s in _UZ_KIRILL_SOZLAR):
        return "uz_cyrl"
    if oldingi == "uz_cyrl" and kirill < 15:
        return "uz_cyrl"  # qisqa kirill xabar ("хоп", "ок") - avvalgi o'zbek kirill davom etadi
    return "ru"


# Texnik belgilar (kVt, V, IP55, UMATIC...) yozuvni aniqlashga xalaqit bermasligi uchun olib tashlanadi
_TEXNIK_REGEX = re.compile(r"\b(?:[A-Z]{2,}\w*|k?[VW]t?|kVt|IP\d*|Ex|m³|ob/min|STIR|INN)\b")


def yozuv_mosmi(javob: str, til: str) -> bool:
    """Javob kutilgan yozuvda (lotin yoki kirill) yozilganini tekshiradi."""
    kirill, lotin = _harf_sonlari(_TEXNIK_REGEX.sub(" ", javob or ""))
    if kirill + lotin < 10:
        return True
    if til == "uz_latn":
        return lotin >= kirill * 2
    return kirill >= lotin * 2


# =====================================================================
#  NARX HAQIDA O'YLAB TOPISHDAN HIMOYA
# =====================================================================

_NARX_REGEX = re.compile(
    r"\d[\d\s.,]*\s*(so['‘’`]?m|сўм|сум|sum\b|uzs|\$|usd|dollar|доллар|mln|млн|million|миллион|ming\b|минг|тыс)",
    re.IGNORECASE,
)


def _chegara_variantlari() -> list[str]:
    mln = KATTA_BUYURTMA_CHEGARASI // 1_000_000
    return [
        rf"{mln}\s*(mln|млн|million|миллион)",
        rf"{son_format(KATTA_BUYURTMA_CHEGARASI).replace(' ', r'[\s.,]?')}",
    ]


def narx_aytilganmi(javob: str) -> bool:
    """
    AI javobida narx/summa bormi? (To'lov sharti chegarasi - masalan "100 mln" - hisobga olinmaydi.)
    Taklif hali yuborilmagan bo'lsa, AI narx aytishi taqiqlanadi - narxni faqat ombor beradi.
    """
    tekshiriladigan = javob or ""
    for variant in _chegara_variantlari():
        tekshiriladigan = re.sub(variant, " ", tekshiriladigan, flags=re.IGNORECASE)
    return bool(_NARX_REGEX.search(tekshiriladigan))


# =====================================================================
#  OMBOR MAS'ULI YOZGAN NARXLARNI TAHLIL QILISH
# =====================================================================

_KOPAYTIRUVCHILAR = {
    "mln": 1_000_000, "млн": 1_000_000, "million": 1_000_000, "миллион": 1_000_000,
    "ming": 1_000, "минг": 1_000, "тыс": 1_000, "k": 1_000,
}
_SON_REGEX = re.compile(
    r"(?P<kasr>\d+(?:[.,]\d+)?)\s*(?P<kop>mln|млн|million|миллион|ming|минг|тыс|k)(?![a-zа-я])"
    r"|(?P<guruh>\d{1,3}(?:[  .,']\d{3})+)(?!\d)"
    r"|(?P<oddiy>\d+)",
    re.IGNORECASE,
)


def sonlarni_ajratish(qator: str) -> list[int]:
    """'12 500 000 3', '12.5 mln 3', '12500000' kabi qatordan sonlarni ajratadi."""
    sonlar = []
    for m in _SON_REGEX.finditer(qator):
        if m.group("kasr"):
            kop = _KOPAYTIRUVCHILAR[m.group("kop").lower()]
            sonlar.append(round(float(m.group("kasr").replace(",", ".")) * kop))
        elif m.group("guruh"):
            sonlar.append(int(re.sub(r"\D", "", m.group("guruh"))))
        else:
            sonlar.append(int(m.group("oddiy")))
    return sonlar


_YOQ_REGEX = re.compile(r"(yo['‘’`]?q|йўқ|йук|нет|0|-)", re.IGNORECASE)


@dataclass
class OmborJavobi:
    narxlar: list[dict] = field(default_factory=list)  # [{"narx": int, "mavjud": int}]
    izoh: str = ""


def ombor_javobini_tahlil(matn: str, pozitsiyalar: list[dict]) -> OmborJavobi:
    """
    Ombor mas'uli javobini tahlil qiladi. Har bir pozitsiya uchun bitta qator:
        <1 dona narxi> [ombordagi soni]
    Narx 0 - omborda yo'q. "izoh:" bilan boshlangan qator mijozga yuboriladigan izoh.
    Xato bo'lsa ValueError (tushunarli xabar bilan) ko'taradi.
    """
    izohlar, qatorlar = [], []
    for qator in (matn or "").splitlines():
        qator = qator.strip()
        if not qator:
            continue
        izoh_match = re.match(r"^(izoh|изоҳ|изох|izox|примечание)\s*[:\-]\s*(.*)$", qator, re.IGNORECASE)
        if izoh_match:
            izohlar.append(izoh_match.group(2).strip())
        else:
            qatorlar.append(qator)

    if len(qatorlar) != len(pozitsiyalar):
        raise ValueError(
            f"{len(pozitsiyalar)} ta pozitsiya uchun {len(pozitsiyalar)} ta qator kerak, siz {len(qatorlar)} ta yozdingiz."
        )

    narxlar = []
    for i, (qator, poz) in enumerate(zip(qatorlar, pozitsiyalar), 1):
        # "1)" yoki "1." kabi tartib raqamini olib tashlash
        qator = re.sub(r"^\s*\d+\s*[).]\s+", "", qator)
        # Narx va ombordagi son ";" (yoki | / *) bilan ajratiladi. Ajratuvchisiz qator - faqat narx.
        # Bu "12 500 000 100" kabi noaniq yozuvlardan himoya qiladi.
        qismlar = re.split(r"\s*[;|/×*]\s*", qator, maxsplit=1)
        narx_qism = qismlar[0]
        miqdor_qism = qismlar[1] if len(qismlar) > 1 else ""

        if _YOQ_REGEX.fullmatch(narx_qism.strip()):
            narxlar.append({"narx": 0, "mavjud": 0})
            continue

        narx_sonlari = sonlarni_ajratish(narx_qism)
        if not narx_sonlari:
            raise ValueError(f"{i}-qatorda narx topilmadi.")
        if len(narx_sonlari) > 1:
            raise ValueError(
                f"{i}-qator noaniq: narx va sonni ';' bilan ajrating. Masalan: 12 500 000 ; 3"
            )
        narx = narx_sonlari[0]
        if 0 < narx < MIN_NARX:
            raise ValueError(
                f"{i}-qatordagi narx juda kichik ({narx}). Narxni to'liq so'mda yozing, masalan 12 500 000 yoki 12.5 mln."
            )

        if miqdor_qism:
            miqdor_sonlari = sonlarni_ajratish(miqdor_qism)
            if len(miqdor_sonlari) != 1:
                raise ValueError(f"{i}-qatorda ';' dan keyin faqat ombordagi sonni yozing.")
            mavjud = miqdor_sonlari[0]
        else:
            mavjud = poz["miqdor"] or 1

        if narx == 0:
            mavjud = 0
        narxlar.append({"narx": narx, "mavjud": mavjud})

    return OmborJavobi(narxlar=narxlar, izoh=" ".join(izohlar)[:500])


# =====================================================================
#  HISOB-KITOB VA TIJORAT TAKLIFI
# =====================================================================

def son_format(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def hisoblash(pozitsiyalar: list[dict], narxlar: list[dict]) -> tuple[list[dict], int]:
    """Har bir pozitsiya uchun sotiladigan miqdor va summani, hamda jami summani hisoblaydi."""
    qatorlar, jami = [], 0
    for poz, n in zip(pozitsiyalar, narxlar):
        soralgan = poz["miqdor"] or 1
        sotiladi = min(soralgan, n["mavjud"]) if n["narx"] > 0 else 0
        summa = sotiladi * n["narx"]
        jami += summa
        qatorlar.append({**poz, "soralgan": soralgan, "sotiladi": sotiladi, "narx": n["narx"], "summa": summa})
    return qatorlar, jami


def tolov_qismlari(jami: int) -> tuple[int, int]:
    """(oldindan to'lov, qolgan to'lov). Chegaradan oshmasa - 100% oldindan."""
    if jami > KATTA_BUYURTMA_CHEGARASI:
        oldindan = round(jami * OLDINDAN_TOLOV_FOIZI / 100)
        return oldindan, jami - oldindan
    return jami, 0


_MATNLAR = {
    "uz_latn": {
        "sarlavha": "📄 TIJORAT TAKLIFI №{id}",
        "qator": "{n}. {nomi}{param} — {sotiladi} {birlik} × {narx} = {summa} so'm",
        "qisman": "   (so'ralgan {soralgan} {birlik}, omborda {sotiladi} {birlik} mavjud)",
        "yoq": "{n}. {nomi}{param} — hozircha omborda yo'q",
        "jami": "💰 Jami: {jami} so'm",
        "tolov_toliq": "💳 To'lov: 100% oldindan to'lov",
        "tolov_qisman": "💳 To'lov: {foiz}% oldindan ({oldindan} so'm), qolgan {qfoiz}% ({qolgan} so'm) — tovarni ombordan olib chiqishdan oldin",
        "yetkazish": "🚚 Yetkazib berish: omborda mavjud tovar 1–3 kun ichida",
        "muddat": "⏳ Taklif {kun} kun amal qiladi",
        "izoh": "📝 {izoh}",
        "savol": "Buyurtmani rasmiylashtiramizmi? Schyot uchun kompaniya nomi va STIR (INN) kerak bo'ladi.",
        "hech_yoq": "Afsuski, so'ralgan pozitsiyalar hozircha omborda mavjud emas. Menejerimiz muqobil variant yoki buyurtma asosida yetkazib berish muddati bo'yicha tez orada siz bilan bog'lanadi.",
        "kutish": "Narx va ombordagi mavjudlikni aniqlab, tez orada sizga yuboraman.",
        "narx_aniqlanadi": "Narx va mavjudlikni ombordan aniqlab beraman. Qaysi pozitsiya va qancha miqdor kerakligini aniqlashtirib bera olasizmi?",
        "ai_xato": "Xabaringiz qabul qilindi. Menejerimiz tez orada javob beradi.",
        "salom": "Assalomu alaykum!",
        "start": "Assalomu alaykum! {kompaniya} savdo bo'limiga xush kelibsiz. Elektr dvigatel tanlashda yordam beraman. Sizga qanday quvvat va aylanish tezligidagi dvigatel kerak?",
        "taklif_izoh": "📄 Tijorat taklifi {raqam}",
        "taklif_tayyorlanmoqda": "Tijorat taklifini hozir yuboraman, narx bo'yicha menejerimiz siz bilan bog'lanadi.",
        "taklif_predmeti": "Elektr dvigatellarni yetkazib berish ({soni} pozitsiya)",
    },
    "uz_cyrl": {
        "sarlavha": "📄 ТИЖОРАТ ТАКЛИФИ №{id}",
        "qator": "{n}. {nomi}{param} — {sotiladi} {birlik} × {narx} = {summa} сўм",
        "qisman": "   (сўралган {soralgan} {birlik}, омборда {sotiladi} {birlik} мавжуд)",
        "yoq": "{n}. {nomi}{param} — ҳозирча омборда йўқ",
        "jami": "💰 Жами: {jami} сўм",
        "tolov_toliq": "💳 Тўлов: 100% олдиндан тўлов",
        "tolov_qisman": "💳 Тўлов: {foiz}% олдиндан ({oldindan} сўм), қолган {qfoiz}% ({qolgan} сўм) — товарни омбордан олиб чиқишдан олдин",
        "yetkazish": "🚚 Етказиб бериш: омборда мавжуд товар 1–3 кун ичида",
        "muddat": "⏳ Таклиф {kun} кун амал қилади",
        "izoh": "📝 {izoh}",
        "savol": "Буюртмани расмийлаштирамизми? Счёт учун компания номи ва СТИР (ИНН) керак бўлади.",
        "hech_yoq": "Афсуски, сўралган позициялар ҳозирча омборда мавжуд эмас. Менежеримиз муқобил вариант ёки буюртма асосида етказиб бериш муддати бўйича тез орада сиз билан боғланади.",
        "kutish": "Нарх ва омбордаги мавжудликни аниқлаб, тез орада сизга юбораман.",
        "narx_aniqlanadi": "Нарх ва мавжудликни омбордан аниқлаб бераман. Қайси позиция ва қанча миқдор кераклигини аниқлаштириб бера оласизми?",
        "ai_xato": "Хабарингиз қабул қилинди. Менежеримиз тез орада жавоб беради.",
        "salom": "Ассалому алайкум!",
        "start": "Ассалому алайкум! {kompaniya} савдо бўлимига хуш келибсиз. Электр двигател танлашда ёрдам бераман. Сизга қандай қувват ва айланиш тезлигидаги двигател керак?",
        "taklif_izoh": "📄 Тижорат таклифи {raqam}",
        "taklif_tayyorlanmoqda": "Тижорат таклифини ҳозир юбораман, нарх бўйича менежеримиз сиз билан боғланади.",
        "taklif_predmeti": "Elektr dvigatellarni yetkazib berish ({soni} pozitsiya)",
    },
    "ru": {
        "sarlavha": "📄 КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ №{id}",
        "qator": "{n}. {nomi}{param} — {sotiladi} {birlik} × {narx} = {summa} сум",
        "qisman": "   (запрошено {soralgan} {birlik}, в наличии {sotiladi} {birlik})",
        "yoq": "{n}. {nomi}{param} — пока нет в наличии",
        "jami": "💰 Итого: {jami} сум",
        "tolov_toliq": "💳 Оплата: 100% предоплата",
        "tolov_qisman": "💳 Оплата: {foiz}% предоплата ({oldindan} сум), остальные {qfoiz}% ({qolgan} сум) — до вывоза товара со склада",
        "yetkazish": "🚚 Доставка: товар в наличии — в течение 1–3 дней",
        "muddat": "⏳ Предложение действительно {kun} дн.",
        "izoh": "📝 {izoh}",
        "savol": "Оформляем заказ? Для счёта понадобятся название компании и ИНН.",
        "hech_yoq": "К сожалению, запрошенных позиций сейчас нет в наличии. Наш менеджер свяжется с вами в ближайшее время и предложит аналог или сроки поставки под заказ.",
        "kutish": "Уточню цену и наличие на складе и скоро отправлю вам.",
        "narx_aniqlanadi": "Цену и наличие уточню на складе. Подскажите, какая позиция и в каком количестве вам нужна?",
        "ai_xato": "Ваше сообщение получено. Наш менеджер скоро ответит.",
        "salom": "Здравствуйте!",
        "start": "Здравствуйте! Добро пожаловать в отдел продаж {kompaniya}. Помогу подобрать электродвигатель. Какой мощности и частоты вращения двигатель вам нужен?",
        "taklif_izoh": "📄 Коммерческое предложение {raqam}",
        "taklif_tayyorlanmoqda": "Сейчас отправлю коммерческое предложение, по цене с вами свяжется наш менеджер.",
        "taklif_predmeti": "Поставка электродвигателей ({soni} поз.)",
    },
}


def matn(kalit: str, til: str) -> str:
    return _MATNLAR.get(til if til in _MATNLAR else "uz_latn")[kalit]


def taklif_matni(sorov_id: int, pozitsiyalar: list[dict], narxlar: list[dict], til: str, izoh: str = "") -> tuple[str, int]:
    """Mijozga yuboriladigan tijorat taklifi matni va jami summa. Hammasi dasturda hisoblanadi."""
    t = _MATNLAR.get(til if til in _MATNLAR else "uz_latn")
    hisob, jami = hisoblash(pozitsiyalar, narxlar)

    qatorlar = [t["sarlavha"].format(id=sorov_id) + f"\n{KOMPANIYA_NOMI}", ""]
    for n, q in enumerate(hisob, 1):
        param = f" ({q['parametrlar']})" if q["parametrlar"] else ""
        if q["sotiladi"] == 0:
            qatorlar.append(t["yoq"].format(n=n, nomi=q["nomi"], param=param))
            continue
        qatorlar.append(t["qator"].format(
            n=n, nomi=q["nomi"], param=param, sotiladi=q["sotiladi"], birlik=q["birlik"],
            narx=son_format(q["narx"]), summa=son_format(q["summa"]),
        ))
        if q["sotiladi"] < q["soralgan"]:
            qatorlar.append(t["qisman"].format(soralgan=q["soralgan"], sotiladi=q["sotiladi"], birlik=q["birlik"]))

    oldindan, qolgan = tolov_qismlari(jami)
    qatorlar.append("")
    qatorlar.append(t["jami"].format(jami=son_format(jami)) + (f" ({NARX_IZOHI})" if NARX_IZOHI else ""))
    if qolgan:
        qatorlar.append(t["tolov_qisman"].format(
            foiz=OLDINDAN_TOLOV_FOIZI, qfoiz=100 - OLDINDAN_TOLOV_FOIZI,
            oldindan=son_format(oldindan), qolgan=son_format(qolgan),
        ))
    else:
        qatorlar.append(t["tolov_toliq"])
    qatorlar.append(t["yetkazish"])
    qatorlar.append(t["muddat"].format(kun=TAKLIF_MUDDATI_KUN))
    if izoh:
        qatorlar.append(t["izoh"].format(izoh=izoh))
    qatorlar.append("")
    qatorlar.append(t["savol"])
    return "\n".join(qatorlar), jami


def tolov_sharti_matni() -> str:
    """AI ko'rsatmasi uchun to'lov sharti (sozlamalardan - yagona manba)."""
    return (
        f"To'lov: {son_format(KATTA_BUYURTMA_CHEGARASI)} so'mgacha bo'lgan buyurtmalar - 100% oldindan to'lov. "
        f"Summa {son_format(KATTA_BUYURTMA_CHEGARASI)} so'mdan oshsa - {OLDINDAN_TOLOV_FOIZI}% oldindan, "
        f"qolgan {100 - OLDINDAN_TOLOV_FOIZI}% tovarni ombordan olib chiqishdan oldin."
    )


# =====================================================================
#  SALOMLASHISH
# =====================================================================

_SALOM_REGEX = re.compile(
    r"^\s*(va\s*alaykum\s*(as)?salom|ва\s*алайкум\s*(ас)?салом|assalomu\s+alaykum|ассалому\s+алайкум|"
    r"здравствуйте|добрый\s+(день|вечер|утро)|доброе\s+утро|привет|salom|салом|hello)(?!\w)[!.,\s]*",
    re.IGNORECASE,
)


# =====================================================================
#  TAKRORIY "RAHMAT" LARNI OLIB TASHLASH
# =====================================================================

_RAHMAT_REGEX = re.compile(
    r"(rahmat|raxmat|tashakkur|minnatdor\w*|раҳмат|рахмат|ташаккур|миннатдор\w*|спасибо|благодар\w*)",
    re.IGNORECASE,
)
# Minnatdorchilik gapidagi "bo'sh" so'zlar: ular olib tashlangach ma'noli so'z qolmasa - gap butunlay keraksiz
_RAHMAT_TOLDIRUVCHI = re.compile(
    r"(katta|juda|ko['‘’`]?p|sizga|sizdan|ham|uchun|ma['‘’`]?lumot\w*|javob\w*|savol\w*|murojaat\w*|"
    r"batafsil|tez|kontakt\w*|oldindan|tushundim|yaxshi|заранее|понял\w*|понятно|хорошо|олдиндан|тушундим|большое|огромное|вам|за|информаци\w*|ответ\w*|обращени\w*|"
    r"катта|жуда|кўп|сизга|учун|маълумот\w*|жавоб\w*)",
    re.IGNORECASE,
)


def takrorlanganmi(javob: str, oldingilar, chegara: float = 0.8) -> bool:
    """Javob oldingi bot javoblaridan birini deyarli so'zma-so'z takrorlayaptimi?"""
    from difflib import SequenceMatcher

    yangi = re.sub(r"\s+", " ", (javob or "").lower()).strip()
    if len(yangi) < 25:
        return False  # "Nechta kerak?" kabi qisqa savollar takrorlanishi mumkin
    for eski in oldingilar or ():
        eski = re.sub(r"\s+", " ", (eski or "").lower()).strip()
        if eski and SequenceMatcher(None, yangi, eski).ratio() >= chegara:
            return True
    return False


def taqdimotni_takrorlaydimi(javob: str, taqdimot: str, chegara: float = 0.6) -> bool:
    """AI javobi taqdimotning biror xatboshisini (masalan, oxirgi savolni) deyarli takrorlayaptimi?"""
    from difflib import SequenceMatcher

    yangi = re.sub(r"\s+", " ", (javob or "").lower()).strip()
    if not yangi:
        return False
    for xatboshi in re.split(r"\n\s*\n", taqdimot or ""):
        x = re.sub(r"\s+", " ", xatboshi.lower()).strip()
        if len(x) > 30 and SequenceMatcher(None, yangi, x).ratio() >= chegara:
            return True
    return False


def rahmat_aytilganmi(matn: str) -> bool:
    return bool(_RAHMAT_REGEX.search(matn or ""))


def _faqat_rahmatmi(gap: str, ism: str) -> bool:
    """Gap faqat minnatdorchilikdan iboratmi (ma'noli so'z yo'q)?"""
    if not _RAHMAT_REGEX.search(gap):
        return False
    tozalangan = _RAHMAT_TOLDIRUVCHI.sub(" ", _RAHMAT_REGEX.sub(" ", gap))
    if ism:
        tozalangan = re.sub(re.escape(ism), " ", tozalangan, flags=re.IGNORECASE)
    return not re.findall(r"\w{2,}", tozalangan)


def _oxirgi_rahmat_gapini_olib_tashlash(javob: str, ism: str) -> str:
    """Javob oxiridagi "Rahmat!" / "Oldindan rahmat." kabi bo'sh gapni olib tashlaydi."""
    m = re.search(r"(?:(?<=[.!?])|(?<=\n)|^)\s*([^.!?\n]+)[.!?]*\s*$", javob)
    if m and m.start() > 0 and _faqat_rahmatmi(m.group(1), ism):
        return javob[: m.start()].rstrip()
    return javob


def takroriy_rahmatni_olib_tashlash(javob: str, oldin_rahmat_aytilgan: bool, ism: str = "") -> str:
    """
    Bot har bir javobni "Rahmat!" bilan boshlamasligi uchun: suhbatda allaqachon minnatdorchilik
    bildirilgan bo'lsa, javob boshidagi faqat minnatdorchilikdan iborat gap olib tashlanadi.
    Ma'noli gap ("Rahmat, narxni omborga yubordim") o'chirilmaydi - faqat "Rahmat," so'zi olinadi.
    """
    if not oldin_rahmat_aytilgan or not javob:
        return javob
    javob = _oxirgi_rahmat_gapini_olib_tashlash(javob, ism)
    m = re.match(r"\s*([^.!?\n]*)([.!?]+|\n|$)\s*", javob)
    birinchi_gap = m.group(1)
    if not _RAHMAT_REGEX.search(birinchi_gap):
        return javob
    qolgani = javob[m.end():].strip()

    if _faqat_rahmatmi(birinchi_gap, ism):
        natija = qolgani  # "Rahmat!", "Ma'lumot uchun katta rahmat, Bahodir!" - butunlay olib tashlanadi
    else:
        # "Rahmat, endi narxni aniqlayman." -> "Endi narxni aniqlayman."
        yangi_gap = re.sub(
            r"^\s*(katta\s+|juda\s+|большое\s+)?" + _RAHMAT_REGEX.pattern + r"[\s,!.;:—-]*",
            "", javob, count=1, flags=re.IGNORECASE,
        )
        natija = yangi_gap if yangi_gap != javob else javob
    natija = natija.strip()
    if not natija:
        return javob  # javob faqat "rahmat" dan iborat bo'lsa - bo'sh xabar yuborilmaydi
    return natija[:1].upper() + natija[1:]


_SALOM_SOZLARI = {
    "assalomu", "assalom", "alaykum", "aleykum", "salom", "salam", "va", "aka", "opa", "uka", "hurmatli",
    "yaxshimisiz", "qalaysiz", "qalesiz", "xayrli", "kun", "tong", "kech", "hayrli",
    "ассалому", "ассалом", "алайкум", "алейкум", "салом", "салам", "ака", "опа", "яхшимисиз", "қалайсиз",
    "здравствуйте", "здравствуй", "привет", "добрый", "доброе", "день", "вечер", "утро", "здрасте",
    "hello", "hi", "hey", "/start", "start",
}


def faqat_salommi(matn: str) -> bool:
    """Xabar faqat salomlashishdan iboratmi ("Assalomu alaykum aka", "Здравствуйте!", "Salom 👋")?"""
    sozlar = re.findall(r"[^\W\d_]+|/start", (matn or "").lower())
    return 0 < len(sozlar) <= 5 and all(s in _SALOM_SOZLARI for s in sozlar)


def salomni_moslash(javob: str, birinchi_muloqotmi: bool, til: str) -> str:
    """1-javob salom bilan boshlanishini, keyingilarida salom qaytarilmasligini kafolatlaydi."""
    javob = javob.strip()
    salomli = bool(_SALOM_REGEX.match(javob))
    if birinchi_muloqotmi and not salomli:
        return f"{matn('salom', til)} {javob}"
    if not birinchi_muloqotmi and salomli:
        qolgani = _SALOM_REGEX.sub("", javob, count=1).strip()
        return qolgani[:1].upper() + qolgani[1:] if qolgani else javob
    return javob
