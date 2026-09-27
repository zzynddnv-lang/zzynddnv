# 🤖 Zuxriddinning Shaxsiy AI Yordamchisi (Executive Personal Assistant)

Ushbu bot Telegram Business hisobingizga kelgan barcha matnli, **ovozli (voice)**, **video (kruglyash)** va rasm xabarlariga sun'iy intellekt (**Groq Qwen 27B & Whisper Turbo**) orqali avtomatik javob beradi. Zuxriddin onlayn bo'lmaganda suhbatdoshni samimiy kutib oladi, har qanday savoliga javob beradi, uning kimligi va maqsadini to'liq aniqlab, Zuxriddinga dosye yuboradi hamda Google Sheets jadvaliga sinxronizatsiya qiladi.

---

## 📁 Papka tuzilmasi

```text
ai agent/
│
├── zuxriddin_yordamchi_bot.py   # Botning asosiy dastur kodi
├── database.py                  # SQLite ma'lumotlar bazasi moduli
├── google_apps_script.gs        # Google Sheets webhook kodi (Apps Script)
├── tests/                       # Avtomatik testlar
├── yordamchi_bot.db             # Doimiy SQLite bazasi (avtomatik yaratiladi)
├── leadlar.csv                  # Murojaatlar zaxirasi (Excel, avtomatik yaratiladi)
├── .env                         # Maxfiy sozlamalar (gitga yuklanmaydi)
├── .env.example                 # Sozlamalar namunasi
├── requirements.txt             # Kerakli Python kutubxonalari
├── render.yaml / Procfile       # Render.com serveriga joylash sozlamalari
├── run.bat                      # Windows uchun tezkor ishga tushirish
└── github_ga_yuklash.bat        # GitHub'ga yuklash (git push)
```

---

## 🌟 Imkoniyatlar

1. **Telegram Business bilan to'liq integratsiya:** shaxsiy akkauntingizga kelgan xabarlarga avtomatik javob beradi. Siz o'zingiz yozsangiz, bot 30 daqiqa aralashmaydi.
2. **🎙 Ovoz, kruglyash va audio:** Groq Whisper orqali matnga aylantiriladi. Rasm izohi, kontakt, lokatsiya va hujjatlar ham qabul qilinadi.
3. **📋 Murojaat dosyesi:** ism, telefon, tashkilot, mavzu va muhimlik AI orqali aniqlanadi va sizga Telegram'da yuboriladi. Har bir murojaatchi uchun **bitta** dosye saqlanadi — qo'shimcha ma'lumot kelsa, mavjudi yangilanadi (dublikat yo'q).
4. **💾 Saqlash:** SQLite baza + `leadlar.csv` zaxirasi + Google Sheets (ixtiyoriy).
5. **🔒 Xavfsizlik:** admin buyruqlari va dosyelar faqat `OWNER_ID` ga (va Business ulangan akkaunt egasiga) ochiq. Begona foydalanuvchi `/start` bosib ega bo'lib ololmaydi.
6. **🔁 Model zaxirasi:** asosiy model ishlamasa, `FALLBACK_MODELS` dagi modellar ishlatiladi.
7. **👑 Bot egasi uchun buyruqlar:**
   - `/leads` — oxirgi 5 ta murojaat dosyesi
   - `/export` — barcha murojaatlarni Excel (CSV) faylda yuklab olish
   - `/stats` — statistika, faol model va Google Sheets holati
   - `/resume <chat_id>` — siz yozgan chatda botni darhol qayta yoqish
   - `/reset <chat_id>` — chat xotirasini tozalash (sinov uchun)
   - `/help` — qo'llanma

---

## ⚙️ O'rnatish va Sozlash

### 1. Kutubxonalarni o'rnatish
```bash
pip install -r requirements.txt
```

### 2. `.env` faylini to'ldirish
`.env.example` dan nusxa olib `.env` yarating va to'ldiring:
```env
BOT_TOKEN=sizning_bot_tokeningiz
GROQ_API_KEY=sizning_groq_api_kalitingiz
OWNER_ID=sizning_telegram_id_raqamingiz
EGA_ISMI=Zuxriddin
MODEL=qwen/qwen3.8-27b
FALLBACK_MODELS=openai/gpt-oss-120b,openai/gpt-oss-20b
GOOGLE_SHEET_WEBHOOK_URL=
```

> **OWNER_ID ni qanday bilish mumkin?** Botga `/start` yuboring — javobda Telegram ID raqamingiz ko'rsatiladi.
> `OWNER_ID` yozilmagan bo'lsa, faqat **birinchi** `/start` bosgan foydalanuvchi va Business ulangan akkaunt ega hisoblanadi.

### 3. Google Sheets (ixtiyoriy)
1. Google Sheets jadvalini oching → **Extensions → Apps Script**.
2. `google_apps_script.gs` kodini joylashtiring va saqlang.
3. **Deploy → New deployment → Web app**: *Execute as: Me*, *Who has access: **Anyone***.
4. Berilgan `.../exec` havolasini `GOOGLE_SHEET_WEBHOOK_URL` ga yozing.

Ulanish holatini `/stats` buyrug'i va har bir dosye ostidagi belgi (✅ / ⚠️) ko'rsatadi.

---

## 🚀 Ishga tushirish

1. **Eng oson usul:** **`run.bat`** faylini ikki marta bosing.
2. **Terminal orqali:**
   ```bash
   python zuxriddin_yordamchi_bot.py
   ```

### Testlar
```bash
python -m unittest discover -s tests -v
```

---

## ☁️ Render.com'ga joylash (Free)

`render.yaml` tayyor. Render panelidagi **Environment** bo'limiga `BOT_TOKEN`, `GROQ_API_KEY`, `OWNER_ID` va (ixtiyoriy) `GOOGLE_SHEET_WEBHOOK_URL` ni kiriting.

**Free tarif cheklovlari:**
- **Uxlab qolish:** Render Free 15 daqiqa so'rov kelmasa xizmatni to'xtatadi. Bot buning oldini olish uchun har 10 daqiqada o'z `RENDER_EXTERNAL_URL/health` manziliga ping yuboradi (avtomatik). Qo'shimcha kafolat uchun [UptimeRobot](https://uptimerobot.com) kabi xizmatda shu manzilni 5 daqiqalik monitoringga qo'yish tavsiya etiladi.
- **Vaqtinchalik disk:** Free tarifda har deploy/qayta ishga tushishda `yordamchi_bot.db` va `leadlar.csv` **o'chib ketadi**. Murojaatlar tarixini doimiy saqlash uchun **Google Sheets ni albatta ulang** (yoki pullik tarifda disk ulab, `DB_PATH`/`CSV_PATH` ni o'sha diskka yo'naltiring).

---

## 📲 Telegram Business-ga ulash

1. Telegram dasturida **Sozlamalar** → **Telegram Business** → **Chatbotlar** bo'limiga kiring.
2. O'zingizning botingizni tanlang va ruxsat bering.
3. Botga kirib **/start** tugmasini bosing — hisobotlar sizga kela boshlaydi.
