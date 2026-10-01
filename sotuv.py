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
        "javob": _str("Mijozga xabar"),
        "til": {"type": "string", "enum": list(TILLAR)},
        "mijoz": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ism", "telefon", "kompaniya", "lavozim", "soha"],
            "properties": {k: {"type": "string"} for k in ("ism", "telefon", "kompaniya", "lavozim", "soha")},
        },
        "ehtiyoj": {"type": "string"},
        "mahsulotlar": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["nomi", "parametrlar", "miqdor", "birlik"],
                "properties": {
                    "nomi": {"type": "string"},
                    "parametrlar": _str("kVt, ob/min, V, o'rnatish, IP"),
                    "miqdor": {"type": "integer"},
                    "birlik": {"type": "string"},
                },
            },
        },
        "narx_sorash": {"type": "boolean"},
        "buyurtma_tasdiqlandi": {"type": "boolean"},
        "bosqich": {"type": "string", "enum": list(BOSQICHLAR)},
        "harorat": {"type": "string", "enum": list(HARORATLAR)},
        "menejer_kerak": {"type": "boolean"},
        "menejer_sababi": {"type": "string"},
        "xulosa": {"type": "string"},
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


# O'zbek (kirill) va rus tillarini ajratish uchun belgilar: so'zlar va qo'shimchalar
_UZ_KIRILL_SOZ_REGEX = re.compile(
    r"\b(ва|бу|шу|у|мен|сиз|биз|улар|нима|нега|қандай|кандай|қанча|канча|қачон|качон|керак|бор|йўқ|йук|йок|"
    r"ҳам|хам|учун|билан|лекин|ёки|эмас|бўлди|булди|яхши|хоп|раҳмат|рахмат|ака|опа|ассалому|салом|"
    r"борми|йўқми|қилиш|килиш|бериш|олиш|ёзинг|айтинг|қаердан|каердан|нарх|нархи|товар|сотмоқда)\b"
)
_UZ_KIRILL_QOSHIMCHA = re.compile(
    r"[а-яўқғҳ]{2,}(лар|ларни|ларга|ни|га|да|дан|даги|ми|чи|миз|сиз|мади|майди|япти|ябти|ябди|моқда|мокда|"
    r"ган|ганим|ганимда|ганда|ини|ига|ида|идан|ишни|иш|ади|айди|мизни|ингиз|нгиз)\b"
)
_RU_SOZ_REGEX = re.compile(
    r"\b(что|как|это|нужен|нужна|нужно|нужны|можно|есть|для|пожалуйста|здравствуйте|сколько|какой|какая|какие|"
    r"мне|вы|вас|вам|не|и|в|на|с|по|из|или|бы|ли|уже|ещё|еще|очень|спасибо|добрый|хочу|надо|где|когда|почему|"
    r"будет|был|была|если|только|тоже|также|у)\b"
)
_RU_QOSHIMCHA = re.compile(r"[а-я]{2,}(ый|ий|ой|ая|яя|ое|ее|ые|ие|ть|ться|ешь|ет|ют|ит|ят|ого|его|ому|ему|ых|их|ами|ями|ов|ев)\b")


def _uz_kirill_ballari(past: str) -> tuple[int, int]:
    """(o'zbek balli, rus balli) - kirill matn uchun."""
    uz = 3 * sum(1 for c in past if c in "ўқғҳ") + 2 * len(_UZ_KIRILL_SOZ_REGEX.findall(past)) + len(_UZ_KIRILL_QOSHIMCHA.findall(past))
    ru = 2 * len(_RU_SOZ_REGEX.findall(past)) + len(_RU_QOSHIMCHA.findall(past))
    return uz, ru


def tilni_aniqlash(matn: str, oldingi: str = "") -> str:
    """
    Matn yozilgan tilni aniqlaydi: uz_latn, uz_cyrl yoki ru.
    Kirill matnda o'zbek va rus so'zlari/qo'shimchalari solishtiriladi ("таништирмаябти" - o'zbekcha).
    Matnda harf juda kam bo'lsa ("ok", "5", emoji) - oldingi aniqlangan til qoldiriladi.
    """
    matn = matn or ""
    kirill, lotin = _harf_sonlari(matn)
    if kirill + lotin < 3 and oldingi in TILLAR:
        return oldingi
    if kirill <= lotin:
        return "uz_latn"
    uz, ru = _uz_kirill_ballari(matn.lower())
    if uz > ru:
        return "uz_cyrl"
    if uz == ru and oldingi in ("uz_cyrl", "ru"):
        return oldingi  # aniq emas (masalan "ок", "хоп") - avvalgi kirill til davom etadi
    return "ru" if ru > uz else "uz_cyrl" if any(c in _UZ_KIRILL_HARFLAR for c in matn) else "ru"


