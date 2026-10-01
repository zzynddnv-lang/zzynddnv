"""
TIJORAT TAKLIFI PDF - UMATIC shabloni asosida (UMATIC_Tijorat_taklifi_UZ.docx / ..._RU_финал.docx).

Serverda Word yo'q, shuning uchun shablon dizayni reportlab bilan qayta chizilgan:
logotip, rekvizitlar, ranglar (#008E87), jadval va imzo - shablondagidek.
Standart rejimda taklif NARXSIZ: narx ustunida "So'rov bo'yicha".
Ombor rejimida (NARX_OMBORDAN=1) narxlar berilsa - narx, summa, jami va to'lov sharti bilan chiziladi.
Tillar: UZ (lotin va kirill mijozlar uchun), RU, EN.
"""

import io
import os
from datetime import datetime
from xml.sax.saxutils import escape

import sotuv
from vaqt import hozir

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(BASE_DIR, "assets", "umatic_logo.png")

# DejaVu Sans - kirill va o'zbek (o‘, g‘) harflarini to'liq qo'llaydi, erkin litsenziya
pdfmetrics.registerFont(TTFont("DejaVu", os.path.join(BASE_DIR, "assets", "fonts", "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", os.path.join(BASE_DIR, "assets", "fonts", "DejaVuSans-Bold.ttf")))

# Shablon ranglari
TEAL = colors.HexColor("#008E87")
TEAL_OCH = colors.HexColor("#EAF5F4")
KULRANG_FON = colors.HexColor("#F4F7F7")
MATN = colors.HexColor("#1F2933")
XIRA = colors.HexColor("#5F6B73")
CHIZIQ = colors.HexColor("#D9E2E1")


MATNLAR = {
    "uz": {
        "kompaniya": "“UMATIC” mas’uliyati cheklangan jamiyati qo‘shma korxona",
        "rekvizit": "STIR 311152304  •  h/r 20208000007034472001 (UZS)  •  MFO 01198",
        "footer": "“UMATIC” MChJ QK  |  STIR 311152304  |  h/r 20208000007034472001 (UZS)  |  MFO 01198",
        "raqam": "Chiq. №",
        "sana": "Sana:",
        "kimga": "Kimga:",
        "aloqa": "Aloqa:",
        "sarlavha": "TIJORAT TAKLIFI",
        "tagsarlavha": "elektr dvigatellarni yetkazib berish bo‘yicha",
        "hurmatli": "Hurmatli {ism}!",
        "hurmatli_umumiy": "Hurmatli mijoz!",
        "kirish": (
            "“UMATIC” MChJ qo‘shma korxonasi kompaniyamizga bildirgan qiziqishingiz uchun minnatdorlik bildiradi "
            "va elektr dvigatellarni yetkazib berish bo‘yicha hamkorlik imkoniyatini ko‘rib chiqishni taklif etadi. "
            "Biz Sizning texnik talablaringiz, byudjetingiz va loyiha muddatlaringizga mos yechimni tayyorlashga tayyormiz."
        ),
        "predmet": "Taklif predmeti:",
        "shartlar": "TIJORAT SHARTLARI",
        "ustunlar": ["№", "Tovar / xizmat", "Miqdori", "Narxi"],
        "narx": "So‘rov bo‘yicha",
        "izoh": "* Narx va mavjudlik ombor ma’lumotlari asosida alohida taqdim etiladi.",
        "yakun": (
            "Zaruratga ko‘ra texnik qismni tezkor aniqlashtirish, spetsifikatsiyani tayyorlash va loyihangiz uchun "
            "maqbul shartlarni taklif etishga tayyormiz."
        ),
        "hamkorlik": "Uzoq muddatli va o‘zaro manfaatli hamkorlikdan mamnun bo‘lamiz.",
        "imzo": "Hurmat bilan,<br/>Yusufboyev Begzod<br/>Savdo bo‘limi rahbari",
    },
    "ru": {
        "kompaniya": "СП ООО «UMATIC»",
        "rekvizit": "ИНН 311152304  •  р/с 20208000007034472001 (UZS)  •  МФО 01198",
        "footer": "“UMATIC” MChJ QK  |  ИНН 311152304  |  р/с 20208000007034472001 (UZS)  |  МФО 01198",
        "raqam": "Исх. №",
        "sana": "Дата:",
        "kimga": "Кому:",
        "aloqa": "Контакт:",
        "sarlavha": "КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ",
        "tagsarlavha": "на поставку электродвигателей",
        "hurmatli": "Уважаемый(ая) {ism}!",
        "hurmatli_umumiy": "Уважаемый клиент!",
        "kirish": (
            "СП ООО «UMATIC» благодарит Вас за интерес к нашей компании и предлагает рассмотреть возможность "
            "сотрудничества по поставке электродвигателей. Мы готовы сформировать решение под Ваши технические "
            "требования, бюджет и сроки реализации проекта."
        ),
        "predmet": "Предмет предложения:",
        "shartlar": "КОММЕРЧЕСКИЕ УСЛОВИЯ",
        "ustunlar": ["№", "Товар / услуга", "Кол-во", "Цена"],
        "narx": "По запросу",
        "izoh": "* Цена и наличие предоставляются отдельно по данным склада.",
        "yakun": (
            "При необходимости мы готовы оперативно уточнить техническую часть, подготовить спецификацию "
            "и предложить оптимальные условия под Ваш проект."
        ),
        "hamkorlik": "Будем рады долгосрочному и взаимовыгодному сотрудничеству.",
        "imzo": "С уважением,<br/>Юсуфбоев Бегзод<br/>Руководитель отдела продаж",
    },
    "en": {
        "kompaniya": "“UMATIC” LLC Joint Venture",
        "rekvizit": "TIN 311152304  •  acc. 20208000007034472001 (UZS)  •  Bank code 01198",
        "footer": "“UMATIC” LLC JV  |  TIN 311152304  |  acc. 20208000007034472001 (UZS)  |  Bank code 01198",
        "raqam": "Ref. No.",
        "sana": "Date:",
        "kimga": "To:",
        "aloqa": "Contact:",
        "sarlavha": "COMMERCIAL OFFER",
        "tagsarlavha": "for the supply of electric motors",
        "hurmatli": "Dear {ism},",
        "hurmatli_umumiy": "Dear customer,",
        "kirish": (
            "“UMATIC” LLC JV thanks you for your interest in our company and invites you to consider cooperation "
            "on the supply of electric motors. We are ready to prepare a solution that fits your technical "
            "requirements, budget and project timeline."
        ),
        "predmet": "Subject:",
        "shartlar": "COMMERCIAL TERMS",
        "ustunlar": ["No.", "Goods / service", "Qty", "Price"],
        "narx": "On request",
        "izoh": "* Price and availability are provided separately based on warehouse data.",
        "yakun": (
            "If necessary, we are ready to promptly clarify the technical details, prepare a specification "
            "and offer the best terms for your project."
        ),
        "hamkorlik": "We look forward to long-term and mutually beneficial cooperation.",
        "imzo": "Best regards,<br/>Begzod Yusufboyev<br/>Head of Sales",
    },
}

# Narxli taklif uchun qo'shimcha ustun va qatorlar
NARXLI = {
    "uz": {"ustunlar": ["№", "Tovar / xizmat", "Miqdori", "Narxi, so‘m", "Summa, so‘m"], "jami": "JAMI", "yoq": "omborda yo‘q",
           "izoh": "* Narxlar ombor ma’lumotlari asosida."},
    "ru": {"ustunlar": ["№", "Товар / услуга", "Кол-во", "Цена, сум", "Сумма, сум"], "jami": "ИТОГО", "yoq": "нет в наличии",
           "izoh": "* Цены по данным склада."},
    "en": {"ustunlar": ["No.", "Goods / service", "Qty", "Price, UZS", "Amount, UZS"], "jami": "TOTAL", "yoq": "out of stock",
           "izoh": "* Prices are based on warehouse data."},
}


def pdf_tili(til: str) -> str:
    """Mijoz tili bo'yicha shablon: rus - RU, ingliz - EN, o'zbek (lotin va kirill) - UZ."""
    return til if til in ("ru", "en") else "uz"


def taklif_raqami(sorov_id: int) -> str:
    return f"UM-{sorov_id:05d}"


def _uslublar():
    asos = dict(fontName="DejaVu", textColor=MATN, fontSize=9.5, leading=13)
    return {
        "matn": ParagraphStyle("matn", **asos),
        "qalin": ParagraphStyle("qalin", **{**asos, "fontName": "DejaVu-Bold"}),
        "hurmatli": ParagraphStyle("hurmatli", **{**asos, "fontName": "DejaVu-Bold", "fontSize": 10.5, "leading": 14}),
        "xira": ParagraphStyle("xira", **{**asos, "textColor": XIRA, "fontSize": 8.5, "leading": 11}),
        "xira_ong": ParagraphStyle("xira_ong", **{**asos, "textColor": XIRA, "fontSize": 8.5, "leading": 11, "alignment": TA_RIGHT}),
        "sarlavha": ParagraphStyle("sarlavha", fontName="DejaVu-Bold", fontSize=17, leading=22, textColor=TEAL, alignment=TA_CENTER),
        "tagsarlavha": ParagraphStyle("tagsarlavha", fontName="DejaVu", fontSize=8.5, leading=11, textColor=XIRA, alignment=TA_CENTER),
        "bolim": ParagraphStyle("bolim", fontName="DejaVu-Bold", fontSize=9.5, leading=13, textColor=MATN),
        "jadval_bosh": ParagraphStyle("jb", fontName="DejaVu-Bold", fontSize=8.5, leading=11, textColor=colors.white, alignment=TA_CENTER),
        "jadval": ParagraphStyle("j", fontName="DejaVu", fontSize=8.5, leading=11, textColor=MATN),
        "jadval_markaz": ParagraphStyle("jm", fontName="DejaVu", fontSize=8.5, leading=11, textColor=MATN, alignment=TA_CENTER),
        "jadval_xira": ParagraphStyle("jx", fontName="DejaVu", fontSize=7.5, leading=10, textColor=XIRA),
    }


def _sahifa_bezagi(canvas, doc, t: dict):
    """Har sahifadagi sarlavha (logotip + rekvizitlar) va pastki yozuv - shablondagidek."""
    en, bo = A4
    chap, ong = 18 * mm, en - 18 * mm
    canvas.saveState()
    if os.path.exists(LOGO):
        canvas.drawImage(LOGO, chap, bo - 30 * mm, width=58 * mm, height=17.4 * mm, mask="auto", preserveAspectRatio=True)
    canvas.setFillColor(MATN)
    canvas.setFont("DejaVu-Bold", 7.5)
    canvas.drawRightString(ong, bo - 19 * mm, t["kompaniya"])
    canvas.drawRightString(ong, bo - 23 * mm, t["rekvizit"])
    canvas.setStrokeColor(TEAL)
    canvas.setLineWidth(1)
    canvas.line(chap, bo - 34 * mm, ong, bo - 34 * mm)
    canvas.line(chap, 16 * mm, ong, 16 * mm)
    canvas.setFillColor(XIRA)
    canvas.setFont("DejaVu", 6.8)
    canvas.drawCentredString(en / 2, 12 * mm, t["footer"])
    canvas.restoreState()


def taklif_pdf(
    sorov_id: int,
    til: str,
    pozitsiyalar: list[dict],
    mijoz_ismi: str = "",
    kompaniya: str = "",
    telefon: str = "",
    predmet: str = "",
    sana: datetime | None = None,
    narxlar: list[dict] | None = None,
    izoh: str = "",
) -> bytes:
    """
    Tijorat taklifi PDF faylini yaratadi va baytlar ko'rinishida qaytaradi.
    narxlar berilmasa - narxsiz ("So'rov bo'yicha"); berilsa - narx, summa, jami va to'lov sharti bilan.
    """
    t = MATNLAR[pdf_tili(til)]
    u = _uslublar()
    sana = sana or hozir()
    kenglik = A4[0] - 36 * mm

    hikoya = []

    # Raqam / sana / mijoz satrlari (shablondagi ingichka chiziqli qatorlar)
    kimga = ", ".join(x for x in (kompaniya, mijoz_ismi) if x) or "—"
    satrlar = Table(
        [
            [Paragraph(f"{t['raqam']} {escape(taklif_raqami(sorov_id))}", u["xira"]),
             Paragraph(f"{t['sana']} {sana.strftime('%d.%m.%Y')}", u["xira_ong"])],
            [Paragraph(f"{t['kimga']} {escape(kimga)}", u["xira"]),
             Paragraph(f"{t['aloqa']} {escape(telefon or '—')}", u["xira_ong"])],
        ],
        colWidths=[kenglik * 0.6, kenglik * 0.4],
    )
    satrlar.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, CHIZIQ),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    hikoya += [satrlar, Spacer(1, 7 * mm)]

    hikoya += [
        Paragraph(t["sarlavha"], u["sarlavha"]),
        Paragraph(t["tagsarlavha"], u["tagsarlavha"]),
        Spacer(1, 6 * mm),
        Paragraph(t["hurmatli"].format(ism=escape(mijoz_ismi)) if mijoz_ismi else t["hurmatli_umumiy"], u["hurmatli"]),
        Spacer(1, 2 * mm),
        Paragraph(t["kirish"], u["matn"]),
        Spacer(1, 4 * mm),
    ]

    if predmet:
        quti = Table([[Paragraph(f"<b>{t['predmet']}</b> {escape(predmet)}", u["qalin"])]], colWidths=[kenglik])
        quti.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL_OCH),
            ("BOX", (0, 0), (-1, -1), 0.8, TEAL),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        hikoya += [quti, Spacer(1, 5 * mm)]

    # Tijorat shartlari jadvali
    hikoya.append(Paragraph(t["shartlar"], u["bolim"]))
    hikoya.append(Spacer(1, 2 * mm))
    if narxlar:
        hikoya += _narxli_jadval(pozitsiyalar, narxlar, til, u, kenglik, izoh)
    else:
        hikoya += _narxsiz_jadval(pozitsiyalar, t, u, kenglik)

    hikoya += [
        Paragraph(t["yakun"], u["matn"]),
        Spacer(1, 3 * mm),
        Paragraph(t["hamkorlik"], u["qalin"]),
        Spacer(1, 8 * mm),
        Paragraph(t["imzo"], u["xira"]),
    ]

    bufer = io.BytesIO()
    hujjat = SimpleDocTemplate(
        bufer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=40 * mm, bottomMargin=22 * mm,
        title=f"{t['sarlavha']} {taklif_raqami(sorov_id)}", author="UMATIC",
    )
    hujjat.build(
        hikoya,
        onFirstPage=lambda c, d: _sahifa_bezagi(c, d, t),
        onLaterPages=lambda c, d: _sahifa_bezagi(c, d, t),
    )
    return bufer.getvalue()


