"""
Savdo boti uchun testlar (standart unittest, qo'shimcha paket kerak emas).

Ishga tushirish:
    python -m unittest discover -s tests -v
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

# Testlar vaqtinchalik baza va sozlamalar bilan ishlaydi (haqiqiy bazaga va webhook'ga tegmaydi)
_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["CSV_PATH"] = os.path.join(_TMP, "test.csv")
os.environ["OWNER_ID"] = "111, 222"
os.environ["SKLAD_CHAT_ID"] = "-100500"
os.environ["GOOGLE_SHEET_WEBHOOK_URL"] = ""  # .env dagi haqiqiy webhook ishlatilmasin
os.environ["KATTA_BUYURTMA_CHEGARASI"] = "100000000"
os.environ["OLDINDAN_TOLOV_FOIZI"] = "50"
os.environ["NARX_IZOHI"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402
import sotuv  # noqa: E402
import taklif_pdf  # noqa: E402
import zuxriddin_yordamchi_bot as b  # noqa: E402

# Testlarda "tabiiy tezlik" kutishi o'chiriladi (testlar tez ishlashi uchun)
b.TABIIY_MIN = b.TABIIY_MAX = 0


def rejim_qoy(test: unittest.TestCase, rejim: str):
    """Test davomida taklif rejimini o'rnatadi (mavjudlik / narx / darhol) va oxirida qaytaradi."""
    eski = (b.TAKLIF_REJIMI, b.NARX_OMBORDAN, b.OMBOR_ORQALI)
    b.TAKLIF_REJIMI, b.NARX_OMBORDAN, b.OMBOR_ORQALI = rejim, rejim == "narx", rejim in ("mavjudlik", "narx")

    def qaytar():
        b.TAKLIF_REJIMI, b.NARX_OMBORDAN, b.OMBOR_ORQALI = eski

    test.addCleanup(qaytar)


class TezlikTest(unittest.TestCase):
    """Token tejash (katalogdan faqat kerakli qism) va aqlli kutish."""

    @classmethod
    def setUpClass(cls):
        b.bilimlarni_yuklash()

    def test_katalog_bilimlarga_qoshilmaydi_alohida_yuklanadi(self):
        bilim = b.bilimlarni_yuklash()
        self.assertNotIn("АИР132М4У1", bilim)
        self.assertEqual(set(b.KATALOG), {"AIR", "MTN", "VA", "SD", "ECV", "D", "K", "KM", "PROVOD", "STATOR", "LENTA", "PERCHATKA"})
        self.assertEqual(sum(len(v) for v in b.KATALOG.values()), 104)

    def test_umumiy_savolda_katalog_yuborilmaydi(self):
        self.assertEqual(sotuv.katalog_tanlash(b.KATALOG, "salom, yaxshimisiz, sizlar nima qilasizlar"), "")

    def test_quvvat_boyicha_yaqin_modellar(self):
        k = sotuv.katalog_tanlash(b.KATALOG, "11 kVt 1500 aylanishli dvigatel kerak")
        self.assertIn("АИР132М4У1", k)
        self.assertNotIn("ВАО-5000", k)
        self.assertLess(len(k), 1200)

    def test_tur_boyicha(self):
        self.assertIn("МТН", sotuv.katalog_tanlash(b.KATALOG, "kran uchun dvigatel"))
        self.assertIn("ВА225М6", sotuv.katalog_tanlash(b.KATALOG, "нужен взрывозащищённый 37 кВт"))
        self.assertIn("СДВ", sotuv.katalog_tanlash(b.KATALOG, "sinxron dvigatel kerak"))

    def test_xato_mosliklar_yoq(self):
        # "va" bog'lovchisi, "экран", "магазин" - katalog bo'limini tanlamasligi kerak
        self.assertEqual(sotuv.katalog_tanlash(b.KATALOG, "men va do'stim keldik"), "")
        self.assertEqual(sotuv.katalog_tanlash(b.KATALOG, "экран и магазин"), "")

    def test_kilovolt_quvvat_emas(self):
        # "6 кВ" - yuqori kuchlanish: sinxron bo'lim to'liq tanlanadi, 6 kVt deb filtrlanmaydi
        k = sotuv.katalog_tanlash(b.KATALOG, "kuchlanish 6 кВ")
        self.assertIn("ВДС-375", k)  # 12 500 kVt - 6 kVt ga "yaqin" deb tashlab yuborilmagan

    def test_kutish_vaqti(self):
        self.assertAlmostEqual(b._kutish_vaqti(RuntimeError("Please try again in 6.008s.")), 6.508, places=2)
        self.assertEqual(b._kutish_vaqti(RuntimeError("try again in 1m30s")), 20.0)  # ko'pi bilan 20 s
        self.assertEqual(b._kutish_vaqti(RuntimeError("try again in 0.2s")), 2.0)
        self.assertEqual(b._kutish_vaqti(RuntimeError("boshqa xato")), float(b.LIMIT_KUTISH))


POZ = [
    {"nomi": "Elektr dvigatel", "parametrlar": "15 kVt, 1500 ob/min", "miqdor": 3, "birlik": "dona"},
    {"nomi": "Nasos", "parametrlar": "", "miqdor": 1, "birlik": "dona"},
]


def ai_json(**ozgarish) -> str:
    data = {
        "javob": "Qanday quvvatdagi dvigatel kerak?", "til": "uz_latn",
        "mijoz": {"ism": "", "telefon": "", "kompaniya": "", "lavozim": "", "soha": ""},
        "ehtiyoj": "", "mahsulotlar": [], "narx_sorash": False, "buyurtma_tasdiqlandi": False,
        "bosqich": "qiziqish", "harorat": "iliq", "menejer_kerak": False, "menejer_sababi": "", "xulosa": "",
    }
    data.update(ozgarish)
    return json.dumps(data, ensure_ascii=False)


class AiNatijaTest(unittest.TestCase):
    def test_toza_json(self):
        n = sotuv.ai_natijasini_ajratish(ai_json(mahsulotlar=POZ, narx_sorash=True))
        self.assertEqual(n["javob"], "Qanday quvvatdagi dvigatel kerak?")
        self.assertTrue(n["narx_sorash"])
        self.assertEqual(len(n["mahsulotlar"]), 2)

    def test_think_va_markdown(self):
        n = sotuv.ai_natijasini_ajratish("<think>fikr</think>```json\n" + ai_json() + "\n```")
        self.assertIsNotNone(n)

    def test_yaroqsiz_json_mijozga_ketmaydi(self):
        self.assertIsNone(sotuv.ai_natijasini_ajratish('{"til": "ru"}'))
        self.assertIsNone(sotuv.ai_natijasini_ajratish(""))

    def test_buzilgan_jsondan_javob(self):
        n = sotuv.ai_natijasini_ajratish('{"javob": "Salom, yordam beraman", "til": "uz_la')
        self.assertEqual(n["javob"], "Salom, yordam beraman")
        self.assertFalse(n["narx_sorash"])

    def test_notogri_turlar_tozalanadi(self):
        n = sotuv.ai_natijasini_ajratish(ai_json(
            til="en", bosqich="nomalum", narx_sorash="true",
            mahsulotlar=[{"nomi": "", "miqdor": 2}, {"nomi": "Nasos", "miqdor": "5 dona"}, "xato"],
        ))
        self.assertEqual(n["til"], "")
        self.assertEqual(n["bosqich"], "")
        self.assertFalse(n["narx_sorash"])  # faqat haqiqiy true qabul qilinadi
        self.assertEqual(n["mahsulotlar"], [{"nomi": "Nasos", "parametrlar": "", "miqdor": 5, "birlik": "dona"}])

    def test_bosqich_orqaga_ketmaydi(self):
        self.assertEqual(sotuv.bosqichni_birlashtirish("taklif_berildi", "qiziqish"), "taklif_berildi")
        self.assertEqual(sotuv.bosqichni_birlashtirish("qiziqish", "narx_sorovi"), "narx_sorovi")
        self.assertEqual(sotuv.bosqichni_birlashtirish("taklif_berildi", "rad_etdi"), "rad_etdi")
        self.assertEqual(sotuv.bosqichni_birlashtirish("muzokara", ""), "muzokara")

    def test_sxema_strict_talablari(self):
        def tekshir(s):
            if s.get("type") == "object":
                self.assertFalse(s["additionalProperties"])
                self.assertEqual(set(s["required"]), set(s["properties"]))
                for v in s["properties"].values():
                    tekshir(v)
            elif s.get("type") == "array":
                tekshir(s["items"])
        tekshir(sotuv.JAVOB_SXEMASI)