_TIL_SOROVLARI = (
    ("uz_cyrl", r"kirill(da|cha)?\b|кирилл|кирил(да|ча)"),
    ("uz_latn", r"lotin(da|cha)?\b|латин|лотин(да|ча)"),
    ("ru", r"rus\s*(tilida|tiliga|cha)|ruscha|по-?русски|на\s+русском|русск(ий|ом)\s+язык|русча|рус\s+тил"),
    ("uz", r"o['‘’`]?zbek\s*(tilida|tiliga|cha)|o['‘’`]?zbekcha|по-?узбекски|на\s+узбекском|узбекск|ўзбек\s*(тилида|ча)|узбек\s*(тилида|ча)|ўзбекча|узбекча"),
)


def til_sorovi(matn: str) -> str | None:
    """
    Mijoz tilni o'zgartirishni so'radimi? ("rus tilida gapiring", "по-узбекски", "kirillda yozing")
    Qaytaradi: uz_latn / uz_cyrl / ru yoki None.
    """
    past = (matn or "").lower()
    for til, naqsh in _TIL_SOROVLARI:
        if re.search(naqsh, past):
            if til == "uz":
                kirill, lotin = _harf_sonlari(matn)
                return "uz_cyrl" if kirill > lotin else "uz_latn"
            return til
    return None


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


def ombor_mavjudlik_tahlil(matn: str, pozitsiyalar: list[dict]) -> OmborJavobi:
    """
    Mavjudlik rejimi: ombor mas'uli har bir pozitsiya uchun bitta qatorda omborda NECHTA borligini yozadi.
        3        <- 3 ta bor
        yo'q / 0 <- yo'q
        izoh: ...  <- ixtiyoriy, mijozga ko'rinadi
    Narx so'ralmaydi. Xato bo'lsa ValueError (tushunarli xabar bilan).
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
    natija = []
    for i, qator in enumerate(qatorlar, 1):
        qator = re.sub(r"^\s*\d+\s*[).]\s+", "", qator)
        if _YOQ_REGEX.fullmatch(qator.strip()):
            natija.append({"narx": 0, "mavjud": 0})
            continue
        sonlar = sonlarni_ajratish(qator)
        if len(sonlar) != 1:
            raise ValueError(f"{i}-qatorda faqat omborda nechta borligini yozing (masalan: 3, yoki yo'q).")
        natija.append({"narx": 0, "mavjud": sonlar[0]})
    return OmborJavobi(narxlar=natija, izoh=" ".join(izohlar)[:500])


def mavjudlik_korinishi(pozitsiyalar: list[dict], narxlar: list[dict]) -> str:
    """Ombor mas'uliga tasdiqlash uchun: har pozitsiya bo'yicha so'ralgan va omborda bor soni."""
    qatorlar = []
    for i, (p, n) in enumerate(zip(pozitsiyalar, narxlar), 1):
        bor = n.get("mavjud", 0)
        belgi = "✅" if bor >= p["miqdor"] else ("⚠️" if bor else "❌")
        qatorlar.append(f"{belgi} {i}. {p['nomi']} — so'ralgan {p['miqdor']} {p['birlik']}, omborda {bor}")
    return "\n".join(qatorlar)


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
        "taklif_predmeti": "Uskunalar va materiallar yetkazib berish ({soni} pozitsiya)",
        "mavjudlik_tekshirilmoqda": "Omborda mavjudligini tekshirib, tijorat taklifini tez orada yuboraman.",
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
        "taklif_predmeti": "Ускуна ва материаллар етказиб бериш ({soni} позиция)",
        "mavjudlik_tekshirilmoqda": "Омборда мавжудлигини текшириб, тижорат таклифини тез орада юбораман.",
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
        "taklif_predmeti": "Поставка оборудования и материалов ({soni} поз.)",
        "mavjudlik_tekshirilmoqda": "Проверю наличие на складе и скоро отправлю коммерческое предложение.",
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


