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
            til="fr", bosqich="nomalum", narx_sorash="true",
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
        self._narx_rejimi = b.NARX_OMBORDAN
        b.NARX_OMBORDAN = True
        self.addCleanup(setattr, b, "NARX_OMBORDAN", self._narx_rejimi)
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
        self.assertEqual(lead["telefon"], "+998 90 123 45 67")  # bir xil ko'rinishga keltiriladi
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
        self.assertFalse(b.NARX_OMBORDAN)  # standart rejim - narxsiz
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
        db.init_db()
        with db.get_db() as conn:
            for t in ("leads", "sorovlar", "messages", "chats"):
                conn.execute(f"DELETE FROM {t}")
        self.yuborilgan = []

        async def send_message(chat_id, text, **kw):
            self.yuborilgan.append((chat_id, text, kw))
            return SimpleNamespace(message_id=100 + len(self.yuborilgan))

        self.hujjatlar = []

        async def send_document(chat_id, document, caption=None, **kw):
            self.hujjatlar.append((chat_id, document, caption, kw))
            return SimpleNamespace(message_id=1)

        b.bot = SimpleNamespace(send_message=send_message, send_document=send_document, id=999)
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
        # Mijozga narxli PDF ham boradi (matndagi raqamlar bilan)
        pdflar = [x for x in self.hujjatlar if x[0] == self.MIJOZ_CHAT]
        self.assertEqual(len(pdflar), 1)
        self.assertTrue(pdflar[0][1].data.startswith(b"%PDF"))
        self.assertEqual(pdflar[0][3]["business_connection_id"], "biz-conn-1")

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

    def test_matnlar_barcha_tillarda(self):
        for til, soz in (("uz_latn", "Kran-metallurgiya"), ("uz_cyrl", "Кран-металлургия"), ("ru", "Крановые")):
            matn = b.tanishtiruv_matni(til)
            self.assertIn("UMATIC", matn)
            self.assertIn(soz, matn)
            self.assertFalse(sotuv.narx_aytilganmi(matn), til)

    def test_salomga_faqat_taqdimot_ai_chaqirilmaydi(self):
        self._yoz("Assalomu alaykum")
        self.assertEqual(len(self.yuborilgan), 1)
        self.assertIn("UMATIC", self.yuborilgan[0])
        self.assertIn("MTN", self.yuborilgan[0])
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
        self.assertEqual(sum("Kran-metallurgiya" in x for x in self.yuborilgan), 1)

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
        self.assertEqual(sum("Kran-metallurgiya" in x for x in self.yuborilgan), 1)  # ikkinchi marta yo'q

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
        self.assertIn("Крановые", self.yuborilgan[0])


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
        # Token tejash: bitta javob uchun AI so'rovlari MAX_AI_CHAQIRUV dan oshmaydi
        self.assertEqual(len(chaqiruvlar), b.MAX_AI_CHAQIRUV)

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
        modellar_soni = len(set([b.MODEL] + b.ZAXIRA_MODELLAR))

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



# =====================================================================
#  YANGI IMKONIYATLAR: tillar, telefon, lidlar guruhi, zaxira, navbat, egalik
# =====================================================================

def _soxta_bot(yuborilgan: list, **qoshimcha):
    """Telegram bot o'rnini bosuvchi obyekt: barcha chaqiruvlar ro'yxatga yoziladi."""
    hisob = {"n": 0}

    def _yoz(nomi):
        async def f(*a, **kw):
            hisob["n"] += 1
            yuborilgan.append((nomi, kw))
            return SimpleNamespace(message_id=1000 + hisob["n"])
        return f

    nomlar = ("send_message", "send_document", "edit_message_text", "send_chat_action", "send_photo",
              "send_media_group", "pin_chat_message", "delete_message")
    obj = SimpleNamespace(id=999, **{n: _yoz(n) for n in nomlar})
    for k, v in qoshimcha.items():
        setattr(obj, k, v)
    return obj


def _tozalash():
    db.init_db()
    with db.get_db() as conn:
        for t in ("leads", "sorovlar", "messages", "chats", "darslar"):
            conn.execute(f"DELETE FROM {t}")


