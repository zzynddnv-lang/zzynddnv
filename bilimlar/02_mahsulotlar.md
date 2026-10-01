<!--
  MAHSULOTLAR: 3 YO'NALISH (bot shu fayldan o'qiydi). Aniq modellar, rasm va texnik ma'lumot - katalog.json
  (yangilash: python tools/katalog_yangilash.py). Model nomlari KIRILL yozuvida (saytdagidek).
  Manba: umatic.uz katalog va maqolalari. Narx va qoldiq bu yerga YOZILMAYDI.
  Fayl QISQA bo'lsin (Groq limiti).
-->
# 1. Elektr dvigatellar

Turlar:
- Umumsanoat asinxron (АИР, 0,25–200 kVt): nasos, ventilyator, kompressor, konveyer, stanok; ishlab chiqarish, kon, qurilish, kommunal xo'jalik. Ishonchli, kam xizmat talab qiladi.
- Kran-metallurgiya (МТН, МТКН, 5–60 kVt): kran va ko'tarish mexanizmlari. Tez-tez ishga tushirish/to'xtatishga va qisqa muddatli 2,5 martagacha ortiqcha yuklamaga chidaydi, chastota o'zgartirgich bilan ishlaydi. Namlik/changda IP54+.
- Portlashdan himoyalangan (ВА, ВАО, 4–5000 kVt): neft-gaz, kon, kimyo, don sanoati, shaxtalar. Himoya turini portlash xavfi darajasiga qarab muhandis tanlaydi.
- Sinxron (СД, СДМ, ВДС, СТДМ, 500–12 500 kVt, 6–10 kV): yirik nasos, kompressor, tegirmon; tezlik yuklamaga qaramay o'zgarmaydi.

Tanlash uchun so'raladi (1-2 va miqdor yetarli, qolgani "bilsangiz" deb bir marta):
1. Quvvat, kVt  2. Aylanish tezligi: 3000 / 1500 / 1000 / 750 ob/min (2/4/6/8 qutb)
3. Kuchlanish: 220/380 yoki 380/660 V  4. O'rnatish: oyoqli/lapali IM1081 ("на лапах"), flanesli IM3081 ("фланцевый"), aralash IM2081
5. Himoya: IP54/IP55; portlash xavfi bo'lsa Ex ("взрывозащищённый")  6. Mexanizm; eski dvigatel shildigi (pasport plastinkasi) — eng aniq tanlov

Tushuntirish uchun: nominal tezlik sinxrondan biroz past (1500 → ~1450 ob/min) — normal. Quvvat mexanizmdan biroz zaxira bilan tanlanadi: kichigi qiziydi, kattasi ortiqcha xarajat. Yulduz/uchburchak ulanish tarmoqqa qarab; katta quvvatda soft-starter yoki chastota o'zgartirgich. Izolyatsiya sinfi F. KPD va IE sinfi (IE2, IE3) yuqori — elektr sarfi kam. Katalogdagi modellarning IE sinfi ko'rsatilmagan: energiya tejash so'ralsa, katalogdagi aniq modelning KPD qiymatini ayt, seriyaga IE sinfini o'ylab topma. Noto'g'ri tanlangan dvigatel qiziydi, podshipnik va o'ram erta ishdan chiqadi.

# 2. Nasos agregatlari
- Quduq (skvajina) nasoslari ЭЦВ: quduqdan suv chiqarish (ichimlik suvi, sug'orish, sanoat). Nomi: ЭЦВ 8-25-100 — 8 dyuymli quduq uchun, 25 m³/soat sarf, 100 m napor.
- Ikki tomonlama kirishli Д: katta sarfli (yuzlab–minglab m³/soat) suv ta'minoti, sug'orish, sanoat nasos stansiyalari. Nomi: Д 320-50 — 320 m³/soat, 50 m.
- Konsol К: toza suv va neytral suyuqliklar, isitish, suv ta'minoti. Nomi: 1К 20/30 — 20 m³/soat, 30 m.
- Monoblok «Гном»: ifloslangan suv, drenaj, chuqurlardan suv chiqarish.
So'raladi: vazifasi (quduq, sug'orish, drenaj, sanoat), sarf (m³/soat), napor (m), suyuqlik turi; quduq uchun — quduq diametri va chuqurligi; miqdor.

# 3. Elektroizolyatsiya materiallari
- Mis emal sim ПЭТВ-2 (0,25 mm dan): elektr mashinalar, transformator va g'altak o'ramlari uchun. So'raladi: diametr (mm), miqdor (kg).
- Stator va yakor o'ram seksiyalari, stator sterjenlari, kollektorlar: dvigatel va generatorlar uchun BUYURTMA ASOSIDA tayyorlanadi. So'raladi: mashina markasi, quvvati, chizma yoki namuna.
- Kiper lenta: o'ram izolyatsiyasini tortib mahkamlash uchun, turli kengliklarda.
- Ish qo'lqoplari: trikotaj, PVX qoplamali, brezent, payvandchi (kragi), dielektrik.