def takrorlanganmi(javob: str, oldingilar, chegara: float = 0.9) -> bool:
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


# =====================================================================
#  KATALOG: TANLASH, MODELNI TOPISH, NOMLARNI TO'G'RILASH
#  (token tejash - har safar 104 ta mahsulot emas, faqat mijozga mos qismi yuboriladi)
# =====================================================================

BOLIM_SARLAVHALARI = {
    "AIR": "Umumsanoat asinxron dvigatellar (АИР)",
    "MTN": "Kran-metallurgiya dvigatellari (МТН, МТКН)",
    "VA": "Portlashdan himoyalangan dvigatellar (ВА, ВАО)",
    "SD": "Sinxron dvigatellar (СД, СДМ, СДН, ВДС, СТДМ)",
    "ECV": "Quduq (skvajina) nasos agregatlari (ЭЦВ)",
    "D": "Ikki tomonlama kirishli nasoslar (Д)",
    "K": "Konsol nasoslar (К)",
    "KM": "Monoblok nasoslar (Гном)",
    "PROVOD": "Mis emal sim (ПЭТВ-2)",
    "STATOR": "Stator va yakor o'ram seksiyalari, kollektorlar (buyurtma asosida tayyorlanadi)",
    "LENTA": "Kiper lenta",
    "PERCHATKA": "Ish qo'lqoplari",
}
DVIGATEL_BOLIMLARI = ("AIR", "MTN", "VA", "SD")
NASOS_BOLIMLARI = ("ECV", "D", "K", "KM")
IZOLYATSIYA_BOLIMLARI = ("PROVOD", "STATOR", "LENTA", "PERCHATKA")

# So'z boshidan (\b) qidiriladi: "экран" -> "кран", "магазин" -> "газ" kabi xato mosliklar bo'lmasligi uchun.
# Uzbekcha "va" bog'lovchisi ВА seriyasi deb olinmasligi uchun faqat "VA 160", "VAO" kabi yozuvlar.
_TUR_KALITLARI = {
    "AIR": r"umumsanoat|asinxron|асинхрон|общепром|\bair|\bаир|konveyer|конвейер|ventilyator|вентилятор|kompressor|компрессор|stanok|станок",
    "MTN": r"\bkran|\bкран|ko['‘’`]?tarish|кўтариш|подъ[её]м|\blift|\bлифт|\bmtn|\bмтн|\bmtkn|\bмткн|metallurg|металлург",
    "VA": r"portla|взрыв|\bex\b|\bneft|\bнефт|\bgaz\b|\bгаз\b|shaxta|шахт|kimyo|хими|\bva\s?\d|\bvao|\bва\s?\d|\bвао",
    "SD": r"sinxron|синхрон|\bsd\d|\bsdm|\bсд\d|\bсдм|\bсдв|\bvds|\bвдс|\bstdm|\bстдм|tegirmon|мельниц|\d+\s*kv\b|\d+\s*кв\b",
    "ECV": r"quduq|қудуқ|кудук|skvajin|скважин|\becv|\bэцв|артезиан|\bets?v",
    "D": r"ikki\s+tomonlama|икки\s+томонлама|двухсторон|\bд\s?\d{3}|\bd\s?\d{3}",
    "K": r"konsol|консол|\b1к\b|\b1k\b|\b1[кk]\s?\d",
    "KM": r"monoblok|моноблок|гном|\bgnom|drenaj|дренаж|loyqa|лойқа|грязн|ифлос",
    "PROVOD": r"\bsim\b|\bsimi\b|\bсим\b|провод|\bemal|\bэмал|пэтв|\bpetv|обмоточн",
    "STATOR": r"stator|статор|seksiya|секци|yakor|якор|o['‘’`]?ram|ўрам|\bурам|обмотк|kollektor|коллектор|sterjen|стерж",
    "LENTA": r"kiper|кипер|\blenta|\bлента",
    "PERCHATKA": r"qo['‘’`]?lqop|қўлқоп|кулкоп|перчат|рукавиц|краги",
}
_GURUH_KALITLARI = (
    (r"dvigatel|двигател|\bmotor|\bмотор", DVIGATEL_BOLIMLARI),
    (r"\bnasos|\bнасос|\bpump", NASOS_BOLIMLARI),
    (r"izolyats|изоляц|изолятс", IZOLYATSIYA_BOLIMLARI),
)
MAX_KATALOG_QATOR = 25


