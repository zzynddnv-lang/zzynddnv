# 🤖 UMATIC savdo menejeri — Telegram AI sotuv boti

Bot Telegram'da (Telegram Business akkaunt yoki botning o'zi orqali) yozgan mijozlar bilan **savdo menejeri** kabi ishlaydi. UMATIC ning 3 yo'nalishi: **elektr dvigatellar, nasos agregatlari, elektroizolyatsiya materiallari** (umatic.uz dagi 104 ta mahsulot).

- birinchi xabarda o'zini tanishtiradi va kompaniya/mahsulotlar taqdimotini yuboradi;
- mahsulotlar haqida ma'lumot beradi, so'ralsa **texnik ma'lumot va rasmini** yuboradi (saytdan);
- model nomlarini saytdagidek **kirill** yozuvida yozadi (АИР132М4У1, ЭЦВ 8-25-100);
- mijoz tilini aniqlaydi va "rus tilida gapiring" kabi so'rovda tilni almashtiradi;
- sovuq mijozni qizdiradi, e'tirozlarga javob beradi, sotuvga olib boradi;
- mijoz qaysi tilda yozsa (o'zbek lotin, o'zbek kirill, rus) — o'sha tilda javob beradi;
- **narx aytmaydi**: pozitsiya va miqdor aniq bo'lgach, avval **omborda mavjudligi tekshiriladi** (ombor/menejer tugma bosadi), keyin mijozga UMATIC shablonidagi **tijorat taklifi (PDF, "Omborda" ustuni bilan)** yuboriladi — narxni menejer bildiradi;
- (ixtiyoriy, `NARX_OMBORDAN=1`) ombor mas'uli Telegram'da narx kiritadi va bot narxli taklifni o'zi hisoblab yuboradi;
- mijoz haqidagi barcha ma'lumotni **CRM** ga yig'adi (SQLite + CSV + Google Sheets) va menejerga bildirishnoma yuboradi.

---

## 🔄 Sotuv jarayoni (standart: narxsiz, `NARX_OMBORDAN=0`)

```text
Mijoz yozadi
   ↓
AI: salom → ehtiyoj → kVt, ob/min, miqdor → ism, kompaniya, telefon           (CRM: 🆕 → 🔍)
   ↓  pozitsiya va miqdor aniq
Mijozga: 📄 UMATIC_Tijorat_taklifi_UM-00012.pdf (UZ yoki RU, narx ustunida "So'rov bo'yicha")
Menejerga: PDF nusxasi + mijoz kartochkasi → "Mijozga narxni bildiring"      (CRM: 📄)
```

PDF sizning `UMATIC_Tijorat_taklifi_UZ.docx` / `..._RU_финал.docx` shabloningiz asosida chiziladi: logotip, rekvizitlar, ranglar, jadval, Yusufboyev Begzod imzosi. Kafolat, yetkazib berish, to'lov sharti va menejer qatori hozircha yo'q. O'zbek (lotin va kirill) mijozga — UZ, rus mijozga — RU shablon.

## 🔄 Ombor rejimi (`NARX_OMBORDAN=1`)

```text
Mijoz yozadi
   ↓
AI: salom → ehtiyoj → texnik parametrlar → miqdor → ism, kompaniya, telefon      (CRM: 🆕 → 🔍)
   ↓  pozitsiya va miqdor aniq
Ombor chatiga: 🆕 NARX SO'ROVI #12  [💰 Narx kiritish] [❌ Omborda yo'q]           (CRM: 💰)
   ↓  ombor mas'uli narx va qoldiqni yozadi
Bot hisoblab ko'rsatadi: "mijozga aynan shunday yuboriladi"  [✅ Mijozga yuborish] [✏️ Qayta]
   ↓  tasdiqlangach
Mijozga: 📄 TIJORAT TAKLIFI №12 (jami, to'lov sharti, muddat) — mijoz tilida    (CRM: 📄)
   ↓  mijoz rozi bo'lsa
Menejerga: 🎉 MIJOZ BUYURTMANI TASDIQLADI → schyot chiqarish                     (CRM: ✅)
```

