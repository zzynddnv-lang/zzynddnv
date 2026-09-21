import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls
import os
from datetime import datetime

def set_cell_background(cell, fill_hex):
    """Katakcha orqa fonini bo'yash."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=120, bottom=120, left=180, right=180):
    """Katakcha ichki hoshiyalarini sozlash."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}>'
                      f'<w:top w:w="{top}" w:type="dxa"/>'
                      f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
                      f'<w:left w:w="{left}" w:type="dxa"/>'
                      f'<w:right w:w="{right}" w:type="dxa"/>'
                      f'</w:tcMar>')
    tcPr.append(tcMar)

def add_callout(doc, text, title="DIQQAT / OGOHLANTIRISH", border_color="C53030", bg_color="FFF5F5"):
    """Diqqat yoki ogohlantirish qutichasini qo'shish."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Inches(6.5)
    
    cell = table.cell(0, 0)
    set_cell_background(cell, bg_color)
    set_cell_margins(cell, top=140, bottom=140, left=200, right=200)
    
    # Chap chegara chizig'i
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(f'<w:tcBorders {nsdecls("w")}>'
                          f'<w:left w:val="single" w:sz="24" w:space="0" w:color="{border_color}"/>'
                          f'<w:top w:val="none"/>'
                          f'<w:right w:val="none"/>'
                          f'<w:bottom w:val="none"/>'
                          f'</w:tcBorders>')
    tcPr.append(tcBorders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(4)
    run_title = p.add_run(f"📌 {title}\n")
    run_title.bold = True
    run_title.font.size = Pt(11)
    run_title.font.name = "Calibri"
    r, g, b = int(border_color[:2], 16), int(border_color[2:4], 16), int(border_color[4:], 16)
    run_title.font.color.rgb = RGBColor(r, g, b)
    
    run_text = p.add_run(text)
    run_text.font.size = Pt(10)
    run_text.font.name = "Calibri"
    run_text.font.color.rgb = RGBColor(45, 55, 72)
    doc.add_paragraph().paragraph_format.space_after = Pt(6)

def create_report():
    doc = docx.Document()
    
    # Sahifa hoshiyalari (Margins) - 2.54 sm (1 inch)
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
        
    # Ranglar
    C_NAVY = RGBColor(27, 54, 93)      # #1B365D - Asosiy sarlavhalar
    C_BLUE = RGBColor(43, 108, 176)    # #2B6CB0 - Ikkinchi darajali sarlavhalar
    C_TEXT = RGBColor(45, 55, 72)      # #2D3748 - Asosiy matn
    C_MUTED = RGBColor(113, 128, 150)  # #718096 - Izohlar
    
    # -------------------------------------------------------------
    # SARLAVHA (TITLE SECTION)
    # -------------------------------------------------------------
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(4)
    run_title = title_p.add_run("ZUXRIDDIN YORDAMCHISI — TELEGRAM BUSINESS AI BOT")
    run_title.font.name = "Calibri"
    run_title.font.size = Pt(22)
    run_title.bold = True
    run_title.font.color.rgb = C_NAVY
    
    subtitle_p = doc.add_paragraph()
    subtitle_p.paragraph_format.space_after = Pt(12)
    run_sub = subtitle_p.add_run("Loyiha Maqsadi, To'liq Texnik Tahlil (QA), Xato va Kamchiliklar Hamda Rivojlantirish Rejasi")
    run_sub.font.name = "Calibri"
    run_sub.font.size = Pt(13)
    run_sub.font.color.rgb = C_BLUE
    
    # Meta ma'lumotlar jadvali
    meta_table = doc.add_table(rows=2, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.autofit = False
    meta_table.columns[0].width = Inches(3.25)
    meta_table.columns[1].width = Inches(3.25)
    
    meta_data = [
        [("Loyiha egasi:", " Zuxriddin"), ("Texnologiyalar:", " Python 3.13, aiogram 3, Groq (Llama 3.1)")],
        [("Tahlil turi:", " To'liq audit & QA (Quality Assurance)"), ("Sana:", f" {datetime.now().strftime('%Y-%m-%d')}")]
    ]
    for row_idx, row in enumerate(meta_data):
        for col_idx, (k, v) in enumerate(row):
            cell = meta_table.cell(row_idx, col_idx)
            set_cell_background(cell, "F7FAFC")
            set_cell_margins(cell, top=60, bottom=60, left=100, right=100)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r1 = p.add_run(k)
            r1.bold = True
            r1.font.size = Pt(9.5)
            r1.font.name = "Calibri"
            r1.font.color.rgb = C_NAVY
            r2 = p.add_run(v)
            r2.font.size = Pt(9.5)
            r2.font.name = "Calibri"
            r2.font.color.rgb = C_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(14)
    
    # -------------------------------------------------------------
    # 1-BO'LIM: SIZ NIMA QILMOQCHISIZ? (ASL MAQSAD TAHLILI)
    # -------------------------------------------------------------
    h1 = doc.add_paragraph()
    h1.paragraph_format.space_before = Pt(14)
    h1.paragraph_format.space_after = Pt(6)
    r_h1 = h1.add_run("1. SIZ NIMA QILMOQCHISIZ? (LOYIHANING ASOSIY MAQSADI)")
    r_h1.bold = True
    r_h1.font.size = Pt(15)
    r_h1.font.name = "Calibri"
    r_h1.font.color.rgb = C_NAVY
    
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(
        "Kodingizni va arxitekturangizni chuqur o'rganib chiqdik. Siz shaxsiy Telegram profilingiz uchun "
        "avtomatlashtirilgan sun'iy intellekt yordamchisini (AI SDR / Savdo bo'yicha yordamchi) qurmoqchisiz. "
        "Ushbu tizimning tub maqsadi quyidagi biznes vazifalarini yechishdan iborat:"
    )
    r.font.size = Pt(10.5)
    r.font.name = "Calibri"
    r.font.color.rgb = C_TEXT
    
    goals = [
        ("Shaxsiy akkauntni 24/7 rejimida ushlab turish: ", "Siz Telegram'da onlayn bo'lmagan, uxlab yotgan yoki boshqa ishlar bilan band bo'lgan vaqtingizda ham shaxsiy profilingizga yozgan har qanday odam bir necha soniyada javob oladi."),
        ("Lead Qualifying (Mijozni saralash va ma'lumot yig'ish): ", "Har bir murojaatchiga bir xil oddiy gaplarni qaytarmasdan, tabiiy insondek muloqot orqali 4 ta muhim savolga aniqlik kiritish: (1) Ismi, (2) Qanday masalada yozgani, (3) Aniq maqsadi nima (narx, mahsulot, hamkorlik), (4) Bog'lanish telefon raqami."),
        ("Xavfsiz va vakolatli suhbat (Hallucination Safe): ", "Sun'iy intellekt o'zidan narxlar yoki bajarib bo'lmas muddatlarni to'qib chiqarmasligi, bilmagan masalasida 'Buni Zuxriddin o'zi aniq aytadi' deb o'z vakolatini cheklashi."),
        ("Zuxriddin (Ega)ga tayyor hisobot uzatish: ", "Mijoz bilan ma'lumot to'liq olingach, AI Zuxriddinning shaxsiy chatiga barcha ma'lumotlarni qisqa hisobot (Lead Card) shaklida yetkazadi."),
        ("Mijozlar bazasini Excel (CSV)da yuritish: ", "Har bir murojaat yo'qolib ketmasligi uchun 'leadlar.csv' fayliga sana, ism, username, Telegram ID va xulosasi bilan yozib borish."),
        ("Egasi aralashganda AI orqaga chekinishi: ", "Agar siz (Zuxriddin) o'zingiz mijozga yozishni boshlasangiz, AI darhol suhbatdan chiqib ketishi va sizning muloqotingizga xalaqit bermasligi kerak.")
    ]
    for b_title, b_desc in goals:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.space_after = Pt(4)
        r_bt = bp.add_run(b_title)
        r_bt.bold = True
        r_bt.font.size = Pt(10)
        r_bt.font.name = "Calibri"
        r_bt.font.color.rgb = C_NAVY
        r_bd = bp.add_run(b_desc)
        r_bd.font.size = Pt(10)
        r_bd.font.name = "Calibri"
        r_bd.font.color.rgb = C_TEXT
        
    doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # -------------------------------------------------------------
    # 2-BO'LIM: HOZIRGACHA NIMA ISHLAR QILINDI?
    # -------------------------------------------------------------
    h2 = doc.add_paragraph()
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after = Pt(6)
    r_h2 = h2.add_run("2. HOZIRGACHA QILINGAN ISHLAR (JORIY HOLAT)")
    r_h2.bold = True
    r_h2.font.size = Pt(15)
    r_h2.font.name = "Calibri"
    r_h2.font.color.rgb = C_NAVY
    
    done_items = [
        ("Loyiha strukturasi yaratildi: ", "Bitta fayldan iborat qoralamadan to'liq professional loyiha shakliga keltirildi (.env, requirements.txt, run.bat, README.md, .gitignore)."),
        ("Xavfsizlik qatlami (.env): ", "Telegram Bot tokeni va Groq API kalitlari kod ichidan ajratilib, .env muhitiga olindi."),
        ("Leadlar fayli yo'li mustahkamlandi: ", "CSV fayli doimiy tarzda bot joylashgan papkaga tushishi uchun absolut yo'naltirish (BASE_DIR) joriy etildi."),
        ("Windows tezkor ishga tushirish (run.bat): ", "Har safar terminal buyruqlarini yozib o'tirmasdan, bitta bosish bilan botni yoqish imkoniyati yaratildi."),
        ("Boshlang'ich start komandasi: ", "Bot egasi botga kirib /start bosganida javob qaytarish mexanizmi qo'shildi.")
    ]
    for b_title, b_desc in done_items:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.space_after = Pt(3)
        r_bt = bp.add_run(b_title)
        r_bt.bold = True
        r_bt.font.size = Pt(10)
        r_bt.font.name = "Calibri"
        r_bt.font.color.rgb = C_BLUE
        r_bd = bp.add_run(b_desc)
        r_bd.font.size = Pt(10)
        r_bd.font.name = "Calibri"
        r_bd.font.color.rgb = C_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------
    # 3-BO'LIM: TO'LIQ QA VA KRITIK TAHLIL (XATO VA KAMCHILIKLAR)
    # -------------------------------------------------------------
    h3 = doc.add_paragraph()
    h3.paragraph_format.space_before = Pt(14)
    h3.paragraph_format.space_after = Pt(6)
    r_h3 = h3.add_run("3. KRITIK TAHLIL: BARCHA XATOLAR VA KAMCHILIKLAR (QA AUDIT)")
    r_h3.bold = True
    r_h3.font.size = Pt(15)
    r_h3.font.name = "Calibri"
    r_h3.font.color.rgb = C_NAVY

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(8)
    r = p.add_run(
        "Quyidagi tahlil kodni haqiqiy tijoriy yuklama (Production) sharoitida sinovdan o'tkazish "
        "natijasida aniqlangan barcha xatoliklar, xavflar va kamchiliklarni o'z ichiga oladi:"
    )
    r.font.size = Pt(10.5)
    r.font.name = "Calibri"
    r.font.color.rgb = C_TEXT

    # XATOLAR JADVALI
    table = doc.add_table(rows=1, cols=4)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.columns[0].width = Inches(1.8)
    table.columns[1].width = Inches(1.1)
    table.columns[2].width = Inches(2.2)
    table.columns[3].width = Inches(1.9)
    
    headers = ["Xatolik / Muammo", "Darajasi", "Oqibati", "Tavsiya etilgan yechim"]
    hdr_cells = table.rows[0].cells
    for idx, text in enumerate(headers):
        hdr_cells[idx].text = text
        set_cell_background(hdr_cells[idx], "1B365D")
        set_cell_margins(hdr_cells[idx], top=100, bottom=100, left=100, right=100)
        p = hdr_cells[idx].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.font.bold = True
            run.font.size = Pt(9.5)
            run.font.name = "Calibri"
            run.font.color.rgb = RGBColor(255, 255, 255)
            
    matrix = [
        ("1. allowed_updates ko'rsatilmagan", "KRITIK 🔴", "Bot Telegram Business xabarlarini eshitmay qoladi va ishlamaydi", "allowed_updates=dp.resolve_used_update_types()"),
        ("2. JSON parsing oqishi (Leak)", "KRITIK 🔴", "Mijozga dasturchi JSON kodi yuborilib qoladi", "Mustahkam regex + xavfsiz matn tozalash"),
        ("3. Poyga holati (Race Condition)", "YUQORI 🔴", "Bir vaqtda bir nechta xabar kelsa, bot bir necha bor salom yuboradi", "Har bir chat uchun asyncio.Lock()"),
        ("4. RAM xotiraga bog'liqlik", "YUQORI 🟡", "Bot qayta yonganda barcha suhbatlar va tugaganlar o'chadi", "SQLite ma'lumotlar bazasiga o'tish"),
        ("5. Cheksiz suhbat tarixi", "O'RTA 🟡", "Token sarfi oshadi, xotira to'ladi, so'rovlar sekinlashadi", "Sliding window (oxirgi 10 xabar)"),
        ("6. Ovozli xabarlar (Voice) inkor qilinishi", "O'RTA 🟡", "Ovoz tashlagan mijozlar boy beriladi", "Groq Whisper API bilan matnga o'girish"),
        ("7. Sinxron CSV yozish", "PAST 🟢", "Ko'p foydalanuvchida bot event loop'i qotib qolishi mumkin", "aiofiles yoki alohida thread'da yozish"),
        ("8. Chat boshqaruvi yo'qligi", "O'RTA 🟡", "Ega chatni qayta yoqish yoki to'xtatish imkoniga ega emas", "Admin buyruqlari (/pause, /leads, /reset)")
    ]
    
    for row_data in matrix:
        row_cells = table.add_row().cells
        for col_idx, text in enumerate(row_data):
            row_cells[col_idx].text = text
            set_cell_margins(row_cells[col_idx], top=70, bottom=70, left=90, right=90)
            p = row_cells[col_idx].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            for run in p.runs:
                run.font.size = Pt(9)
                run.font.name = "Calibri"
                if col_idx == 1:
                    run.font.bold = True
                    if "KRITIK" in text or "YUQORI" in text:
                        run.font.color.rgb = RGBColor(197, 48, 48)
                    else:
                        run.font.color.rgb = RGBColor(43, 108, 176)
                else:
                    run.font.color.rgb = C_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # BATAFSIL XATOLIKLAR TAHLILI
    add_callout(
        doc,
        "Telegram Bot API da oddiy xabarlar (Message) avtomatik keladi, biroq Business Connection va "
        "Business Message yangilanishlari faqatgina 'allowed_updates' parametrida aniq ko'rsatilgandagina botga yetkaziladi. "
        "Hozirgi dp.start_polling(bot) chaqiruvida bu ko'rsatilmaganligi sababli, bot biznes xabarlarini o'tkazib yuborishi muqarrar!",
        title="1-KRITIK XATO: ALLOWED_UPDATES YO'QLIGI",
        border_color="C53030",
        bg_color="FFF5F5"
    )

    add_callout(
        doc,
        "AI modeli har doim ham mukammal JSON qaytarmaydi. Agar Groq/Llama modeli javobni JSON emas, "
        "oddiy matn yoki chala formatda qaytarsa, koddagi 'except (ValueError, json.JSONDecodeError)' bloki "
        "xom matnni to'g'ridan-to'g'ri mijozga jo'natib yuboradi. Natijada mijoz ekranida JSON skriptlari ko'rinib qoladi.",
        title="2-KRITIK XATO: XOM JSON MATNINING MIJOZGA CHIQIB KETISHI",
        border_color="C53030",
        bg_color="FFF5F5"
    )

    add_callout(
        doc,
        "Telegram foydalanuvchilari ko'pincha ketma-ket bir nechta xabar jo'natishadi ('Salom', 'Narxlar qancha?', 'Yetkazib berish bormi?'). "
        "Koddagi asinxron ishlovchi har bir xabar uchun alohida korutina ochadi. Tarix hali saqlanmaganligi sababli, "
        "bot har bir xabarga alohida 'Salom' deb javob berishi va AI konteksti buzilib ketishi mumkin. Har bir chat_id uchun Lock zarur!",
        title="3-KRITIK XATO: POYGA HOLATI (RACE CONDITION)",
        border_color="DD6B20",
        bg_color="FFFAF0"
    )

    add_callout(
        doc,
        "Bot xotirasi (suhbatlar va tugaganlar) operativ xotirada (RAM) saqlanmoqda. Bot o'chib yonsa, "
        "barcha ma'lumotlar yo'qoladi. Avval gaplashib bo'lingan mijoz ertaga yozsa, bot yana unga noldan "
        "'Salom, men Zuxriddinning yordamchisiman...' deb boshlaydi. Buni zudlik bilan SQLite bazasiga o'tkazish kerak.",
        title="4-JIDDIY KAMCHILIK: MA'LUMOTLAR BAZASINING YO'QLIGI",
        border_color="DD6B20",
        bg_color="FFFAF0"
    )

    # -------------------------------------------------------------
    # 4-BO'LIM: BOSQICHMA-BOSQICH YO'L XARITASI (ROADMAP)
    # -------------------------------------------------------------
    h4 = doc.add_paragraph()
    h4.paragraph_format.space_before = Pt(14)
    h4.paragraph_format.space_after = Pt(6)
    r_h4 = h4.add_run("4. LOYIHANI MUKAMMAL QILISH YO'L XARITASI (ROADMAP)")
    r_h4.bold = True
    r_h4.font.size = Pt(15)
    r_h4.font.name = "Calibri"
    r_h4.font.color.rgb = C_NAVY

    phases = [
        ("1-Bosqich: Barqarorlik va Xatolarni tuzatish (Bug Fixes)", [
            "start_polling funksiyasiga 'allowed_updates=dp.resolve_used_update_types()' parametrini kiritish.",
            "JSON parsingni regex va tozalash mexanizmi bilan kuchaytirish (mijozga hech qachon xom kod bormasligi uchun).",
            "Chatlar uchun asyncio.Lock() joriy qilish (ketma-ket xabarlar poygasi oldini olish).",
            "Sliding window (oxirgi 10-12 xabar) orqali kontekst va token hajmini optimal saqlash."
        ]),
        ("2-Bosqich: Doimiy Xotira (SQLite) va Ega Boshqaruvi", [
            "RAM o'rniga yengil SQLite ma'lumotlar bazasini o'rnatish (chatlar holati doimiy saqlanadi).",
            "Muloqot statuslari tizimi: 'active' (AI javob beradi), 'paused' (ega o'zi yozmoqda), 'completed' (suhbat yakunlangan).",
            "Bot egasi uchun Telegram komandalari: /leads (oxirgi mijozlar), /stats (statistika), /export (CSV yuklash)."
        ]),
        ("3-Bosqich: Ovozli Xabarlar (Groq Whisper Integratsiyasi)", [
            "Mijoz ovozli xabar (voice message) yuborganda uni avtomatik yuklab olish.",
            "Groq Whisper API orqali ovozni 1-2 soniyada matnga o'girish.",
            "Matnni Llama modeliga uzatib, muloqotni uzluksiz davom ettirish (mijoz kutib qolmaydi)."
        ]),
        ("4-Bosqich: Cloud CRM va Google Sheets Integratsiyasi", [
            "CSV bilan birga real vaqtda Google Sheets jadvaliga yangi leadlarni qo'shib borish.",
            "Bitrix24, AmoCRM yoki Notion kabi tizimlar bilan Webhook orqali bog'lash."
        ]),
        ("5-Bosqich: 24/7 Doimiy Ishlash (Deployment)", [
            "Lokal kompyuterdan mustaqil ravishda arzon Linux VPS serverga (masalan, Hetzner, DigitalOcean) o'rnatish.",
            "Systemd xizmati yoki Docker orqali bot to'xtab qolsa o'zini o'zi qayta ishga tushirishini ta'minlash."
        ])
    ]

    for p_title, p_tasks in phases:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(2)
        r_pt = p.add_run(f"📌 {p_title}")
        r_pt.bold = True
        r_pt.font.size = Pt(11)
        r_pt.font.name = "Calibri"
        r_pt.font.color.rgb = C_BLUE
        
        for task in p_tasks:
            tp = doc.add_paragraph(style='List Bullet')
            tp.paragraph_format.space_after = Pt(2)
            r_t = tp.add_run(task)
            r_t.font.size = Pt(9.5)
            r_t.font.name = "Calibri"
            r_t.font.color.rgb = C_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # -------------------------------------------------------------
    # 5-BO'LIM: XULOSA VA TAVSIYA
    # -------------------------------------------------------------
    h5 = doc.add_paragraph()
    h5.paragraph_format.space_before = Pt(12)
    h5.paragraph_format.space_after = Pt(6)
    r_h5 = h5.add_run("5. XULOSA VA KEYINGI QADAMLAR")
    r_h5.bold = True
    r_h5.font.size = Pt(15)
    r_h5.font.name = "Calibri"
    r_h5.font.color.rgb = C_NAVY

    p_conc = doc.add_paragraph()
    p_conc.paragraph_format.space_after = Pt(8)
    r_c = p_conc.add_run(
        "Zuxriddin, siz yaratayotgan loyiha biznes va shaxsiy samaradorlik uchun juda katta qiymatga ega zamonaviy mahsulotdir. "
        "Ushbu auditda ko'rsatilgan 3 ta asosiy kritik xatolik (allowed_updates, JSON parsing, Concurrency lock) to'g'rilangandan so'ng, "
        "botingiz real mijozlar bilan hech qanday uzilishlarsiz va xavfsiz ishlashga to'liq tayyor bo'ladi. "
        "Keyingi bosqichda SQLite bazasi va Groq Whisper (ovozli xabarlar) qo'shilsa, ushbu bot O'zbekiston bozoridagi "
        "eng ilg'or AI yordamchilardan biriga aylanadi."
    )
    r_c.font.size = Pt(10.5)
    r_c.font.name = "Calibri"
    r_c.font.color.rgb = C_TEXT

    # Faylni saqlash
    output_path = r"c:\Users\Dell\Desktop\ai agent\Loyiha_Tahlili_va_Xato_Kamchiliklar.docx"
    doc.save(output_path)
    print(f"Hujjat muvaffaqiyatli yaratildi: {output_path}")

if __name__ == "__main__":
    create_report()