def _jadval_uslubi(qatorlar_soni: int, jami_qator: bool = False) -> TableStyle:
    uslub = [
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.5, CHIZIQ),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, TEAL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    oxirgi = qatorlar_soni - (1 if jami_qator else 0)
    for r in range(2, oxirgi, 2):
        uslub.append(("BACKGROUND", (0, r), (-1, r), KULRANG_FON))
    if jami_qator:
        uslub += [("BACKGROUND", (0, -1), (-1, -1), TEAL_OCH), ("SPAN", (0, -1), (3, -1))]
    return TableStyle(uslub)


def _nomi_paragrafi(p: dict, u: dict) -> Paragraph:
    nomi = escape(p["nomi"])
    if p.get("parametrlar"):
        nomi += f"<br/><font color='#5F6B73' size='7.5'>{escape(p['parametrlar'])}</font>"
    return Paragraph(nomi, u["jadval"])


def _narxsiz_jadval(pozitsiyalar: list[dict], t: dict, u: dict, kenglik: float) -> list:
    qatorlar = [[Paragraph(x, u["jadval_bosh"]) for x in t["ustunlar"]]]
    for i, p in enumerate(pozitsiyalar, 1):
        miqdor = f"{p['miqdor']} {escape(p.get('birlik') or '')}".strip() if p.get("miqdor") else "—"
        qatorlar.append([
            Paragraph(str(i), u["jadval_markaz"]),
            _nomi_paragrafi(p, u),
            Paragraph(miqdor, u["jadval_markaz"]),
            Paragraph(t["narx"], u["jadval_markaz"]),
        ])
    jadval = Table(qatorlar, colWidths=[kenglik * 0.07, kenglik * 0.55, kenglik * 0.16, kenglik * 0.22], repeatRows=1)
    jadval.setStyle(_jadval_uslubi(len(qatorlar)))
    return [jadval, Spacer(1, 2 * mm), Paragraph(t["izoh"], u["xira"]), Spacer(1, 6 * mm)]