class OmborJavobiTest(unittest.TestCase):
    def test_oddiy_narxlar(self):
        j = sotuv.ombor_javobini_tahlil("12 500 000 ; 2\n4.2 mln", POZ)
        self.assertEqual(j.narxlar, [{"narx": 12_500_000, "mavjud": 2}, {"narx": 4_200_000, "mavjud": 1}])

    def test_formatlar(self):
        for qator, kutilgan in [
            ("12500000", 12_500_000), ("12 500 000", 12_500_000), ("12.500.000", 12_500_000),
            ("12,5 mln", 12_500_000), ("12.5млн", 12_500_000), ("800 ming", 800_000), ("1) 3 400 000", 3_400_000),
        ]:
            j = sotuv.ombor_javobini_tahlil(qator, POZ[:1])
            self.assertEqual(j.narxlar[0]["narx"], kutilgan, qator)

    def test_yoq_va_izoh(self):
        j = sotuv.ombor_javobini_tahlil("yo'q\n5 000 000 ; 1\nizoh: yetkazib berish 2 kun", POZ)
        self.assertEqual(j.narxlar[0], {"narx": 0, "mavjud": 0})
        self.assertEqual(j.izoh, "yetkazib berish 2 kun")

    def test_qator_soni_mos_emas(self):
        with self.assertRaises(ValueError):
            sotuv.ombor_javobini_tahlil("12 500 000", POZ)

    def test_noaniq_qator_rad_etiladi(self):
        # "12 500 000 100" - narx 12 500 000 va 100 dona, yoki 12 500 000 100 so'mmi? Ajratuvchisiz qabul qilinmaydi.
        with self.assertRaises(ValueError):
            sotuv.ombor_javobini_tahlil("12500000 100", POZ[:1])

    def test_juda_kichik_narx(self):
        with self.assertRaises(ValueError):
            sotuv.ombor_javobini_tahlil("12.5", POZ[:1])  # "mln" unutilgan

    def test_bosh_matn(self):
        with self.assertRaises(ValueError):
            sotuv.ombor_javobini_tahlil("narxi keyin", POZ[:1])


class TolovVaTaklifTest(unittest.TestCase):
    def test_tolov_chegarasi(self):
        self.assertEqual(sotuv.tolov_qismlari(100_000_000), (100_000_000, 0))  # "oshsa" - teng emas
        self.assertEqual(sotuv.tolov_qismlari(100_000_001), (50_000_000, 50_000_001))
        oldindan, qolgan = sotuv.tolov_qismlari(150_000_000)
        self.assertEqual((oldindan, qolgan), (75_000_000, 75_000_000))
        self.assertEqual(oldindan + qolgan, 150_000_000)

    def test_qisman_mavjud_hisob(self):
        narxlar = [{"narx": 40_000_000, "mavjud": 2}, {"narx": 0, "mavjud": 0}]
        hisob, jami = sotuv.hisoblash(POZ, narxlar)
        self.assertEqual(jami, 80_000_000)
        self.assertEqual(hisob[0]["sotiladi"], 2)
        self.assertEqual(hisob[1]["sotiladi"], 0)

    def test_taklif_matni_katta_summa(self):
        narxlar = [{"narx": 40_000_000, "mavjud": 3}, {"narx": 5_000_000, "mavjud": 1}]
        matn, jami = sotuv.taklif_matni(7, POZ, narxlar, "uz_latn")
        self.assertEqual(jami, 125_000_000)
        self.assertIn("125 000 000 so'm", matn)
        self.assertIn("50% oldindan (62 500 000 so'm)", matn)
        self.assertIn("№7", matn)

    def test_taklif_matni_kichik_summa_rus(self):
        narxlar = [{"narx": 1_000_000, "mavjud": 1}, {"narx": 0, "mavjud": 0}]
        matn, jami = sotuv.taklif_matni(3, POZ, narxlar, "ru")
        self.assertEqual(jami, 1_000_000)
        self.assertIn("100% предоплата", matn)
        self.assertIn("в наличии 1", matn)
        self.assertIn("пока нет в наличии", matn)

    def test_barcha_tillar(self):
        for til in sotuv.TILLAR:
            matn, _ = sotuv.taklif_matni(1, POZ, [{"narx": 2_000_000, "mavjud": 3}, {"narx": 1_000_000, "mavjud": 1}], til)
            self.assertIn("7 000 000", matn)


class NarxHimoyasiVaTilTest(unittest.TestCase):
    def test_narx_aniqlanadi(self):
        self.assertTrue(sotuv.narx_aytilganmi("Bu dvigatel narxi 12 500 000 so'm"))
        self.assertTrue(sotuv.narx_aytilganmi("Цена около 5 млн"))
        self.assertTrue(sotuv.narx_aytilganmi("Taxminan 300$ turadi"))

    def test_tolov_sharti_narx_emas(self):
        self.assertFalse(sotuv.narx_aytilganmi("Summa 100 mln so'mdan oshsa, 50% oldindan to'lanadi"))
        self.assertFalse(sotuv.narx_aytilganmi("15 kVt, 1500 ob/min, 380 V dvigatel kerakmi? 1–3 kunda yetkazamiz"))

    def test_til(self):
        self.assertEqual(sotuv.tilni_aniqlash("Assalomu alaykum, nasos kerak"), "uz_latn")
        self.assertEqual(sotuv.tilni_aniqlash("Ассалому алайкум, насос керак"), "uz_cyrl")
        self.assertEqual(sotuv.tilni_aniqlash("Шунга клиент сўралган маълумотлар"), "uz_cyrl")
        self.assertEqual(sotuv.tilni_aniqlash("Здравствуйте, нужен насос"), "ru")

    def test_qisqa_xabarda_oldingi_til(self):
        self.assertEqual(sotuv.tilni_aniqlash("ok", "ru"), "ru")
        self.assertEqual(sotuv.tilni_aniqlash("5", "uz_cyrl"), "uz_cyrl")
        self.assertEqual(sotuv.tilni_aniqlash("хоп", "uz_cyrl"), "uz_cyrl")

    def test_yozuv_tekshiruvi(self):
        self.assertTrue(sotuv.yozuv_mosmi("Qanday quvvatdagi dvigatel kerak? 15 kVt, IP55", "uz_latn"))
        self.assertFalse(sotuv.yozuv_mosmi("Какой насос вам нужен для полива?", "uz_latn"))
        self.assertFalse(sotuv.yozuv_mosmi("Qanday nasos kerak sug'orish uchun?", "ru"))
        self.assertTrue(sotuv.yozuv_mosmi("Двигател 15 kVt, 380 V, IP55 керакми?", "uz_cyrl"))

    def test_javob_salomi_ikkilanmaydi(self):
        self.assertEqual(sotuv.salomni_moslash("Va alaykum assalom! Nasos kerakmi?", True, "uz_latn"),
                         "Va alaykum assalom! Nasos kerakmi?")
        self.assertEqual(sotuv.salomni_moslash("Ва алайкум ассалом! Қайси?", False, "uz_cyrl"), "Қайси?")

    def test_narx_sorash_mumkinmi(self):
        self.assertTrue(sotuv.narx_sorash_mumkinmi([{"nomi": "Nasos", "parametrlar": "30 m³/soat, 60 m", "miqdor": 2, "birlik": "dona"}]))
        self.assertTrue(sotuv.narx_sorash_mumkinmi(POZ[:1]))  # 15 kVt, 1500 ob/min, 3 dona
        self.assertFalse(sotuv.narx_sorash_mumkinmi([{"nomi": "Dvigatel", "parametrlar": "11 kVt", "miqdor": 4, "birlik": "dona"}]))
        self.assertFalse(sotuv.narx_sorash_mumkinmi([{**POZ[0], "miqdor": 0}]))
        self.assertFalse(sotuv.narx_sorash_mumkinmi([]))

    def test_takrorlanish(self):
        eski = ["Jasur aka, ma'lumotlaringizni qabul qildik. 4 dona dvigatel uchun narx so'rovi yuborilmoqda, tez orada taklifni yuboramiz."]
        yangi = "Jasur aka, ma'lumotlaringizni qabul qildik. 4 dona asinxron dvigatel uchun narx so'rovi yuborilmoqda, tez orada taklifni yuboramiz."
        self.assertTrue(sotuv.takrorlanganmi(yangi, eski))
        self.assertFalse(sotuv.takrorlanganmi("Telefon raqamingizni yozib qoldirasizmi, taklifni shu raqamga ham yuboramiz?", eski))
        self.assertFalse(sotuv.takrorlanganmi("Nechta kerak?", ["Nechta kerak?"]))  # qisqa savol mumkin

    def test_birinchi_rahmat_qoladi(self):
        javob = "Rahmat, Bahodir! Narxni omborga so'radim."
        self.assertEqual(sotuv.takroriy_rahmatni_olib_tashlash(javob, False, "Bahodir"), javob)

    def test_takroriy_rahmat_olib_tashlanadi(self):
        for javob, kutilgan in [
            ("Rahmat! Qanday kuchlanish kerak?", "Qanday kuchlanish kerak?"),
            ("Ma'lumot uchun katta rahmat, Bahodir! Nechta kerak?", "Nechta kerak?"),
            ("Tushundim, rahmat. IP himoya kerakmi?", "IP himoya kerakmi?"),
            ("Rahmat, endi narxni omborga so'rayman.", "Endi narxni omborga so'rayman."),
            ("Спасибо за информацию! Какое напряжение?", "Какое напряжение?"),
            ("Раҳмат! Қайси кучланиш керак?", "Қайси кучланиш керак?"),
            ("Qanday kuchlanish kerak? Oldindan rahmat!", "Qanday kuchlanish kerak?"),
            ("Nechta kerak? Rahmat.", "Nechta kerak?"),
        ]:
            self.assertEqual(sotuv.takroriy_rahmatni_olib_tashlash(javob, True, "Bahodir"), kutilgan, javob)

    def test_rahmatsiz_javob_ozgarmaydi(self):
        javob = "Qanday kuchlanish kerak? 380 V yoki 220 V?"
        self.assertEqual(sotuv.takroriy_rahmatni_olib_tashlash(javob, True), javob)

    def test_faqat_rahmat_bosh_qolmaydi(self):
        self.assertEqual(sotuv.takroriy_rahmatni_olib_tashlash("Rahmat!", True), "Rahmat!")

    def test_salom(self):
        self.assertTrue(sotuv.salomni_moslash("Qanday uskuna kerak?", True, "uz_latn").startswith("Assalomu alaykum!"))
        self.assertTrue(sotuv.salomni_moslash("Какой насос?", True, "ru").startswith("Здравствуйте!"))
        self.assertEqual(sotuv.salomni_moslash("Assalomu alaykum! yaxshi.", False, "uz_latn"), "Yaxshi.")
        self.assertEqual(sotuv.salomni_moslash("Salomatlik muhim.", False, "uz_latn"), "Salomatlik muhim.")


class HuquqlarTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        b.egalar.clear()

    def test_owner_id(self):
        self.assertTrue(b.egami(111))
        self.assertFalse(b.egami(999))
        self.assertFalse(b.egami(None))

    def test_bazadagi_begona_ega_emas(self):
        db.save_owner_id(999)
        self.assertFalse(b.egami(999))
        self.assertNotIn(999, b.hisobot_oluvchilar(None))

    def test_ombor_ruxsati(self):
        self.assertEqual(b.ombor_chatlari(), [-100500])
        self.assertTrue(b.omborga_ruxsat(555, -100500))   # ombor guruhi a'zosi
        self.assertFalse(b.omborga_ruxsat(555, 12345))    # begona chat
        self.assertTrue(b.omborga_ruxsat(111, 12345))     # ega istalgan joyda

    def test_bilimlar_izohsiz(self):
        bilim = b.bilimlarni_yuklash()
        self.assertIn("UMATIC", bilim)
        self.assertNotIn("<!--", bilim)
        self.assertNotIn("TO'LDIRING", bilim)
        self.assertLess(len(bilim), 12000)


class BazaTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.get_db() as conn:
            conn.execute("DELETE FROM leads")
            conn.execute("DELETE FROM sorovlar")

    def test_lead_dublikatsiz_va_bosh_qiymat_ochirmaydi(self):
        self.assertTrue(db.upsert_lead(42, full_name="Ali", telegram_id=42, telefon="+998901234567"))
        self.assertFalse(db.upsert_lead(42, full_name="Ali", telegram_id=42, telefon="", mavzu="Nasos"))
        leadlar = db.get_all_leads()
        self.assertEqual(len(leadlar), 1)
        self.assertEqual(leadlar[0]["telefon"], "+998901234567")
        self.assertEqual(leadlar[0]["mavzu"], "Nasos")

    def test_nomalum_maydon(self):
        with self.assertRaises(ValueError):
            db.upsert_lead(1, parol="x")

    def test_eski_ustunlar_olib_tashlanadi(self):
        with db.get_db() as conn:
            try:
                conn.execute("ALTER TABLE leads ADD COLUMN zamer TEXT")
            except sqlite3.OperationalError:
                pass
        db.init_db()
        with db.get_db() as conn:
            ustunlar = {r["name"] for r in conn.execute("PRAGMA table_info(leads)")}
        self.assertNotIn("zamer", ustunlar)
        self.assertIn("bosqich", ustunlar)

    def test_sorov_holati_atomar(self):
        sid = db.create_sorov(5, 5, None, "ru", json.dumps(POZ), "k", "")
        self.assertEqual(db.get_faol_sorov(5)["id"], sid)
        self.assertTrue(db.sorov_holatini_ozgartirish(sid, db.FAOL_SOROV_HOLATLARI, "narx_kiritilmoqda"))
        self.assertTrue(db.sorov_holatini_ozgartirish(sid, ("narx_kiritilmoqda",), "tasdiq_kutilmoqda"))
        # "Mijozga yuborish" ikki marta bosildi - faqat birinchisi o'tadi
        self.assertTrue(db.sorov_holatini_ozgartirish(sid, ("tasdiq_kutilmoqda",), "yuborilmoqda"))
        self.assertFalse(db.sorov_holatini_ozgartirish(sid, ("tasdiq_kutilmoqda",), "yuborilmoqda"))
        db.sorov_holatini_ozgartirish(sid, ("yuborilmoqda",), "yuborildi")
        self.assertIsNone(db.get_faol_sorov(5))
        self.assertEqual(db.get_oxirgi_taklif(5)["id"], sid)

    def test_menejer_spamdan_himoya(self):
        self.assertTrue(db.menejer_chaqirish_mumkinmi(77, 60))
        self.assertFalse(db.menejer_chaqirish_mumkinmi(77, 60))

    def test_csv_eksport(self):
        db.upsert_lead(7, full_name="Vali", telegram_id=7, xulosa="xulosa, vergul bilan", bosqich="narx_sorovi")
        self.assertTrue(asyncio.run(b.csv_yangilash()))
        with open(os.environ["CSV_PATH"], encoding="utf-8-sig") as f:
            qatorlar = f.read().splitlines()
        self.assertEqual(len(qatorlar), 2)
        self.assertIn("Vali", qatorlar[1])

    def test_sheets_sozlanmagan(self):
        self.assertIsNone(asyncio.run(b.google_sheetsga_yozish({"ism": "x"})))


class SotuvOqimiTest(unittest.TestCase):
    """Ombor rejimi (NARX_OMBORDAN=1): mijoz -> so'rov -> ombor narxi -> taklif."""

    def setUp(self):
        rejim_qoy(self, "narx")
        db.init_db()
        with db.get_db() as conn:
            for t in ("leads", "sorovlar", "messages", "chats"):
                conn.execute(f"DELETE FROM {t}")
        self.yuborilgan = []

        async def send_message(chat_id, text, **kw):
            self.yuborilgan.append((chat_id, text, kw))
            return SimpleNamespace(message_id=len(self.yuborilgan))

        b.bot = SimpleNamespace(send_message=send_message, id=999)
        self.mijoz = SimpleNamespace(id=5001, username="ali", full_name="Ali Valiyev")

    def _natija(self, **ozgarish):
        n = sotuv.ai_natijasini_ajratish(ai_json(**ozgarish))
        n["_birinchi"] = False
        return n

    def test_narx_sorovi_bir_marta_yaratiladi(self):
        n = self._natija(mahsulotlar=POZ, narx_sorash=True, bosqich="narx_sorovi", mijoz={
            "ism": "Ali", "telefon": "", "kompaniya": "Zavod", "lavozim": "", "soha": ""})

        async def oqim():
            await b.crm_yangilash(10, self.mijoz, n, {"faol": None, "taklif": None}, "90 123 45 67", None, None)
            holat = b.suhbat_holati(10)
            await b.crm_yangilash(10, self.mijoz, n, holat, "yana", None, None)

        asyncio.run(oqim())
        with db.get_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sorovlar").fetchone()[0], 1)
        lead = db.get_lead(10)
        self.assertEqual(lead["telefon"], "90 123 45 67")
        self.assertEqual(lead["bosqich"], "narx_sorovi")
        ombor_xabarlari = [x for x in self.yuborilgan if x[0] == -100500]
        self.assertEqual(len(ombor_xabarlari), 1)
        self.assertIn("NARX SO'ROVI #", ombor_xabarlari[0][1])

    def test_miqdorsiz_sorov_yaratilmaydi(self):
        n = self._natija(mahsulotlar=[{**POZ[0], "miqdor": 0}], narx_sorash=True)
        asyncio.run(b.crm_yangilash(11, self.mijoz, n, {"faol": None, "taklif": None}, "dvigatel kerak", None, None))
        self.assertIsNone(db.get_faol_sorov(11))

    def test_ozgargan_sorov_eskisini_bekor_qiladi(self):
        n1 = self._natija(mahsulotlar=POZ[:1], narx_sorash=True)
        n2 = self._natija(mahsulotlar=POZ, narx_sorash=True)

        async def oqim():
            await b.crm_yangilash(12, self.mijoz, n1, {"faol": None, "taklif": None}, "", None, None)
            await b.crm_yangilash(12, self.mijoz, n2, b.suhbat_holati(12), "", None, None)

        asyncio.run(oqim())
        with db.get_db() as conn:
            holatlar = [r[0] for r in conn.execute("SELECT holat FROM sorovlar WHERE chat_id = 12 ORDER BY id")]
        self.assertEqual(holatlar, ["bekor", "kutilmoqda"])

    def test_taklifsiz_buyurtma_tasdiqi_etiborsiz(self):
        n = self._natija(buyurtma_tasdiqlandi=True, bosqich="kelishildi", mahsulotlar=POZ)
        asyncio.run(b.crm_yangilash(13, self.mijoz, n, {"faol": None, "taklif": None}, "ha", None, None))
        # AI "kelishildi" desa ham, taklif yuborilmagan bo'lsa - egaga "buyurtma tasdiqlandi" ketmaydi
        self.assertIsNone(db.get_oxirgi_taklif(13))
        self.assertEqual(db.get_lead(13)["bosqich"], "muzokara")
        self.assertFalse(any("BUYURTMANI TASDIQLADI" in x[1] for x in self.yuborilgan))

    def test_ombor_javobi_filtri(self):
        sid = db.create_sorov(14, 5001, None, "uz_latn", json.dumps(POZ), "k", "")
        prompt = b._narx_kiritish_korsatmasi(sid, POZ)
        import re as _re
        reply = SimpleNamespace(from_user=SimpleNamespace(id=999), text=_re.sub(r"<[^>]+>", "", prompt))
        xabar = SimpleNamespace(reply_to_message=reply, text="1 000 000", chat=SimpleNamespace(id=-100500))
        natija = asyncio.run(b.OmborJavobiFilter()(xabar))
        self.assertEqual(natija["sorov"]["id"], sid)
        # Mijoz botning oddiy xabariga reply qilsa - ombor javobi deb hisoblanmaydi
        reply2 = SimpleNamespace(from_user=SimpleNamespace(id=999), text="Qanday uskuna kerak?")
        xabar2 = SimpleNamespace(reply_to_message=reply2, text="nasos", chat=SimpleNamespace(id=5001))
        self.assertFalse(asyncio.run(b.OmborJavobiFilter()(xabar2)))