class TillarTest(unittest.TestCase):
    def test_ruscha_ozbekcha_deb_aniqlanmaydi(self):
        # Avval "какая" (ичида "ака") va "выбор " (ичида "бор ") o'zbek kirill deb aniqlanardi
        for matn in ("Какая цена на двигатель?", "Есть на выбор несколько моделей?", "Такая мощность подойдёт?"):
            self.assertEqual(sotuv.tilni_aniqlash(matn), "ru", matn)
        self.assertEqual(sotuv.tilni_aniqlash("Ассалому алайкум, ака двигател керак"), "uz_cyrl")

    def test_ingliz_tili(self):
        self.assertEqual(sotuv.tilni_aniqlash("Hello, I need a 15 kW motor"), "en")
        self.assertEqual(sotuv.tilni_aniqlash("How much is it?"), "en")
        self.assertEqual(sotuv.tilni_aniqlash("ok", "en"), "en")
        self.assertEqual(sotuv.tilni_aniqlash("Salom aka, 4 kVt dvigatel kerak"), "uz_latn")
        self.assertTrue(sotuv.yozuv_mosmi("I recommend the AIR 100L4 motor. How many do you need?", "en"))
        self.assertFalse(sotuv.yozuv_mosmi("Sizga AIR 100L4 dvigateli mos keladi, nechta kerak?", "en"))
        self.assertFalse(sotuv.yozuv_mosmi("I recommend the AIR motor for your pump, how many do you need?", "uz_latn"))
        self.assertFalse(sotuv.yozuv_mosmi("Сизга қандай двигател керак, қувватини ёзинг?", "ru"))

    def test_boshqa_tillar_rad_etiladi(self):
        for matn in ("Merhaba, motor fiyatı nedir?", "مرحبا أريد محرك", "你好，我需要电机",
                     "Сәлеметсіз бе, қозғалтқыш керек", "Guten Tag, ich brauche einen Motor", "Bonjour, je cherche un moteur"):
            self.assertEqual(sotuv.tilni_aniqlash(matn), sotuv.BOSHQA_TIL, matn)

    def test_ingliz_matnlari_va_taqdimot(self):
        for kalit in sotuv._MATNLAR["uz_latn"]:
            self.assertIn(kalit, sotuv._MATNLAR["en"])
        self.assertIn("Explosion-proof", b.tanishtiruv_matni("en"))
        self.assertTrue(sotuv.faqat_salommi("Hello!"))
        self.assertTrue(sotuv.narx_aytilganmi("It costs about 300 USD"))

    def test_rasm_izohi_tilni_buzmaydi(self):
        matn = "[Mijoz rasm yubordi (sen uni ko'ra olmaysan, u menejerga yuborildi). Izohi: Вот шильдик двигателя]"
        self.assertEqual(sotuv.tilni_aniqlash(b._til_uchun_matn(matn)), "ru")
        kontakt = "[Mijoz kontakt ulashdi] Ismi: Иван, telefon: +79991234567"
        self.assertEqual(sotuv.tilni_aniqlash(b._til_uchun_matn(kontakt), "ru"), "ru")
        self.assertEqual(sotuv.tilni_aniqlash(b._til_uchun_matn("Salom\n" + kontakt)), "uz_latn")

    def test_boshqa_tilda_ai_chaqirilmaydi(self):
        _tozalash()
        yuborilgan = []
        b.bot = _soxta_bot(yuborilgan)
        chaqiruv = []

        async def soxta_ai(*a, **kw):
            chaqiruv.append(1)

        msg = SimpleNamespace(
            chat=SimpleNamespace(id=70), text="Merhaba, motor fiyatı nedir?", business_connection_id=None,
            sender_business_bot=None, from_user=SimpleNamespace(id=70, username=None, full_name="Ahmet"),
            contact=None, photo=None, document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
        )
        with mock.patch.object(b, "ai_javob", soxta_ai):
            asyncio.run(b.xabarni_qayta_ishlash(msg, is_business=False))
        self.assertEqual(chaqiruv, [])
        matnlar = [kw["text"] for nomi, kw in yuborilgan if nomi == "send_message"]
        self.assertEqual(matnlar, [sotuv.BOSHQA_TIL_JAVOBI])
        self.assertIn("ingliz", matnlar[0])