def _son(matn) -> float:
    m = re.search(r"\d+(?:[.,]\d+)?", str(matn or "").replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else 0.0


def _xus(x: dict, *naqshlar: str) -> str:
    """Xususiyatlar ichidan kalit nomi naqshga mos birinchi qiymat."""
    for naqsh in naqshlar:
        for k, v in x.get("xus", {}).items():
            if re.search(naqsh, k, re.IGNORECASE) and v:
                return str(v).strip()
    return ""


def _birlik(matn: str) -> str:
    return (matn.replace("кВт", "kVt").replace("об/мин", "ob/min").replace(" В", " V").replace("м³/ч", "m³/soat"))


def katalog_qatori(x: dict) -> tuple[str, float]:
    """Mahsulot uchun ixcham katalog qatori va uning quvvati (kVt, saralash/filtrlash uchun)."""
    b, model = x["bolim"], x["model"]
    if b in DVIGATEL_BOLIMLARI:
        m = re.search(r"\s(\d+(?:[ ,.]\d+)*)\s*кВт", x["nomi"])
        kvt_nomi = m.group(1).strip() if m else ""
        kvt_xus = re.sub(r"\s*кВт", "", _xus(x, r"^Мощность$")).strip()
        if kvt_nomi and kvt_xus and abs(_son(kvt_nomi) - _son(kvt_xus)) > 0.01:
            kvt = f"{kvt_nomi} kVt (saytda {kvt_xus} kVt ham ko'rsatilgan - quvvatni menejer aniqlaydi)"
        else:
            kvt = f"{kvt_xus or kvt_nomi} kVt"
        ob = _xus(x, r"число оборотов|частота вращения") or (re.search(r"([\d,.]+)\s*об/мин", x["nomi"]) or [None, ""])[1]
        if ob and "об" not in ob:
            ob += " об/мин"
        qism = [model, kvt, ob, _xus(x, r"^Напряжение$"), _xus(x, r"Степень защиты"),
                ("KPD " + _xus(x, r"^КПД$")) if _xus(x, r"^КПД$") else ""]
        return _birlik(" | ".join(q for q in qism if q)), _son(kvt_xus or kvt_nomi)
    if b in NASOS_BOLIMLARI:
        q = _xus(x, r"Подача")
        h = _xus(x, r"^Напор")
        kvt = _xus(x, r"Мощность двигателя", r"Мощность потребляемая.*номин", r"Мощность")
        ob = _xus(x, r"Частота вращения.*об/мин", r"Частота вращения")
        qism = [model,
                f"{_son(q):g} m³/soat" if q else "",
                f"napor {_son(h):g} m" if h else "",
                f"{_son(kvt):g} kVt" if kvt else "",
                f"{_son(ob):g} ob/min" if ob else ""]
        return " | ".join(p for p in qism if p), _son(kvt)
    if b == "PROVOD":
        tavsif = x.get("tavsif", "")
        material = _xus(x, r"Материал") or (re.search(r"Материал:\s*([а-яё]+)", tavsif) or [None, ""])[1]
        sinf = _xus(x, r"нагревостойк") or (re.search(r"нагревостойкости:\s*([\w-]+)", tavsif) or [None, ""])[1]
        qism = [model, material, f"issiqlikka chidamlilik {sinf}" if sinf else ""]
        return " | ".join(p for p in qism if p), 0.0
    birinchi_gap = re.split(r"(?<=[.!?])\s", x.get("tavsif", ""))[0][:110]
    return f"{model} | {birinchi_gap}" if birinchi_gap else model, 0.0


def katalogni_tayyorlash(mahsulotlar: list[dict]) -> dict[str, list[dict]]:
    """katalog.json ro'yxatini bo'limlarga ajratadi va har bir mahsulotga ixcham qator qo'shadi."""
    bolimlar: dict[str, list[dict]] = {}
    for x in mahsulotlar:
        if x.get("bolim") not in BOLIM_SARLAVHALARI:
            continue
        qator, kvt = katalog_qatori(x)
        bolimlar.setdefault(x["bolim"], []).append({**x, "_qator": qator, "_kvt": kvt})
    for b in bolimlar:
        bolimlar[b].sort(key=lambda m: m["_kvt"])
    return bolimlar


def _katalog_bolimlari_tanlash(past: str) -> list[str]:
    tanlangan = [k for k, naqsh in _TUR_KALITLARI.items() if re.search(naqsh, past)]
    for naqsh, guruh in _GURUH_KALITLARI:
        if re.search(naqsh, past):
            tanlangan += [g for g in guruh if g not in tanlangan]
    return tanlangan


def katalog_tanlash(katalog: dict[str, list[dict]], mijoz_matni: str) -> str:
    """
    Mijoz yozganlariga qarab katalogdan kerakli qismni tanlaydi:
    - tur/yo'nalish aytilgan bo'lsa (kran, quduq nasosi, emal sim...) - shu bo'limlar;
    - quvvat (kVt) aytilgan bo'lsa - shu quvvatga yaqin (0,5x-2x) modellar;
    - hech narsa aytilmagan bo'lsa - katalog yuborilmaydi (umumiy ma'lumot bilimlarda bor).
    """
    if not katalog:
        return ""
    past = (mijoz_matni or "").lower()
    # "kVt", "квт", "kW" - quvvat; "кВ"/"kV" (kilovolt) - quvvat emas
    kvtlar = [float(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:kvt|квт|kwt|kw)\b", past)]
    bolimlar = [b for b in _katalog_bolimlari_tanlash(past) if b in katalog]
    if not bolimlar and not kvtlar:
        return ""
    if not bolimlar:
        bolimlar = [b for b in DVIGATEL_BOLIMLARI + NASOS_BOLIMLARI if b in katalog]

    natija, jami = [], 0
    for b in bolimlar:
        mahsulotlar = katalog[b]
        if kvtlar and any(m["_kvt"] for m in mahsulotlar):
            mos = [m for m in mahsulotlar if any(k * 0.5 <= m["_kvt"] <= k * 2 for k in kvtlar)]
            if not mos and b in _katalog_bolimlari_tanlash(past):
                mos = sorted(mahsulotlar, key=lambda m: min(abs(m["_kvt"] - k) for k in kvtlar))[:2]
            mahsulotlar = mos
        mahsulotlar = mahsulotlar[: max(0, MAX_KATALOG_QATOR - jami)]
        if mahsulotlar:
            natija.append("## " + BOLIM_SARLAVHALARI[b])
            natija += ["- " + m["_qator"] for m in mahsulotlar]
            jami += len(mahsulotlar)
    return "\n".join(natija)


# ---------- Model nomlari: kirill (katalogdagidek) <-> lotin ----------

_LOTIN_MOSLIK = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "J", "З": "Z", "И": "I", "Й": "Y",
    "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F",
    "Х": "H", "Ц": "C", "Ч": "CH", "Ш": "SH", "Щ": "SH", "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "YU", "Я": "YA",
    "Ў": "O", "Қ": "Q", "Ғ": "G", "Ҳ": "H",
}


def model_kaliti(matn: str) -> str:
    """Yozuvdan qat'i nazar solishtirish kaliti: 'АИР132М4У1', 'AIR 132 M4 U1', 'air132m4u1' -> 'AIR132M4U1'."""
    t = "".join(_LOTIN_MOSLIK.get(c, c) for c in (matn or "").upper())
    t = t.replace("X", "H").replace("TS", "C")
    return re.sub(r"[^A-Z0-9]", "", t)


def _hamma_mahsulotlar(katalog: dict[str, list[dict]]) -> list[dict]:
    return [m for b in katalog.values() for m in b]


def topilgan_modellar(katalog: dict[str, list[dict]], matn: str, limit: int = 3) -> list[dict]:
    """Matnda tilga olingan aniq katalog modellari (kirill yoki lotin yozuvida)."""
    kalit = model_kaliti(matn)
    topildi = []
    for m in sorted(_hamma_mahsulotlar(katalog), key=lambda x: -len(model_kaliti(x["model"]))):
        mk = model_kaliti(m["model"])
        if len(mk) >= 4 and re.search(r"\d", mk) and mk in kalit and not any(mk in model_kaliti(t["model"]) for t in topildi):
            topildi.append(m)
    return topildi[:limit]


_KIRILL_LOTIN_SINF = {
    "А": "АA", "В": "ВVB", "Д": "ДD", "Е": "ЕE", "И": "ИI", "К": "КK", "Л": "ЛL", "М": "МM", "Н": "НNH",
    "О": "ОO", "П": "ПP", "Р": "РRP", "С": "СSC", "Т": "ТT", "У": "УUY", "Х": "ХXH", "Г": "ГG", "З": "ЗZ",
    "Э": "ЭE", "Б": "БB", "Ы": "ЫY", "Й": "ЙY", "Ф": "ФF",
}
_NAQSH_KESH: dict[str, re.Pattern] = {}


def _model_naqshi(model: str) -> re.Pattern:
    """Model nomining lotin/kirill aralash yozilishini ham ushlaydigan naqsh ('AIR132M4U1' -> 'АИР132М4У1')."""
    if model not in _NAQSH_KESH:
        qismlar = []
        for c in model.upper().replace(" ", "").replace("-", ""):
            if c in _KIRILL_LOTIN_SINF:
                qismlar.append(f"[{_KIRILL_LOTIN_SINF[c]}]")
            elif c == "Ц":
                qismlar.append("(?:Ц|C|TS)")
            elif c == "Ш":
                qismlar.append("(?:Ш|SH)")
            elif c == "Ч":
                qismlar.append("(?:Ч|CH)")
            else:
                qismlar.append(re.escape(c))
        _NAQSH_KESH[model] = re.compile(r"(?<![\w])" + r"[\s-]?".join(qismlar) + r"(?![\w])", re.IGNORECASE)
    return _NAQSH_KESH[model]


_SERIYA_LOTIN = [
    (r"(?<![\w])MTKN(?![a-z])", "МТКН"), (r"(?<![\w])MTN(?![a-z])", "МТН"), (r"(?<![\w])AIR(?![a-z])", "АИР"),
    (r"(?<![\w])VAO(?![a-z])", "ВАО"), (r"(?<![\w])VA(?=[\s-]?\d|,|\)|/)", "ВА"), (r"(?<![\w])STDM(?![a-z])", "СТДМ"),
    (r"(?<![\w])SDM(?![a-z])", "СДМ"), (r"(?<![\w])SDN(?![a-z])", "СДН"), (r"(?<![\w])SD(?=[\s-]?\d|,|\)|/)", "СД"),
    (r"(?<![\w])VDS(?![a-z])", "ВДС"), (r"(?<![\w])(?:ECV|ETSV|ETsV)(?![a-z])", "ЭЦВ"),
    (r"(?<![\w])PETV(?![a-z])", "ПЭТВ"), (r"(?<![\w])GNOM(?![a-z])|(?<![\w])Gnom(?![a-z])", "Гном"),
]


def model_nomlarini_tuzatish(matn: str, katalog: dict[str, list[dict]]) -> str:
    """
    AI lotinga o'girib yozgan model va seriya nomlarini katalogdagi asl (kirill) yozuvga qaytaradi:
    'AIR132M4U1' -> 'АИР132М4У1', 'MTN 411-8' -> 'МТН 411-8', 'AIR seriyasi' -> 'АИР seriyasi'.
    """
    if not matn:
        return matn
    for m in sorted(_hamma_mahsulotlar(katalog), key=lambda x: -len(x["model"])):
        if re.search(r"\d", m["model"]):
            matn = _model_naqshi(m["model"]).sub(lambda t: m["model"] if re.search(r"[A-Za-z]", t.group(0)) else t.group(0), matn)
    for naqsh, kirill in _SERIYA_LOTIN:
        matn = re.sub(naqsh, kirill, matn)
    return matn


# AI ning takrorlanib turadigan atama xatolari ("sarf" o'rniga "sug'urta" - insurance)
_ATAMA_TUZATISHLARI = (
    (r"\bsu[g‘'ʻ`]?['‘’ʻ`]?urta(?=\s*\(?\s*m[³3])", "sarf"),
    (r"\bсу[ғг]урта(?=\s*\(?\s*м[³3])", "сарф"),
)


def atamalarni_tuzatish(matn: str) -> str:
    for naqsh, togri in _ATAMA_TUZATISHLARI:
        matn = re.sub(naqsh, togri, matn or "", flags=re.IGNORECASE)
    return matn


def tafsilot_matni(m: dict) -> str:
    """Aniq model uchun to'liq texnik ma'lumot (AI texnik savollarga javob berishi uchun)."""
    xus = "; ".join(f"{k}: {v}" for k, v in list(m.get("xus", {}).items())[:16])
    return f"{m['model']} ({m['nomi']}) — {xus}. {m.get('tavsif', '')[:350]} Sahifa: {m['url']}"


_RASM_SOROV = re.compile(
    r"rasm|surat|\bfoto|\bphoto|фото|расм|сурат|картин|изображ|ko['‘’`]?rinish|кўриниш|как\s+выгляд|qanaqa\s+ko['‘’`]?rin",
    re.IGNORECASE,
)


def rasm_soraldimi(matn: str) -> bool:
    return bool(_RASM_SOROV.search(matn or ""))


# =====================================================================
#  "MENEJER BOG'LANADI" TAKRORINI CHEKLASH VA ZAXIRA JAVOB
# =====================================================================

_MENEJER_REGEX = re.compile(r"menejer|менеджер|менежер|manager", re.IGNORECASE)
_NARX_SAVOL_REGEX = re.compile(
    r"narx|qancha\s+tur|necha\s+pul|so['‘’`]?m|chegirma|skidka|omborda|mavjudmi|yetkaz|dostavka|"
    r"цен[аыу]|стоимост|сколько\s+стоит|скидк|наличи|доставк|нарх|неча\s+пул|чегирма|омборда|етказ",
    re.IGNORECASE,
)


def menejer_aytilganmi(matn: str) -> bool:
    return bool(_MENEJER_REGEX.search(matn or ""))


def narx_savolimi(matn: str) -> bool:
    """Mijoz narx, chegirma, mavjudlik yoki yetkazib berish haqida so'rayaptimi (menejer kerak bo'ladigan savol)?"""
    return bool(_NARX_SAVOL_REGEX.search(matn or ""))


def takroriy_menejerni_olib_tashlash(javob: str, oldin_aytilgan: bool, savol_narxmi: bool) -> str:
    """
    Bot har javobda "menejer siz bilan bog'lanadi" demasligi uchun: suhbatda bu allaqachon aytilgan bo'lsa
    va mijoz narx/mavjudlik so'ramagan bo'lsa - "menejer" tilga olingan gaplar olib tashlanadi.
    Javob bo'sh qolib ketsa - o'zgartirilmaydi.
    """
    if not oldin_aytilgan or savol_narxmi or not menejer_aytilganmi(javob):
        return javob
    gaplar = re.split(r"(?<=[.!?])\s+", javob.strip())
    qolgan = [g for g in gaplar if not menejer_aytilganmi(g)]
    natija = " ".join(qolgan).strip()
    return natija if len(natija) >= 15 else javob


_ZAXIRA_MATNLAR = {
    "uz_latn": ("Katalogimizdan mos modellar:", "Qaysi biri sizga mos va nechta kerak bo'ladi?",
                "Sizga mos dvigatelni tanlashim uchun quvvat (kVt), aylanish tezligi (ob/min) va dvigatel qaysi mexanizmda ishlashini yozing."),
    "uz_cyrl": ("Каталогимиздан мос моделлар:", "Қайси бири сизга мос ва нечта керак бўлади?",
                "Сизга мос двигателни танлашим учун қувват (кВт), айланиш тезлиги (об/мин) ва двигател қайси механизмда ишлашини ёзинг."),
    "ru": ("Подходящие модели из нашего каталога:", "Какая из них вам подходит и сколько нужно?",
           "Чтобы подобрать двигатель, напишите мощность (кВт), частоту вращения (об/мин) и для какого механизма он нужен."),
}


def zaxira_javob(til: str, katalog: str) -> str:
    """
    AI vaqtincha ishlamay qolganda ham mijozga FOYDALI javob (menejerga yo'naltirmasdan):
    so'ralgan quvvatga mos katalog modellari yoki tanlash uchun kerakli parametrlar.
    """
    bosh, savol, umumiy = _ZAXIRA_MATNLAR.get(til, _ZAXIRA_MATNLAR["uz_latn"])
    modellar = [q[2:] for q in (katalog or "").splitlines() if q.startswith("- ")][:3]
    if not modellar:
        return umumiy
    qatorlar = []
    for m in modellar:
        qismlar = [x.strip() for x in m.split("|")]
        qatorlar.append(f"• {qismlar[0]} — {', '.join(qismlar[1:4])}")
    return "\n".join([bosh, *qatorlar, "", savol])


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