def _narxli_jadval(pozitsiyalar: list[dict], narxlar: list[dict], til: str, u: dict, kenglik: float, izoh: str) -> list:
    """Narx, summa va jami - hammasi sotuv.hisoblash orqali (mijozga matnda boradigan raqamlar bilan bir xil)."""
    n = NARXLI[pdf_tili(til)]
    hisob, jami = sotuv.hisoblash(pozitsiyalar, narxlar)
    qatorlar = [[Paragraph(x, u["jadval_bosh"]) for x in n["ustunlar"]]]
    for i, q in enumerate(hisob, 1):
        if q["sotiladi"]:
            miqdor = f"{q['sotiladi']} {escape(q['birlik'])}"
            if q["sotiladi"] < q["soralgan"]:
                miqdor += f"<br/><font size='7'>({q['soralgan']})</font>"
            narx, summa = sotuv.son_format(q["narx"]), sotuv.son_format(q["summa"])
        else:
            miqdor, narx, summa = "—", n["yoq"], "—"
        qatorlar.append([
            Paragraph(str(i), u["jadval_markaz"]),
            _nomi_paragrafi(q, u),
            Paragraph(miqdor, u["jadval_markaz"]),
            Paragraph(narx, u["jadval_markaz"]),
            Paragraph(summa, u["jadval_markaz"]),
        ])
    qatorlar.append([Paragraph(f"<b>{n['jami']}</b>", u["jadval"]), "", "", "",
                     Paragraph(f"<b>{sotuv.son_format(jami)}</b>", u["jadval_markaz"])])
    jadval = Table(qatorlar, colWidths=[kenglik * 0.07, kenglik * 0.43, kenglik * 0.14, kenglik * 0.18, kenglik * 0.18],
                   repeatRows=1)
    jadval.setStyle(_jadval_uslubi(len(qatorlar), jami_qator=True))

    # To'lov sharti, muddat va izoh - mijozga yuboriladigan matn bilan bir xil (sotuv._MATNLAR)
    t = sotuv._MATNLAR.get(til if til in sotuv._MATNLAR else "uz_latn")
    oldindan, qolgan = sotuv.tolov_qismlari(jami)
    shartlar = [
        t["tolov_qisman"].format(
            foiz=sotuv.OLDINDAN_TOLOV_FOIZI, qfoiz=100 - sotuv.OLDINDAN_TOLOV_FOIZI,
            oldindan=sotuv.son_format(oldindan), qolgan=sotuv.son_format(qolgan),
        ) if qolgan else t["tolov_toliq"],
        t["yetkazish"],
        t["muddat"].format(kun=sotuv.TAKLIF_MUDDATI_KUN),
    ]
    if sotuv.NARX_IZOHI:
        shartlar.insert(0, sotuv.NARX_IZOHI)
    if izoh:
        shartlar.append(t["izoh"].format(izoh=izoh))
    natija = [jadval, Spacer(1, 2 * mm), Paragraph(n["izoh"], u["xira"]), Spacer(1, 4 * mm)]
    natija += [Paragraph(escape(_emojisiz(x)), u["matn"]) for x in shartlar]
    return natija + [Spacer(1, 6 * mm)]


def _emojisiz(matn: str) -> str:
    """PDF shriftida emoji yo'q - matn boshidagi belgini olib tashlaymiz."""
    return "• " + matn.lstrip("💳🚚⏳📝 ").strip()


def fayl_nomi(sorov_id: int, til: str) -> str:
    prefiks = {"ru": "Kommercheskoe_predlozhenie", "en": "Commercial_offer"}.get(pdf_tili(til), "Tijorat_taklifi")
    return f"UMATIC_{prefiks}_{taklif_raqami(sorov_id)}.pdf"