class TelefonTest(unittest.TestCase):
    def test_barcha_operatorlar(self):
        for matn, kutilgan in (
            ("+998 77 123 45 67", "+998 77 123 45 67"), ("77 123 45 67", "+998 77 123 45 67"),
            ("50 1234567", "+998 50 123 45 67"), ("(90) 123-45-67", "+998 90 123 45 67"),
            ("998331234567", "+998 33 123 45 67"), ("8 90 123 45 67", "+998 90 123 45 67"),
            ("raqamim 71 200 30 40", "+998 71 200 30 40"), ("+7 999 123 45 67", "+79991234567"),
        ):
            self.assertEqual(sotuv.telefon_topish(matn), kutilgan, matn)

    def test_texnik_raqamlar_telefon_emas(self):
        for matn in ("15 kVt 1500 ob/min 3 dona", "100000000", "12 500 000", "380 V, 50 Hz, IP55"):
            self.assertEqual(sotuv.telefon_topish(matn), "", matn)


class TaklifKalitiTest(unittest.TestCase):
    def test_qayta_ifodalash_yangi_taklif_emas(self):
        a = [{"nomi": "AIR 100L4", "parametrlar": "4 kVt, 1500 ob/min", "miqdor": 3, "birlik": "dona"}]
        b_ = [{"nomi": "АИР100L4 электродвигатель", "parametrlar": "4кВт 1500об/мин", "miqdor": 3, "birlik": "шт"}]
        c = [{"nomi": "AIR 100L4", "parametrlar": "4 kVt, 1500 ob/min", "miqdor": 5, "birlik": "dona"}]
        self.assertEqual(sotuv.mahsulotlar_kaliti(a), sotuv.mahsulotlar_kaliti(b_))
        self.assertNotEqual(sotuv.mahsulotlar_kaliti(a), sotuv.mahsulotlar_kaliti(c))


