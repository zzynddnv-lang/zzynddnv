# 🤖 Zuxriddin Yordamchisi - Telegram Business AI Bot

Ushbu bot Telegram Business hisobingizga kelgan yangi xabarlarga sun'iy intellekt (**Groq / Llama 3.1**) orqali avtomatik javob beradi, mijoz haqidagi asosiy ma'lumotlarni (ism, murojaat maqsadi, telefon raqami) aniqlaydi va sizga hisobot tariqasida taqdim etadi.

---

## 📁 Papka tuzilmasi

```text
ai agent/
│
├── zuxriddin_yordamchi_bot.py   # Botning asosiy kodi
├── .env                         # Maxfiy token va kalitlar (Bot token, Groq API key)
├── .env.example                 # Tokenlar uchun namuna fayl
├── requirements.txt             # Kerakli Python kutubxonalari
├── run.bat                      # Windows uchun tezkor ishga tushirish fayli
├── leadlar.csv                  # Mijozlar bazasi (bot ishga tushgach avtomatik yaratiladi)
├── .gitignore                   # Git uchun e'tiborsiz qoldiriladigan fayllar
└── README.md                    # Loyiha bo'yicha to'liq qo'llanma
```

---

## ⚙️ O'rnatish va Sozlash

### 1. Kutubxonalarni o'rnatish
VS Code terminalida quyidagi buyruqni bering:
```bash
pip install -r requirements.txt
```

### 2. Sozlamalarni tekshirish (.env)
Loyihadagi `.env` faylini oching va kerak bo'lsa sozlamalarni o'zgartiring:
- `BOT_TOKEN`: Telegram @BotFather bergan token.
- `GROQ_API_KEY`: Groq platformasidan olingan API kalit.
- `EGA_ISMI`: Sizning ismingiz (bot o'zini shu ism bilan tanishtiradi).
- `MODEL`: Groq modeli (standart: `llama-3.1-8b-instant`).

---

## 🚀 Ishga tushirish

Ikkita qulay usuldan birini tanlang:

### 1-usul: Tayyor fayl orqali (eng oson)
Papkadagi **`run.bat`** faylini ikki marta bosing. Konsol oynasi ochilib, bot avtomatik ishga tushadi.

### 2-usul: VS Code terminali orqali
Terminalda quyidagi buyruqni bajaring:
```bash
python zuxriddin_yordamchi_bot.py
```

---

## 📲 Telegram Business-ga ulash bo'yicha qo'llanma

Bot sizning shaxsiy Telegram profilingizga kelgan xabarlarga javob berishi uchun quyidagi bosqichlarni bajaring:

1. **Telegram Premium** obunasiga ega bo'lishingiz kerak.
2. Telegram dasturida **Sozlamalar (Settings)** bo'limiga kiring.
3. **Telegram Business** -> **Chatbotlar (Chatbots)** bo'limini oching.
4. Qidiruvga botingizning username'ini (masalan: `@sizning_botingiz`) yozing va uni tanlang.
5. Botga xabarlarni o'qish va javob yuborish ruxsatini bering.
6. **MUHIM:** Bot sizga yangi mijozlar hisobotini yuborishi uchun o'zingiz Telegram orqali shu botga kirib **/start** tugmasini bosib qo'ying.

---

## 📊 Natijalar qayerga saqlanadi?

1. **Telegram orqali:** Suhbat yakunlanishi bilan bot sizning shaxsiy chatingizga mijoz haqida hisobot xabarini yuboradi.
2. **Excel/CSV orqali:** Papkada avtomatik tarzda **`leadlar.csv`** fayli shakllanadi va har bir yangi murojaat jadvalga yozib boriladi.