class PdfTaklifTest(unittest.TestCase):
    """Narxsiz rejim (standart): pozitsiya va miqdor aniq bo'lsa mijozga UMATIC PDF taklifi yuboriladi."""

    def setUp(self):
        rejim_qoy(self, "darhol")  # darhol narxsiz PDF rejimi
        db.init_db()
        with db.get_db() as conn:
            for t in ("leads", "sorovlar", "messages", "chats"):
                conn.execute(f"DELETE FROM {t}")
        self.xabarlar, self.hujjatlar = [], []

        async def send_message(chat_id, text, **kw):
            self.xabarlar.append((chat_id, text, kw))
            return SimpleNamespace(message_id=len(self.xabarlar))

        async def send_document(chat_id, document, caption=None, **kw):
            self.hujjatlar.append((chat_id, document, caption, kw))
            return SimpleNamespace(message_id=1)

        b.bot = SimpleNamespace(send_message=send_message, send_document=send_document, id=999)
        self.mijoz = SimpleNamespace(id=6001, username="jasur", full_name="Jasur")

    def _natija(self, **ozgarish):
        n = sotuv.ai_natijasini_ajratish(ai_json(**ozgarish))
        n["_birinchi"] = False
        return n

    def _mijozga(self, chat_id):
        return [x for x in self.hujjatlar if x[0] == chat_id]

    def test_pdf_yaratiladi_va_ochiladi(self):
        for til in ("uz_latn", "uz_cyrl", "ru"):
            pdf = taklif_pdf.taklif_pdf(5, til, POZ, "Jasur", "Kon <zavod> & Co", "+998901234567", "Predmet")
            self.assertTrue(pdf.startswith(b"%PDF"), til)
            self.assertGreater(len(pdf), 5000)
        self.assertEqual(taklif_pdf.taklif_raqami(12), "UM-00012")
        self.assertTrue(taklif_pdf.fayl_nomi(12, "ru").startswith("UMATIC_Kommercheskoe"))

    def test_pdf_taklif_mijozga_va_egaga(self):
        n = self._natija(mahsulotlar=POZ, narx_sorash=True, til="uz_latn",
                         mijoz={"ism": "Jasur", "telefon": "", "kompaniya": "NKMK", "lavozim": "", "soha": ""})
        asyncio.run(b.crm_yangilash(30, self.mijoz, n, {"faol": None, "taklif": None}, "+998 91 234 56 78", "biz-1", None))
        mijozga = self._mijozga(30)
        self.assertEqual(len(mijozga), 1)
        self.assertTrue(mijozga[0][1].data.startswith(b"%PDF"))
        self.assertIn("UM-", mijozga[0][2])
        self.assertEqual(mijozga[0][3]["business_connection_id"], "biz-1")
        # Egalarga (OWNER_ID: 111, 222) nusxa
        self.assertEqual({x[0] for x in self.hujjatlar} - {30}, {111, 222})
        taklif = db.get_oxirgi_taklif(30)
        self.assertIsNotNone(taklif)
        self.assertIsNone(taklif["narxlar"])
        self.assertEqual(db.get_lead(30)["bosqich"], "taklif_berildi")
        # Omborga hech narsa ketmaydi
        self.assertFalse(any(x[0] == -100500 for x in self.xabarlar + self.hujjatlar))

    def test_takroriy_taklif_yuborilmaydi_ozgarsa_yangisi(self):
        n = self._natija(mahsulotlar=POZ, narx_sorash=True)

        async def oqim():
            await b.crm_yangilash(31, self.mijoz, n, {"faol": None, "taklif": None}, "", None, None)
            await b.crm_yangilash(31, self.mijoz, n, b.suhbat_holati(31), "", None, None)
            n2 = self._natija(mahsulotlar=POZ[:1], narx_sorash=True)
            await b.crm_yangilash(31, self.mijoz, n2, b.suhbat_holati(31), "", None, None)

        asyncio.run(oqim())
        self.assertEqual(len(self._mijozga(31)), 2)

    def test_yuborib_bolmasa_egaga_ogohlantirish(self):
        async def xato(chat_id, document, caption=None, **kw):
            if chat_id == 32:
                raise b.TelegramAPIError(method=None, message="BUSINESS_PEER_USAGE_MISSING")
            self.hujjatlar.append((chat_id, document, caption, kw))

        b.bot.send_document = xato
        n = self._natija(mahsulotlar=POZ, narx_sorash=True)
        asyncio.run(b.crm_yangilash(32, self.mijoz, n, {"faol": None, "taklif": None}, "", None, None))
        self.assertIsNone(db.get_oxirgi_taklif(32))
        self.assertTrue(any("YUBORILMADI" in (x[2] or "") for x in self.hujjatlar))

    def test_narxsiz_taklifdan_keyin_ham_narx_aytilmaydi(self):
        sid = db.create_sorov(33, 1, None, "uz_latn", json.dumps(POZ), "k", "")
        db.sorov_holatini_ozgartirish(sid, ("kutilmoqda",), "yuborildi")
        holat = b.suhbat_holati(33)
        self.assertIn("narxsiz", b.holat_matni(holat, False))
        yolgon = ai_json(javob="Bu dvigatel 3 mln so'm turadi")

        async def create(**kw):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=yolgon))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"):
            n = asyncio.run(b.ai_javob([{"role": "user", "content": "narxi?"}], holat))
        self.assertFalse(sotuv.narx_aytilganmi(n["javob"]))