class LidlarGuruhiTest(unittest.TestCase):
    GURUH = -100777

    def setUp(self):
        _tozalash()
        self.yuborilgan = []
        b.bot = _soxta_bot(self.yuborilgan)
        patch = mock.patch.object(b, "LIDLAR_CHAT_ID", self.GURUH)
        patch.start()
        self.addCleanup(patch.stop)
        self.mijoz = SimpleNamespace(id=8001, username="karim", full_name="Karim")

    def _natija(self, **o):
        n = sotuv.ai_natijasini_ajratish(ai_json(**o))
        n["_birinchi"] = False
        return n

    def _guruhga(self, nomi):
        return [kw for n, kw in self.yuborilgan if n == nomi and kw.get("chat_id") == self.GURUH]

    def test_karta_kontakt_olinganda_paydo_boladi_va_tahrirlanadi(self):
        async def oqim():
            await b.crm_yangilash(80, self.mijoz, self._natija(ehtiyoj="Konveyer"), {}, "salom", None, None)
            self.assertEqual(self._guruhga("send_message"), [])  # kontaktsiz - hali lid emas
            await b.crm_yangilash(80, self.mijoz, self._natija(ehtiyoj="Konveyer"), {}, "raqamim 93 123 45 67", None, None)
            await b.crm_yangilash(80, self.mijoz, self._natija(ehtiyoj="Konveyer"), {}, "ok", None, None)
            await b.crm_yangilash(80, self.mijoz, self._natija(ehtiyoj="Konveyer 4 kVt"), {}, "4 kVt", None, None)

        asyncio.run(oqim())
        yangi = self._guruhga("send_message")
        self.assertEqual(len(yangi), 1)  # har bir mijoz - bitta kartochka
        self.assertIn("+998 93 123 45 67", yangi[0]["text"])
        self.assertIn("LID #", yangi[0]["text"])
        tahrir = self._guruhga("edit_message_text")
        self.assertEqual(len(tahrir), 1)  # o'zgarmagan holatda tahrir yo'q, o'zgarganda - bor
        self.assertIn("4 kVt", tahrir[0]["text"])
        # Egalarga shaxsiy xabar ketmaydi - hammasi guruhda
        self.assertFalse(any(kw.get("chat_id") in (111, 222) for _, kw in self.yuborilgan))

    def test_hodisa_kartaga_javob_qilib_yoziladi_va_pdf_guruhga(self):
        n = self._natija(mahsulotlar=POZ, narx_sorash=True, menejer_kerak=True, menejer_sababi="chegirma",
                         mijoz={"ism": "Karim", "telefon": "", "kompaniya": "", "lavozim": "", "soha": ""})
        asyncio.run(b.crm_yangilash(81, self.mijoz, n, {"faol": None, "taklif": None}, "91 234 56 78", None, None))
        karta_id = json.loads(db.get_lead(81)["karta_msglar"])[str(self.GURUH)]
        pdf = self._guruhga("send_document")
        self.assertEqual(len(pdf), 1)
        self.assertEqual(pdf[0]["reply_to_message_id"], karta_id)
        self.assertLessEqual(len(pdf[0]["caption"]), 1024)
        menejer = [kw for kw in self._guruhga("send_message") if "MENEJER ARALASHUVI" in kw["text"]]
        self.assertEqual(menejer[0]["reply_to_message_id"], karta_id)

    def test_uzun_izohli_fayl_buzilmaydi(self):
        db.upsert_lead(82, full_name="X", telegram_id=82, telefon="+998 90 000 00 00")
        asyncio.run(b.lid_hodisasi(82, "<b>Sarlavha</b>\n" + "a" * 1500, hujjat=(b"%PDF-test", "t.pdf")))
        hujjat = self._guruhga("send_document")[0]
        self.assertIsNone(hujjat["caption"])  # 1024 dan uzun izoh kesilmaydi - alohida xabar bo'ladi
        self.assertTrue(any("a" * 1500 in kw["text"] for kw in self._guruhga("send_message")))

    def test_uslub_va_xulosa_xotirada(self):
        n = self._natija(uslub="Qisqa yozadi, 'aka' deydi", xulosa="Konveyer uchun dvigatel izlayapti", ehtiyoj="Konveyer")
        asyncio.run(b.crm_yangilash(83, self.mijoz, n, {}, "salom aka", None, None))
        matn = b.holat_matni(b.suhbat_holati(83), False)
        self.assertIn("'aka' deydi", matn)
        self.assertIn("Konveyer", matn)
        self.assertIn("telefon: hali olinmagan", matn)


class EgalikTest(unittest.TestCase):
    def setUp(self):
        _tozalash()
        b.egalar.clear()
        self.yuborilgan = []
        b.bot = _soxta_bot(self.yuborilgan)

    def _xabar(self, user_id, matn):
        javoblar = []

        async def answer(text, **kw):
            javoblar.append(text)

        return SimpleNamespace(
            chat=SimpleNamespace(id=user_id, type="private"), text=matn, business_connection_id=None,
            sender_business_bot=None, from_user=SimpleNamespace(id=user_id, username=None, full_name="U", language_code="uz"),
            contact=None, photo=None, document=None, location=None, voice=None, video_note=None, audio=None,
            caption=None, answer=answer,
        ), javoblar

    def test_start_bilan_ega_bolib_bolmaydi(self):
        with mock.patch.object(b, "OWNER_IDS", set()):
            msg, _ = self._xabar(5555, "/start")
            asyncio.run(b.start_komandasi(msg))
            self.assertFalse(b.egami(5555))
            self.assertNotIn(5555, db.get_owner_ids())

    def test_ega_xabari_mijoz_deb_hisoblanmaydi(self):
        msg, javoblar = self._xabar(111, "dvigatel kerak")
        with mock.patch.object(b, "xabarni_navbatga_qoshish") as navbat:
            asyncio.run(b.xabar_keldi_shaxsiy(msg))
            navbat.assert_not_called()
        self.assertIn("egasisiz", javoblar[0])
        self.assertIsNone(db.get_lead(111))

    def test_sinov_rejimida_mijoz_sifatida(self):
        b.SINOV_REJIMI.add(111)
        self.addCleanup(b.SINOV_REJIMI.discard, 111)
        msg, _ = self._xabar(111, "dvigatel kerak")

        async def navbat(m, is_business):
            navbat.chaqirildi = True

        navbat.chaqirildi = False
        with mock.patch.object(b, "xabarni_navbatga_qoshish", navbat):
            asyncio.run(b.xabar_keldi_shaxsiy(msg))
        self.assertTrue(navbat.chaqirildi)