**To'lov sharti** (sozlamalardan, dastur hisoblaydi):
- 100 mln so'mgacha — 100% oldindan to'lov;
- 100 mln so'mdan oshsa — 50% oldindan, qolgan 50% tovarni ombordan olib chiqishdan oldin.

**Menejerga bildirishnomalar:** yangi mijoz · menejer aralashuvi kerak (chegirma, shikoyat, qo'ng'iroq so'rovi) · buyurtma tasdiqlandi · omborda yo'q · taklifga 6 soat javob bo'lmadi · AI ishlamay qoldi.
**Omborga eslatma:** narx so'roviga 30 daqiqa javob berilmasa.

---

## 🧠 Botni o'qitish (bilimlar bazasi)

Bot faqat `bilimlar/` papkasidagi fayllarda yozilgan faktlarga tayanadi:

| Fayl | Nima yoziladi |
|---|---|
| `bilimlar/01_kompaniya.md` | Kompaniya haqida: kimsiz, afzalliklar (kafolat, yetkazib berish — aniq bo'lganda) |
| `bilimlar/02_mahsulotlar.md` | Elektr dvigatellar: umumiy ma'lumot va mijozdan qaysi parametrlarni so'rash kerak (brend/seriyalarni shu yerga qo'shing) |
| `bilimlar/03_sotuv_qoidalari.md` | Muloqot uslubi, sotuv bosqichlari, e'tirozlarga javoblar, taqiqlar |
| `bilimlar/katalog.json` | umatic.uz dagi 104 ta mahsulot: texnik ma'lumot, rasm, havola. **Yangilash:** `python tools/katalog_yangilash.py` |
| `bilimlar/tanishtiruv/uz_latn.txt`, `uz_cyrl.txt`, `ru.txt` | Mijozning **birinchi xabariga** avtomatik yuboriladigan taqdimot: kompaniya, 4 tur dvigatel, afzalliklar, chaqiriq. AI ga bog'liq emas — har doim to'liq chiqadi |

Qoidalar:
- Faqat **aniq va tasdiqlangan** ma'lumot yozing — bot har bir gapni mijozga aytishi mumkin.
- **Narx va qoldiqni yozmang** — ularni har safar ombor tasdiqlaydi.
- `<!-- ... -->` ichidagi matn botga ko'rinmaydi (o'zingiz uchun eslatma).
- Fayllar qisqa bo'lsin (jami ~12 000 belgigacha): har bir xabarda AI ga butun bilim yuboriladi.
- O'zgartirgach GitHub'ga yuklang — Render qayta ishga tushganda bot yangi bilimlarni oladi. Tekshirish: `/bilim`.

---

## ⚙️ O'rnatish

```bash
pip install -r requirements.txt
```

`.env.example` dan nusxa olib `.env` yarating. Asosiy sozlamalar:

| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather dan olingan token |
| `GROQ_API_KEY` | https://console.groq.com/keys |
| `OWNER_ID` | Egalar/menejerlar Telegram ID si (botga `/start` yuborsangiz ko'rsatiladi) |
| `TAKLIF_REJIMI` | `mavjudlik` (standart) — ombor mavjudlikni tasdiqlagach PDF; `narx` — ombor narx kiritadi; `darhol` — tekshiruvsiz PDF |
| `SKLAD_CHAT_ID` | Faqat `NARX_OMBORDAN=1` da: ombor mas'uli yoki ombor guruhi chat ID si (guruhda `/chatid`) |
| `KOMPANIYA_NOMI` | `UMATIC` |
| `KATTA_BUYURTMA_CHEGARASI`, `OLDINDAN_TOLOV_FOIZI` | Faqat `NARX_OMBORDAN=1` da, to'lov sharti: `100000000`, `50` |
| `NARX_IZOHI` | Faqat `NARX_OMBORDAN=1` da: masalan `QQS bilan` |
| `MODEL`, `FALLBACK_MODELS` | `openai/gpt-oss-120b`; zaxira: `qwen/qwen3.8-27b` (`gpt-oss-20b` o'zbek tilida sifatsiz — tavsiya etilmaydi) |
| `GOOGLE_SHEET_WEBHOOK_URL` | Google Sheets CRM (pastga qarang) |

### Ombor guruhini sozlash (faqat `NARX_OMBORDAN=1`)
1. Ombor mas'uli(lari) bilan Telegram guruh oching va botni guruhga qo'shing.
2. Guruhda `/chatid` yuboring (buni `OWNER_ID` dagi odam yuborishi kerak) — chiqqan raqamni `SKLAD_CHAT_ID` ga yozing.
3. Guruh a'zolari narx so'rovlaridagi tugmalarni bosa oladi va narxni **bot xabariga javob (reply)** qilib yozadi:
   ```text
   12 500 000 ; 3      ← 1 dona narxi ; omborda nechta bor
   4.2 mln             ← hammasi bor bo'lsa sonini yozmasa ham bo'ladi
   yo'q                ← bu pozitsiya omborda yo'q
   izoh: 2 kunda yetkaziladi   ← ixtiyoriy, mijozga ko'rinadi
   ```
   Narx va sonni albatta `;` bilan ajrating (`12500000 100` kabi noaniq yozuv qabul qilinmaydi).

### Google Sheets CRM
1. Google Sheets → **Extensions → Apps Script**, `google_apps_script.gs` kodini joylashtiring.
2. **Deploy → New deployment → Web app**: *Execute as: Me*, *Who has access: **Anyone***.
3. `.../exec` havolasini `GOOGLE_SHEET_WEBHOOK_URL` ga yozing. Har bir mijoz — bitta qator (yangilanib boradi).

---

## 🚀 Ishga tushirish

```bash
python zuxriddin_yordamchi_bot.py
```
yoki `run.bat`. Testlar:
```bash
python -m unittest discover -s tests -v
```

### Buyruqlar (faqat egalar uchun)
`/leads` · `/sorovlar` · `/export` · `/stats` · `/bilim` · `/chatid` · `/resume <chat_id>` · `/reset <chat_id>` · `/help`

Menejer Telegram Business chatida mijozga o'zi yozsa, bot **faqat shu chatda** pauza qiladi va menejerning oxirgi xabaridan **5 daqiqa** o'tgach o'zi qayta ishga tushadi (boshqa chatlarda ishlashda davom etadi). Menejer yozganlari bot xotirasiga tushadi — bot qaytganda suhbatni davom ettiradi. Darhol qayta yoqish: `/resume <chat_id>`. Muddatni o'zgartirish: `EGA_PAUZA_DAQIQA`.

---

## ⚠️ Cheklovlar

- **Groq bepul tarifi:** har bir model uchun daqiqasiga ~8 000 token va kuniga 200 000 token. Bitta javob ~3 500–4 000 token, ya'ni bepul tarifda har model daqiqasiga ~2 ta, kuniga ~50 ta javob beradi. Bot limitga urilganda darhol zaxira modelga o'tadi, lekin **real sotuv uchun Groq Developer (pullik) tarifiga o'tish kerak** — aks holda mijozlar ko'p bo'lganda javoblar kechikadi yoki "menejer javob beradi" deyiladi.
- **Render Free:** 15 daqiqa so'rov bo'lmasa uxlaydi (bot o'ziga ping yuborib buni oldini oladi); diskdagi baza deploy'da **o'chadi** — CRM tarixi uchun Google Sheets'ni albatta ulang.
- **Telegram Business:** bot mijozga faqat u oxirgi 24 soatda yozgan bo'lsa xabar yubora oladi. Taklif kechikib yuborilsa va xato bo'lsa, ombor chatida ogohlantirish chiqadi.
- **Rasm/fayl:** AI rasmni ko'ra olmaydi — mijoz yuborgan rasm (masalan, dvigatel shildigi) menejer va ombor chatiga yuboriladi.