class OmborOqimiTest(unittest.TestCase):
    """Ombor tugmalari va narx kiritish - soxta Telegram obyektlari bilan to'liq oqim."""

    SKLAD = -100500
    MIJOZ_CHAT = 20

    def setUp(self):
        rejim_qoy(self, "narx")
        db.init_db()
        with db.get_db() as conn:
            for t in ("leads", "sorovlar", "messages", "chats"):
                conn.execute(f"DELETE FROM {t}")
        self.yuborilgan = []

        async def send_message(chat_id, text, **kw):
            self.yuborilgan.append((chat_id, text, kw))
            return SimpleNamespace(message_id=100 + len(self.yuborilgan))

        b.bot = SimpleNamespace(send_message=send_message, id=999)
        db.upsert_lead(self.MIJOZ_CHAT, full_name="Ali", telegram_id=7, bosqich="narx_sorovi")
        self.sid = db.create_sorov(self.MIJOZ_CHAT, 7, "biz-conn-1", "uz_latn", json.dumps(POZ), "k", "")

    def _callback(self, data, user_id=555, chat_id=None):
        javoblar = []

        async def answer(text=None, show_alert=False):
            javoblar.append(text)

        async def noop(*a, **kw):
            return None

        async def reply(text, **kw):
            self.yuborilgan.append(("reply", text, kw))

        msg = SimpleNamespace(chat=SimpleNamespace(id=chat_id or self.SKLAD), message_id=50, html_text="so'rov",
                              edit_text=noop, edit_reply_markup=noop, reply=reply)
        cb = SimpleNamespace(data=data, from_user=SimpleNamespace(id=user_id, full_name="Ombor"), message=msg, answer=answer)
        asyncio.run(b.ombor_tugmasi(cb))
        return javoblar

    def _narx_yozish(self, matn):
        async def reply(text, **kw):
            self.yuborilgan.append(("reply", text, kw))

        xabar = SimpleNamespace(text=matn, chat=SimpleNamespace(id=self.SKLAD), from_user=SimpleNamespace(id=555),
                                message_id=60, reply=reply)
        asyncio.run(b.ombor_narx_javobi(xabar, db.get_sorov(self.sid)))

    def _mijozga_ketganlar(self):
        return [x for x in self.yuborilgan if x[0] == self.MIJOZ_CHAT]

    def test_toliq_oqim(self):
        self._callback(f"s:n:{self.sid}")
        self.assertEqual(db.get_sorov(self.sid)["holat"], "narx_kiritilmoqda")
        self.assertIn("SHU XABARGA JAVOB", self.yuborilgan[-1][1])

        self._narx_yozish("40 000 000 ; 3\n12 mln\nizoh: 2 kunda yetkaziladi")
        s = db.get_sorov(self.sid)
        self.assertEqual(s["holat"], "tasdiq_kutilmoqda")
        self.assertEqual(s["summa"], 132_000_000)
        self.assertEqual(self._mijozga_ketganlar(), [])  # tasdiqsiz mijozga hech narsa ketmaydi

        self._callback(f"s:ok:{self.sid}")
        mijozga = self._mijozga_ketganlar()
        self.assertEqual(len(mijozga), 1)
        self.assertIn("132 000 000 so'm", mijozga[0][1])
        self.assertIn("50% oldindan (66 000 000 so'm)", mijozga[0][1])
        self.assertIn("2 kunda yetkaziladi", mijozga[0][1])
        self.assertEqual(mijozga[0][2]["business_connection_id"], "biz-conn-1")
        self.assertEqual(db.get_sorov(self.sid)["holat"], "yuborildi")
        self.assertEqual(db.get_lead(self.MIJOZ_CHAT)["bosqich"], "taklif_berildi")
        self.assertEqual(db.get_chat_history(self.MIJOZ_CHAT)[-1]["role"], "assistant")

        # Ikkinchi marta bosish - mijozga qayta yuborilmaydi
        javob = self._callback(f"s:ok:{self.sid}")
        self.assertEqual(len(self._mijozga_ketganlar()), 1)
        self.assertIn("allaqachon", javob[-1])

    def test_xato_narx_qayta_soraladi(self):
        self._callback(f"s:n:{self.sid}")
        self._narx_yozish("12500000 100")  # noaniq
        self.assertEqual(db.get_sorov(self.sid)["holat"], "narx_kiritilmoqda")
        self.assertIn("⚠️", self.yuborilgan[-1][1])
        self.assertEqual(self._mijozga_ketganlar(), [])

    def test_begona_tugma_bosa_olmaydi(self):
        javob = self._callback(f"s:n:{self.sid}", user_id=555, chat_id=424242)
        self.assertEqual(javob, ["Ruxsat yo'q"])
        self.assertEqual(db.get_sorov(self.sid)["holat"], "kutilmoqda")

    def test_omborda_yoq_tasdiq_bilan(self):
        self._callback(f"s:y:{self.sid}")
        self.assertEqual(db.get_sorov(self.sid)["holat"], "kutilmoqda")  # hali tasdiqlanmagan
        self.assertEqual(self._mijozga_ketganlar(), [])
        self._callback(f"s:yh:{self.sid}")
        self.assertEqual(db.get_sorov(self.sid)["holat"], "yoq")
        self.assertEqual(len(self._mijozga_ketganlar()), 1)

    def test_mijozga_yuborib_bolmasa_qayta_urinish_mumkin(self):
        self._callback(f"s:n:{self.sid}")
        self._narx_yozish("1 000 000\n2 000 000")

        async def xato_send(chat_id, text, **kw):
            if chat_id == self.MIJOZ_CHAT:
                raise b.TelegramAPIError(method=None, message="BUSINESS_PEER_USAGE_MISSING")
            self.yuborilgan.append((chat_id, text, kw))
            return SimpleNamespace(message_id=1)

        b.bot.send_message = xato_send
        self._callback(f"s:ok:{self.sid}")
        self.assertEqual(db.get_sorov(self.sid)["holat"], "tasdiq_kutilmoqda")  # qayta bosish mumkin


class TanishtiruvTest(unittest.TestCase):
    """Birinchi xabarda kompaniya va mahsulotlar taqdimoti (AI ga bog'liq emas)."""

    def setUp(self):
        db.init_db()
        with db.get_db() as conn:
            for t in ("leads", "sorovlar", "messages", "chats"):
                conn.execute(f"DELETE FROM {t}")
        self.yuborilgan = []

        async def send_message(chat_id, text, **kw):
            self.yuborilgan.append(text)
            return SimpleNamespace(message_id=1)

        async def noop(*a, **kw):
            return None

        b.bot = SimpleNamespace(send_message=send_message, send_chat_action=noop, id=999)
        self.ai_chaqiruvlar = []

        async def soxta_ai(tarix, holat, til="uz_latn"):
            self.ai_chaqiruvlar.append([m["role"] for m in tarix])
            n = sotuv.ai_natijasini_ajratish(ai_json(javob="Konveyer uchun AIR seriyasi mos. Quvvati qancha?"))
            n["_birinchi"] = not any(m["role"] == "assistant" for m in tarix)
            n["til"] = til
            return n

        self.patch = mock.patch.object(b, "ai_javob", soxta_ai)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _yoz(self, matn, chat_id=40):
        msg = SimpleNamespace(
            chat=SimpleNamespace(id=chat_id), text=matn, business_connection_id=None, sender_business_bot=None,
            from_user=SimpleNamespace(id=chat_id, username=None, full_name="Mijoz"),
            contact=None, photo=None, document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
        )
        asyncio.run(b.xabarni_qayta_ishlash(msg, is_business=False))

    def test_faqat_salom(self):
        for x in ("Assalomu alaykum", "salom aka", "Здравствуйте!", "Добрый день", "Ассалому алайкум 👋", "/start"):
            self.assertTrue(sotuv.faqat_salommi(x), x)
        for x in ("Salom, dvigatel kerak", "11 kVt bormi", "Здравствуйте, нужен двигатель", "", "👋"):
            self.assertFalse(sotuv.faqat_salommi(x), x)

    def test_taqdimot_ozini_tanishtiradi_3_yonalish_kirill_nomlar(self):
        """Xato #1, #2, #3: o'zini tanishtiradi, 3 yo'nalish, model nomlari kirillda."""
        for til, ozi, nasos, izol in (
            ("uz_latn", "AI savdo yordamchisiman", "Nasos agregatlari", "Elektroizolyatsiya"),
            ("uz_cyrl", "AI савдо ёрдамчисиман", "Насос агрегатлари", "Электроизоляция"),
            ("ru", "AI-помощник", "Насосные агрегаты", "Электроизоляционные"),
        ):
            matn = b.tanishtiruv_matni(til)
            for soz in (ozi, nasos, izol, "АИР", "МТН", "ЭЦВ", "ПЭТВ-2"):
                self.assertIn(soz, matn, f"{til}: {soz}")
            for lotin in ("AIR", "MTN", "VAO", "ECV", "PETV"):
                self.assertNotIn(lotin, matn, f"{til}: {lotin}")

    def test_matnlar_barcha_tillarda(self):
        for til, soz in (("uz_latn", "kran-metallurgiya"), ("uz_cyrl", "кран-металлургия"), ("ru", "крановые")):
            matn = b.tanishtiruv_matni(til)
            self.assertIn("UMATIC", matn)
            self.assertIn(soz, matn)
            self.assertFalse(sotuv.narx_aytilganmi(matn), til)

    def test_salomga_faqat_taqdimot_ai_chaqirilmaydi(self):
        self._yoz("Assalomu alaykum")
        self.assertEqual(len(self.yuborilgan), 1)
        self.assertIn("UMATIC", self.yuborilgan[0])
        self.assertIn("МТН", self.yuborilgan[0])
        self.assertEqual(self.ai_chaqiruvlar, [])

    def test_savol_bilan_boshlasa_taqdimot_va_javob(self):
        self._yoz("Salom, konveyer uchun dvigatel kerak")
        self.assertEqual(len(self.yuborilgan), 2)
        self.assertIn("UMATIC", self.yuborilgan[0])
        self.assertTrue(self.yuborilgan[1].startswith("Konveyer"))  # qayta salomlashmaydi
        self.assertEqual(self.ai_chaqiruvlar, [["user", "assistant"]])

    def test_ikkinchi_xabarda_taqdimot_takrorlanmaydi(self):
        self._yoz("Assalomu alaykum")
        self._yoz("Konveyer uchun kerak")
        self.assertEqual(len(self.yuborilgan), 2)
        self.assertEqual(sum("kran-metallurgiya" in x for x in self.yuborilgan), 1)

    def test_taqdimotni_takrorlash_aniqlanadi(self):
        taqdimot = b.tanishtiruv_matni("uz_latn")
        oxirgi = taqdimot.split("\n\n")[-1]
        self.assertTrue(sotuv.taqdimotni_takrorlaydimi(oxirgi.replace("yozing", "yozing iltimos"), taqdimot))
        self.assertFalse(sotuv.taqdimotni_takrorlaydimi("Konveyer uchun AIR seriyasi mos, quvvati qancha?", taqdimot))

    def test_taqdimot_tarixda_qisqa_belgi(self):
        self._yoz("Assalomu alaykum", chat_id=42)
        tarix = db.get_chat_history(42)
        self.assertEqual(tarix[-1]["content"], b.TAQDIMOT_BELGISI)  # to'liq matn emas - token tejaladi

    def test_eski_yordamchi_tarixi_bor_chatga_ham_taqdimot(self):
        """Foydalanuvchi holati: bazada eski shaxsiy yordamchi javoblari qolgan chat."""
        db.add_message(43, "user", "salom")
        db.add_message(43, "assistant", "Sizni qanday yordam bera olaman? Ismingiz va telefon raqamingizni yozsangiz, Zuxriddin siz bilan bog'lanadi.")
        self._yoz("Assalomu alaykum", chat_id=43)
        self.assertEqual(len(self.yuborilgan), 1)
        self.assertIn("UMATIC", self.yuborilgan[0])
        self._yoz("dvigatel kerak", chat_id=43)
        self.assertEqual(sum("kran-metallurgiya" in x for x in self.yuborilgan), 1)  # ikkinchi marta yo'q

    def test_versiya_yangilanganda_tarix_tozalanadi_crm_qoladi(self):
        db.add_message(44, "assistant", "Zuxriddin siz bilan bog'lanadi")
        db.taqdimot_belgilash(44)
        db.upsert_lead(44, full_name="Eski mijoz", telegram_id=44)
        self.assertTrue(db.suhbat_versiyasini_yangilash("test-v2"))
        self.assertEqual(db.get_chat_history(44), [])
        self.assertFalse(db.taqdimot_yuborilganmi(44))
        self.assertEqual(db.get_lead(44)["full_name"], "Eski mijoz")
        self.assertFalse(db.suhbat_versiyasini_yangilash("test-v2"))  # ikkinchi marta tozalamaydi

    def test_ruscha_mijozga_ruscha_taqdimot(self):
        self._yoz("Здравствуйте", chat_id=41)
        self.assertIn("крановые", self.yuborilgan[0])