class NavbatTest(unittest.TestCase):
    def setUp(self):
        _tozalash()
        self.yuborilgan = []
        b.bot = _soxta_bot(self.yuborilgan)

    def test_ketma_ket_xabarlarga_bitta_javob(self):
        ai_kirish = []

        async def soxta_ai(tarix, holat, til="uz_latn"):
            ai_kirish.append(tarix[-1]["content"])
            n = sotuv.ai_natijasini_ajratish(ai_json(javob="Konveyer uchun AIR mos. Quvvati qancha?"))
            n["_birinchi"], n["til"] = False, til
            return n

        def xabar(matn):
            return SimpleNamespace(
                chat=SimpleNamespace(id=90), text=matn, business_connection_id=None, sender_business_bot=None,
                from_user=SimpleNamespace(id=90, username=None, full_name="Mijoz"), contact=None, photo=None,
                document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
            )

        async def oqim():
            for matn in ("Salom", "konveyer uchun", "dvigatel kerak"):
                await b.xabarni_navbatga_qoshish(xabar(matn), is_business=False)
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.3)

        db.taqdimot_belgilash(90)
        with mock.patch.object(b, "ai_javob", soxta_ai), mock.patch.object(b, "XABAR_KUTISH", 0.1):
            asyncio.run(oqim())
        self.assertEqual(ai_kirish, ["Salom\nkonveyer uchun\ndvigatel kerak"])
        javoblar = [kw["text"] for n, kw in self.yuborilgan if n == "send_message" and kw.get("chat_id") == 90]
        self.assertEqual(len(javoblar), 1)


class QaytganMijozTest(unittest.TestCase):
    def test_tanish_mijozga_taqdimot_qayta_yuborilmaydi(self):
        _tozalash()
        yuborilgan = []
        b.bot = _soxta_bot(yuborilgan)
        db.upsert_lead(95, full_name="Aziz", telegram_id=95, xulosa="Nasos uchun 7.5 kVt so'ragan", uslub="rasmiy")

        async def soxta_ai(tarix, holat, til="uz_latn"):
            self.assertIn("Aziz", b.holat_matni(holat, True))
            n = sotuv.ai_natijasini_ajratish(ai_json(javob="Aziz, yana xush kelibsiz! Qanday yordam kerak?"))
            n["_birinchi"], n["til"] = True, til
            return n

        msg = SimpleNamespace(
            chat=SimpleNamespace(id=95), text="Salom", business_connection_id=None, sender_business_bot=None,
            from_user=SimpleNamespace(id=95, username=None, full_name="Aziz"), contact=None, photo=None,
            document=None, location=None, voice=None, video_note=None, audio=None, caption=None,
        )
        with mock.patch.object(b, "ai_javob", soxta_ai):
            asyncio.run(b.xabarni_qayta_ishlash(msg, is_business=False))
        matnlar = [kw["text"] for n, kw in yuborilgan if n == "send_message"]
        self.assertEqual(len(matnlar), 1)
        self.assertNotIn("Kran-metallurgiya", matnlar[0])
        self.assertIn("Aziz", matnlar[0])


