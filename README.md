# 🤖 Zuxriddin Yordamchisi - Telegram Business AI Bot

Ushbu bot Telegram Business hisobingizga kelgan yangi matnli va **ovozli (voice)** xabarlarga sun'iy intellekt (**Groq Llama 3.1 & Whisper**) orqali avtomatik javob beradi, mijoz haqidagi asosiy ma'lumotlarni aniqlaydi, suhbatlarni **SQLite** bazasida saqlaydi va sizga tayyor hisobot taqdim etadi.

---

## 📁 Papka tuzilmasi

```text
ai agent/
│
├── zuxriddin_yordamchi_bot.py   # Botning asosiy dastur kodi
├── database.py                  # SQLite ma'lumotlar bazasi moduli
├── yordamchi_bot.db             # Doimiy SQLite bazasi (avtomatik yaratiladi)
├── .env                         # Maxfiy tokenlar (Bot token, Groq API key)
├── .env.example                 # Sozlamalar namunasi
├── requirements.txt             # Kerakli Python kutubxonalari
├── run.bat                      # Windows uchun tezkor ishga tushirish fayli
├── leadlar.csv                  # Mijozlar bazasi zaxirasi (Excel)
├── .gitignore                   # Maxfiy va baza fayllarini himoyalash
└── README.md                    # Loyiha qo'llanmasi
```

---

## 🌟 Imkoniyatlar

1. **Telegram Business bilan to'liq integratsiya:** Shaxsiy akkauntingizga kelgan yangi xabarlarga avtomatik javob beradi.
2. **🎙 Ovozli xabarlarni tushunish (Voice-to-Text):** Mijoz ovozli xabar (voice note) yoki audio yuborsa, **Groq Whisper** modeli uni tezkorlik bilan matnga aylantiradi va muloqot uzilmaydi.
3. **💾 Doimiy xotira (SQLite):** Bot o'chib yonsa ham suhbatlar tarixi va mijozlar holati saqlanib qoladi.
4. **🔒 Poyga holatidan himoya (Concurrency Lock):** Ketma-ket kelgan xabarlar tartib bilan ishlanadi.
5. **🛡 Xavfsiz JSON parser:** Mijozga hech qachon xom dasturchi kodlari ko'rinib qolmaydi.
6. **👑 Bot egasi uchun buyruqlar:**
   - `/leads` — Oxirgi kelgan 5 ta mijozni botda ko'rish.
   - `/stats` — Baza statistikasi (jami leadlar, faol va yakunlangan suhbatlar).
   - `/reset <chat_id>` — Xohlagan chatni qayta faollashtirish (sinovlar uchun).
   - `/help` — Foydalanish bo'yicha yo'riqnoma.

---

## ⚙️ O'rnatish va Sozlash

### 1. Kutubxonalarni o'rnatish
```bash
pip install -r requirements.txt
```

### 2. Sozlamalarni tekshirish (.env)
`.env` faylida o'zingizning bot tokeningiz va Groq kalitingiz borligiga ishonch hosil qiling:
```env
BOT_TOKEN=8765266953:AAED...
GROQ_API_KEY=gsk_...
EGA_ISMI=Zuxriddin
MODEL=llama-3.1-8b-instant
```

---

## 🚀 Ishga tushirish

1. **Eng oson usul:** Papkadagi **`run.bat`** faylini ikki marta bosing.
2. **Terminal orqali:**
   ```bash
   python zuxriddin_yordamchi_bot.py
   ```

---

## 📲 Telegram Business-ga ulash

1. Telegram dasturida **Sozlamalar** -> **Telegram Business** -> **Chatbotlar** bo'limiga kiring.
2. O'zingizning botingizni tanlang va ruxsat bering.
3. Botingiz sizga hisobot yubora olishi uchun botning o'ziga kirib **/start** tugmasini bosing.