class MenejerVaZaxiraTest(unittest.TestCase):
    """Bot har narsaga "menejer bog'lanadi" demasligi va AI ishlamasa ham foydali javob berishi."""

    def test_menejer_takrori_olib_tashlanadi(self):
        javob = "АИР132М4У1 konveyer uchun mos, IP55 himoyaga ega. Menejerimiz tez orada siz bilan bog'lanadi."
        self.assertEqual(sotuv.takroriy_menejerni_olib_tashlash(javob, True, False),
                         "АИР132М4У1 konveyer uchun mos, IP55 himoyaga ega.")

    def test_birinchi_marta_yoki_narx_sorasa_qoladi(self):
        javob = "Bu model mos. Narx bo'yicha menejerimiz bog'lanadi."
        self.assertEqual(sotuv.takroriy_menejerni_olib_tashlash(javob, False, False), javob)
        self.assertEqual(sotuv.takroriy_menejerni_olib_tashlash(javob, True, True), javob)

    def test_faqat_menejer_gapi_bosh_qolmaydi(self):
        javob = "Menejerimiz tez orada siz bilan bog'lanadi."
        self.assertEqual(sotuv.takroriy_menejerni_olib_tashlash(javob, True, False), javob)

    def test_narx_savoli(self):
        for x in ("narxi qancha?", "Сколько стоит?", "omborda bormi", "chegirma bormi", "Нархи неча пул?"):
            self.assertTrue(sotuv.narx_savolimi(x), x)
        for x in ("kafolati qancha?", "IP55 nima degani", "kran uchun qaysi biri yaxshi"):
            self.assertFalse(sotuv.narx_savolimi(x), x)

    def test_zaxira_javob_katalog_bilan(self):
        b.bilimlarni_yuklash()
        javob = sotuv.zaxira_javob("uz_latn", sotuv.katalog_tanlash(b.KATALOG, "11 kVt dvigatel"))
        self.assertIn("АИР132М4У1", javob)
        self.assertNotIn("enejer", javob)
        self.assertFalse(sotuv.narx_aytilganmi(javob))

    def test_zaxira_javob_katalogsiz_va_rus(self):
        self.assertIn("kVt", sotuv.zaxira_javob("uz_latn", ""))
        self.assertIn("кВт", sotuv.zaxira_javob("ru", ""))
        self.assertNotIn("енеджер", sotuv.zaxira_javob("ru", ""))

    def test_ai_ishlamasa_menejerga_yonaltirmaydi(self):
        db.init_db()
        with db.get_db() as conn:
            for t in ("messages", "chats"):
                conn.execute(f"DELETE FROM {t}")
        yuborilgan = []

        async def send_message(chat_id, text, **kw):
            yuborilgan.append(text)
            return SimpleNamespace(message_id=1)

        async def noop(*a, **kw):
            return None

        async def buzuq_ai(*a, **kw):
            raise RuntimeError("Error code: 429 rate_limit_exceeded")

        b.bot = SimpleNamespace(send_message=send_message, send_chat_action=noop, id=999)
        db.taqdimot_belgilash(50)
        msg = SimpleNamespace(
            chat=SimpleNamespace(id=50), text="11 kVt 1500 ob/min dvigatel kerak", business_connection_id=None,
            sender_business_bot=None, from_user=SimpleNamespace(id=50, username=None, full_name="M"),
            contact=None, photo=None, document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
        )
        with mock.patch.object(b, "ai_javob", buzuq_ai):
            asyncio.run(b.xabarni_qayta_ishlash(msg, is_business=False))
        mijozga = yuborilgan[0]
        self.assertIn("АИР132М4У1", mijozga)
        self.assertNotIn("qabul qilindi", mijozga)
        self.assertIn("429", b.OXIRGI_AI_XATOSI["xato"])

    def test_json_schema_qollamaydigan_model(self):
        """llama kabi model json_schema ni qo'llamasa - oddiy JSON rejimida qayta so'raladi."""
        formatlar = []

        async def create(**kw):
            formatlar.append(kw["response_format"]["type"])
            if kw["response_format"]["type"] == "json_schema":
                raise RuntimeError("Error code: 400 - response_format `json_schema` is not supported with this model")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ai_json()))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        n = asyncio.run(b._groq_sorov("llama-3.3-70b-versatile", [{"role": "user", "content": "salom"}]))
        self.assertEqual(formatlar, ["json_schema", "json_object"])
        self.assertIsNotNone(n)

    def test_zanjirda_doim_ishonchli_modellar(self):
        # Render'da eski MODEL=qwen qolsa ham gpt-oss-120b sinaladi
        with mock.patch.object(b, "MODEL", "qwen/qwen3.8-27b"), mock.patch.object(b, "ZAXIRA_MODELLAR", ["qwen/qwen3.8-27b"]):
            chaqiruvlar = []

            async def create(**kw):
                chaqiruvlar.append(kw["model"])
                raise RuntimeError("500")

            b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with mock.patch.object(b, "tizim_korsatmasi", return_value="t"), self.assertRaises(RuntimeError):
                asyncio.run(b.ai_javob([{"role": "user", "content": "salom"}], {"faol": None, "taklif": None}))
        self.assertEqual(chaqiruvlar, ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"])


class MenejerPauzaTest(unittest.TestCase):
    """Menejer chatga qo'shilsa - FAQAT o'sha chatda 5 daqiqa pauza, keyin bot o'zi qaytadi."""

    EGA = 7000
    BCID = "biz-conn"

    def setUp(self):
        db.init_db()
        with db.get_db() as conn:
            for t in ("messages", "chats", "leads", "sorovlar"):
                conn.execute(f"DELETE FROM {t}")
        b.egalar.clear()
        b.egalar[self.BCID] = self.EGA
        self.yuborilgan = []

        async def send_message(chat_id, text, **kw):
            self.yuborilgan.append((chat_id, text))
            return SimpleNamespace(message_id=1)

        async def noop(*a, **kw):
            return None

        b.bot = SimpleNamespace(send_message=send_message, send_chat_action=noop, id=999)

        async def soxta_ai(tarix, holat, til="uz_latn"):
            self.oxirgi_tarix = list(tarix)
            n = sotuv.ai_natijasini_ajratish(ai_json(javob="MTN 411-8 kran uchun mos. Nechta kerak?"))
            n["_birinchi"] = False
            n["til"] = til
            return n

        p = mock.patch.object(b, "ai_javob", soxta_ai)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(b.egalar.clear)

    def _xabar(self, chat_id, matn, kimdan):
        msg = SimpleNamespace(
            chat=SimpleNamespace(id=chat_id), text=matn, business_connection_id=self.BCID, sender_business_bot=None,
            from_user=SimpleNamespace(id=kimdan, username=None, full_name="X"),
            contact=None, photo=None, document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
        )
        asyncio.run(b.xabarni_qayta_ishlash(msg, is_business=True))

    def _bot_javoblari(self, chat_id):
        return [t for c, t in self.yuborilgan if c == chat_id]

    def _vaqtni_orqaga_surish(self, chat_id, daqiqa):
        from datetime import datetime, timedelta
        vaqt = (datetime.now() - timedelta(minutes=daqiqa)).strftime("%Y-%m-%d %H:%M:%S")
        with db.get_db() as conn:
            conn.execute("UPDATE chats SET owner_last_active = ? WHERE chat_id = ?", (vaqt, chat_id))

    def test_standart_pauza_5_daqiqa(self):
        self.assertEqual(b.EGA_PAUZA_DAQIQA, 5)

    def test_faqat_yozilgan_chat_toxtaydi(self):
        self._xabar(60, "Assalomu alaykum, men menejerman", self.EGA)  # menejer 60-chatga yozdi
        self._xabar(60, "kran uchun dvigatel kerak", 601)           # mijoz shu chatda
        self._xabar(61, "kran uchun dvigatel kerak", 611)           # boshqa mijoz, boshqa chat
        self.assertEqual(self._bot_javoblari(60), [])                # 60 - pauzada
        self.assertTrue(self._bot_javoblari(61))                     # 61 - bot ishlayapti

    def test_5_daqiqadan_keyin_ozi_qaytadi(self):
        self._xabar(62, "Salom, qanday yordam kerak?", self.EGA)
        self._vaqtni_orqaga_surish(62, 4)
        self._xabar(62, "kran uchun dvigatel", 621)
        self.assertEqual(self._bot_javoblari(62), [])  # 4 daqiqa - hali pauza
        self._vaqtni_orqaga_surish(62, 6)
        self._xabar(62, "15 kVt kerak", 621)
        javoblar = self._bot_javoblari(62)
        self.assertEqual(len(javoblar), 1)            # 6 daqiqa - bot qaytdi
        self.assertNotIn("UMATIC —", javoblar[0])      # menejer suhbatiga taqdimot tashlanmaydi

    def test_menejer_yozganlari_bot_xotirasida(self):
        self._xabar(63, "Bu dvigatel ertaga keladi", self.EGA)
        self._xabar(63, "yaxshi, rahmat", 631)  # pauza paytida - javob yo'q, lekin xotiraga yoziladi
        self._vaqtni_orqaga_surish(63, 6)
        self._xabar(63, "yana bitta savol bor", 631)
        mazmun = [m["content"] for m in self.oxirgi_tarix]
        self.assertIn("(Menejer yozdi) Bu dvigatel ertaga keladi", mazmun)
        self.assertIn("yaxshi, rahmat", mazmun)

    def test_har_bir_menejer_xabari_pauzani_uzaytiradi(self):
        self._xabar(64, "birinchi xabar", self.EGA)
        self._vaqtni_orqaga_surish(64, 6)
        self._xabar(64, "yana yozdim", self.EGA)  # suhbat davom etmoqda - pauza qaytadan 5 daqiqa
        self._xabar(64, "savol", 641)
        self.assertEqual(self._bot_javoblari(64), [])


class TestchiXatolariTest(unittest.TestCase):
    """Testchi topgan 6 ta xato uchun: har biri qaytib kelmasligini kafolatlaydi."""

    @classmethod
    def setUpClass(cls):
        b.bilimlarni_yuklash()

    def setUp(self):
        db.init_db()
        with db.get_db() as conn:
            for t in ("messages", "chats", "leads", "sorovlar"):
                conn.execute(f"DELETE FROM {t}")
        self.xabarlar, self.hujjatlar, self.rasmlar = [], [], []

        async def send_message(chat_id, text, **kw):
            self.xabarlar.append((chat_id, text))
            return SimpleNamespace(message_id=len(self.xabarlar))

        async def send_document(chat_id, document, caption=None, **kw):
            self.hujjatlar.append((chat_id, document, caption))
            return SimpleNamespace(message_id=1)

        async def send_photo(chat_id, photo, caption=None, **kw):
            self.rasmlar.append((chat_id, caption))
            return SimpleNamespace(message_id=1)

        async def noop(*a, **kw):
            return None

        b.bot = SimpleNamespace(send_message=send_message, send_document=send_document, send_photo=send_photo,
                                send_chat_action=noop, id=999)
        self.ai_tillari = []
        self.ai_javobi = "Katalogimizda AIR132M4U1 bor: 11 kVt, 1460 ob/min."

        async def soxta_ai(tarix, holat, til="uz_latn"):
            self.ai_tillari.append(til)
            self.oxirgi_holat = holat
            n = sotuv.ai_natijasini_ajratish(ai_json(javob=self.ai_javobi))
            n["_birinchi"], n["til"] = False, til
            return n

        p = mock.patch.object(b, "ai_javob", soxta_ai)
        p.start()
        self.addCleanup(p.stop)

    def _yoz(self, matn, chat_id=70):
        db.taqdimot_belgilash(chat_id)  # taqdimot alohida testlangan
        msg = SimpleNamespace(
            chat=SimpleNamespace(id=chat_id), text=matn, business_connection_id=None, sender_business_bot=None,
            from_user=SimpleNamespace(id=chat_id, username=None, full_name="Test"),
            contact=None, photo=None, document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
        )
        asyncio.run(b.xabarni_qayta_ishlash(msg, is_business=False))

    # --- #2: saytdagi boshqa mahsulotlar ham taklif qilinadi ---
    def test_nasos_va_izolyatsiya_katalogda(self):
        nasos = sotuv.katalog_tanlash(b.KATALOG, "quduq nasosi kerak")
        self.assertIn("ЭЦВ 8-25-100", nasos)
        sim = sotuv.katalog_tanlash(b.KATALOG, "emal sim kerak 0,5 mm")
        self.assertIn("ПЭТВ-2 0,50 мм", sim)
        self.assertIn("Перчатки", sotuv.katalog_tanlash(b.KATALOG, "qo'lqop bormi"))
        self.assertIn("Секции статорных обмоток", sotuv.katalog_tanlash(b.KATALOG, "stator o'rami kerak"))

    def test_korsatmada_boshqa_mahsulot_rad_etilmaydi(self):
        korsatma = b.tizim_korsatmasi()
        self.assertIn("NASOS AGREGATLARI", korsatma)
        self.assertNotIn("hozircha faqat dvigatellar", korsatma)

    # --- #3: model nomlari kirillda ---
    def test_lotin_model_nomi_kirillga_qaytariladi(self):
        self._yoz("11 kVt 1500 ob/min dvigatel kerak")
        javob = [t for c, t in self.xabarlar if c == 70][-1]
        self.assertIn("АИР132М4У1", javob)
        self.assertNotIn("AIR132M4U1", javob)

    # --- #4: til o'zgartirish ---
    def test_ozbek_kirill_toggri_aniqlanadi(self):
        for matn in ("Узини таништирмаябти", "Сухбат давомида тил узгартиромади", "Техник маълумот ва расм сураганимда жавоб бермади"):
            self.assertEqual(sotuv.tilni_aniqlash(matn), "uz_cyrl", matn)

    def test_tilni_soraganda_ozgaradi_va_saqlanadi(self):
        self._yoz("salom, dvigatel kerak")
        self._yoz("rus tilida gapiring")
        self._yoz("11 kvt dvigatel kerak")  # lotinda yozdi, lekin rus tilini tanlagan
        self.assertEqual(self.ai_tillari, ["uz_latn", "ru", "ru"])
        self._yoz("ўзбекча ёзинг")
        self.assertEqual(self.ai_tillari[-1], "uz_cyrl")

    # --- #5: texnik ma'lumot va rasm ---
    def test_texnik_tafsilot_korsatmaga_qoshiladi(self):
        m = sotuv.topilgan_modellar(b.KATALOG, "АИР132М4У1 tokini ayting")[0]
        tafsilot = sotuv.tafsilot_matni(m)
        self.assertIn("Номинальный ток", tafsilot)
        self.assertIn("umatic.uz", tafsilot)

    def test_rasm_soralganda_yuboriladi(self):
        async def soxta_rasm(url):
            return b"\xff\xd8jpeg"

        with mock.patch.object(b, "_rasmni_yuklash", soxta_rasm):
            self._yoz("АИР132М4У1 rasmini yuboring")
        self.assertEqual(len(self.rasmlar), 1)
        self.assertIn("АИР132М4У1", self.rasmlar[0][1])
        self.assertIn("rasmi avtomatik yuboriladi", " ".join(self.oxirgi_holat["qoshimcha"]))

    def test_model_aytilmasa_rasm_uchun_soraydi(self):
        self._yoz("rasm bormi?")
        self.assertEqual(self.rasmlar, [])
        self.assertIn("qaysi model", " ".join(self.oxirgi_holat["qoshimcha"]))

    # --- #6: taklif omborda tekshirilgandan keyin ---
    def test_standart_rejim_mavjudlik(self):
        self.assertEqual(b.TAKLIF_REJIMI, "mavjudlik")
        self.assertTrue(b.OMBOR_ORQALI)

    def test_taklif_ombor_tasdiqlamaguncha_yuborilmaydi(self):
        rejim_qoy(self, "mavjudlik")
        n = sotuv.ai_natijasini_ajratish(ai_json(mahsulotlar=POZ, narx_sorash=True))
        n["_birinchi"] = False
        mijoz = SimpleNamespace(id=80, username=None, full_name="M")
        asyncio.run(b.crm_yangilash(80, mijoz, n, {"faol": None, "taklif": None}, "", None, None))
        self.assertEqual([h for h in self.hujjatlar if h[0] == 80], [])  # mijozga PDF hali ketmadi
        sorov = db.get_faol_sorov(80)
        self.assertIsNotNone(sorov)
        self.assertTrue(any("MAVJUDLIK SO'ROVI" in t for c, t in self.xabarlar if c == -100500))

    def _callback(self, data, chat_id=-100500):
        async def answer(text=None, show_alert=False):
            return None

        async def noop(*a, **kw):
            return None

        async def reply(text, **kw):
            self.xabarlar.append(("reply", text))

        msg = SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=5, html_text="so'rov",
                              edit_text=noop, edit_reply_markup=noop, reply=reply)
        asyncio.run(b.ombor_tugmasi(SimpleNamespace(data=data, from_user=SimpleNamespace(id=555, full_name="Ombor"),
                                                    message=msg, answer=answer)))

    def test_hammasi_bor_keyin_pdf_omborda_ustuni_bilan(self):
        rejim_qoy(self, "mavjudlik")
        db.upsert_lead(81, full_name="Sardor", telegram_id=81)
        sid = db.create_sorov(81, 81, None, "uz_latn", json.dumps(POZ), "k", "")
        self._callback(f"s:hb:{sid}")
        self.assertEqual(db.get_sorov(sid)["holat"], "tasdiq_kutilmoqda")
        self.assertEqual([h for h in self.hujjatlar if h[0] == 81], [])  # tasdiqsiz ketmaydi
        self._callback(f"s:ok:{sid}")
        mijozga = [h for h in self.hujjatlar if h[0] == 81]
        self.assertEqual(len(mijozga), 1)
        self.assertEqual(db.get_sorov(sid)["holat"], "yuborildi")

    def test_sonini_kiritish_va_hech_biri_yoq(self):
        rejim_qoy(self, "mavjudlik")
        sid = db.create_sorov(82, 82, None, "uz_latn", json.dumps(POZ), "k", "")
        self._callback(f"s:n:{sid}")
        self.assertIn("NECHTA", self.xabarlar[-1][1])

        async def reply(text, **kw):
            self.xabarlar.append(("reply", text))

        xabar = SimpleNamespace(text="yo'q\n0", chat=SimpleNamespace(id=-100500), from_user=SimpleNamespace(id=555),
                                message_id=9, reply=reply)
        asyncio.run(b.ombor_narx_javobi(xabar, db.get_sorov(sid)))
        self._callback(f"s:ok:{sid}")
        self.assertEqual(db.get_sorov(sid)["holat"], "yoq")
        self.assertEqual([h for h in self.hujjatlar if h[0] == 82], [])  # PDF emas
        self.assertTrue(any(c == 82 for c, t in self.xabarlar))     # "omborda yo'q" xabari

    def test_pdf_omborda_ustuni(self):
        pdf = taklif_pdf.taklif_pdf(9, "ru", POZ, "Олег", "", "", "", mavjudlik=[3, 0])
        self.assertTrue(pdf.startswith(b"%PDF"))