class ZaxiraTest(unittest.TestCase):
    def test_zaxiralash_va_tiklash(self):
        import zaxira
        _tozalash()
        db.upsert_lead(500, full_name="Saqlanadigan mijoz", telegram_id=500)
        sid = db.create_sorov(500, 500, None, "uz_latn", json.dumps(POZ), "k", "")
        fayllar = {}
        yuborilgan = []

        async def send_document(chat_id, document, **kw):
            fayllar["f"] = document.data
            yuborilgan.append(("send_document", kw))
            return SimpleNamespace(message_id=77)

        bot = _soxta_bot(yuborilgan, send_document=send_document)
        zaxira._holat.update(xesh=None, msg_id=None, bloklangan=False)
        self.assertTrue(asyncio.run(zaxira.zaxiralash(bot, 111)))
        self.assertFalse(asyncio.run(zaxira.zaxiralash(bot, 111)))  # o'zgarmagan baza qayta yuborilmaydi
        self.assertTrue(any(n == "pin_chat_message" for n, _ in yuborilgan))

        # Server qayta ishga tushdi: disk bo'sh
        os.remove(db.DB_FAYLI)
        for q in ("-wal", "-shm"):
            if os.path.exists(db.DB_FAYLI + q):
                os.remove(db.DB_FAYLI + q)
        self.assertFalse(db.baza_bormi())

        async def get_chat(chat_id):
            doc = SimpleNamespace(file_name="umatic_baza_20261001.db.gz", file_id="F1")
            return SimpleNamespace(pinned_message=SimpleNamespace(document=doc, message_id=77))

        async def download(file_id, destination):
            destination.write(fayllar["f"])

        bot.get_chat, bot.download = get_chat, download
        with mock.patch.object(zaxira, "TIKLASH_KUTISH", 0):
            self.assertTrue(asyncio.run(zaxira.tiklash(bot, 111)))
        db.init_db()
        self.assertEqual(db.get_lead(500)["full_name"], "Saqlanadigan mijoz")
        # Taklif raqamlari davom etadi (qaytadan UM-00001 dan boshlanmaydi)
        self.assertGreater(db.create_sorov(500, 500, None, "uz_latn", "[]", "k2", ""), sid)

    def test_tiklash_xato_bolsa_zaxira_ustiga_yozilmaydi(self):
        import zaxira
        zaxira._holat.update(xesh=None, msg_id=None, bloklangan=False)
        with db.get_db() as conn:
            conn.execute("DELETE FROM leads")
            conn.execute("DELETE FROM messages")

        async def get_chat(chat_id):
            raise RuntimeError("tarmoq xatosi")

        bot = _soxta_bot([], get_chat=get_chat)
        with mock.patch.object(zaxira, "TIKLASH_KUTISH", 0):
            self.assertFalse(asyncio.run(zaxira.tiklash(bot, 111)))
        self.assertFalse(asyncio.run(zaxira.zaxiralash(bot, 111, majburiy=True)))
        zaxira._holat["bloklangan"] = False


class VaqtVaSheetsTest(unittest.TestCase):
    def test_toshkent_vaqti(self):
        from datetime import datetime, timezone
        import vaqt
        farq = (vaqt.hozir() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() / 3600
        self.assertAlmostEqual(farq, 5, delta=0.01)

    def test_sheets_xato_javobi_muvaffaqiyat_emas(self):
        from aiohttp import web

        async def oqim():
            async def ok(request):
                return web.json_response({"ok": True})

            async def xato(request):
                return web.json_response({"ok": False, "error": "x"})

            async def login(request):
                return web.Response(text="<html>Sign in</html>", content_type="text/html")

            app = web.Application()
            app.router.add_post("/ok", ok)
            app.router.add_post("/xato", xato)
            app.router.add_post("/login", login)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            natija = {}
            try:
                for yol in ("ok", "xato", "login"):
                    with mock.patch.dict(os.environ, {"GOOGLE_SHEET_WEBHOOK_URL": f"http://127.0.0.1:{port}/{yol}"}):
                        natija[yol] = await b.google_sheetsga_yozish({"ism": "x"})
            finally:
                await runner.cleanup()
            return natija

        self.assertEqual(asyncio.run(oqim()), {"ok": True, "xato": False, "login": False})


class DarslarTest(unittest.TestCase):
    def test_dars_korsatmaga_qoshiladi(self):
        _tozalash()
        db.add_dars("Mijoz chegirma so'rasa, menejer bog'lanishini ayt")
        b.DARSLAR = b.darslarni_yuklash()
        self.addCleanup(setattr, b, "DARSLAR", "")
        self.assertIn("chegirma so'rasa", b.tizim_korsatmasi())
        self.assertIn("MENEJER DARSLARI", b.tizim_korsatmasi())


if __name__ == "__main__":
    unittest.main()