class AiFallbackTest(unittest.TestCase):
    def test_narx_aytsa_xavfsiz_matn(self):
        """AI ikki marta narx o'ylab topsa - mijozga xavfsiz matn ketadi."""
        yolgon = ai_json(javob="Bu nasos 3 mln so'm turadi", narx_sorash=True, mahsulotlar=POZ)

        async def create(**kw):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=yolgon))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"):
            n = asyncio.run(b.ai_javob([{"role": "user", "content": "narxi?"}], {"faol": None, "taklif": None}))
        self.assertEqual(n["javob"], sotuv.matn("kutish", "uz_latn"))

    def test_notogri_til_keyingi_modelga_otadi(self):
        """1-model rus mijoziga ikki marta o'zbekcha javob bersa - 2-model ruscha javobi yuboriladi."""
        chaqiruvlar = []
        b.ZAXIRA_MODELLAR = ["zaxira/model"]

        async def create(**kw):
            chaqiruvlar.append(kw["model"])
            matn = "Quduq diametri va chuqurligi qancha bo'ladi?" if kw["model"] == b.MODEL else "Какой диаметр скважины?"
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ai_json(javob=matn)))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        try:
            with mock.patch.object(b, "tizim_korsatmasi", return_value="test"):
                n = asyncio.run(b.ai_javob([{"role": "user", "content": "нужен насос"}], {"faol": None, "taklif": None}, "ru"))
        finally:
            b.ZAXIRA_MODELLAR = ["qwen/qwen3.8-27b"]
        self.assertEqual(n["javob"], "Какой диаметр скважины?")
        self.assertEqual(chaqiruvlar, [b.MODEL, b.MODEL, "zaxira/model"])

    def test_notogri_tildagi_javob_hech_qachon_yuborilmaydi(self):
        """Barcha modellar rus mijoziga o'zbekcha javob bersa - kutib qayta urinadi, keyin xato (menejerga)."""
        chaqiruvlar = []

        async def create(**kw):
            chaqiruvlar.append(kw["model"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content=ai_json(javob="Quduq diametri va chuqurligi qancha bo'ladi?")))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"), mock.patch.object(b, "LIMIT_KUTISH", 0):
            with self.assertRaises(RuntimeError):
                asyncio.run(b.ai_javob([{"role": "user", "content": "нужен насос"}], {"faol": None, "taklif": None}, "ru"))
        modellar_soni = len(set([b.MODEL] + b.ZAXIRA_MODELLAR + b.ASOSIY_ZANJIR))
        self.assertEqual(len(chaqiruvlar), modellar_soni * 2 * 2)  # 2 aylanish x (javob + tuzatish)

    def test_takroriy_lekin_togri_tildagi_javob_yuboriladi(self):
        eski = "Какой диаметр скважины нужен для подбора насоса, подскажите пожалуйста?"

        async def create(**kw):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ai_json(javob=eski)))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        tarix = [{"role": "user", "content": "насос"}, {"role": "assistant", "content": eski}, {"role": "user", "content": "2 шт"}]
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"):
            n = asyncio.run(b.ai_javob(tarix, {"faol": None, "taklif": None}, "ru"))
        self.assertEqual(n["javob"], eski)

    def test_zaxira_modelga_otadi(self):
        chaqiruvlar = []

        async def create(**kw):
            chaqiruvlar.append(kw["model"])
            if kw["model"] == b.MODEL:
                raise RuntimeError("429 rate limit")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ai_json()))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"):
            n = asyncio.run(b.ai_javob([{"role": "user", "content": "salom"}], {"faol": None, "taklif": None}))
        self.assertEqual(len(chaqiruvlar), 2)
        self.assertEqual(n["javob"], "Qanday quvvatdagi dvigatel kerak?")

    def test_hammasi_limitda_kutib_qayta_urinadi(self):
        chaqiruvlar = []
        modellar_soni = len(set([b.MODEL] + b.ZAXIRA_MODELLAR + b.ASOSIY_ZANJIR))

        async def create(**kw):
            chaqiruvlar.append(kw["model"])
            if len(chaqiruvlar) <= modellar_soni:  # birinchi aylanishda barcha modellar limitda
                raise RuntimeError("Error code: 429 rate_limit_exceeded")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=ai_json()))])

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"), mock.patch.object(b, "LIMIT_KUTISH", 0):
            n = asyncio.run(b.ai_javob([{"role": "user", "content": "salom"}], {"faol": None, "taklif": None}))
        self.assertEqual(len(chaqiruvlar), modellar_soni + 1)
        self.assertIsNotNone(n)

    def test_boshqa_xatoda_kutmaydi(self):
        async def create(**kw):
            raise RuntimeError("500 server error")

        b.groq_chat = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.object(b, "tizim_korsatmasi", return_value="test"), mock.patch.object(b, "LIMIT_KUTISH", 999):
            with self.assertRaises(RuntimeError):
                asyncio.run(b.ai_javob([{"role": "user", "content": "salom"}], {"faol": None, "taklif": None}))


if __name__ == "__main__":
    unittest.main()
