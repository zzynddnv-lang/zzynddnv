"""
Asosiy mantiq uchun testlar (standart unittest, qo'shimcha paket kerak emas).

Ishga tushirish:
    python -m unittest discover -s tests -v
"""

import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest

# Testlar vaqtinchalik baza va sozlamalar bilan ishlaydi (haqiqiy bazaga tegmaydi)
_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["CSV_PATH"] = os.path.join(_TMP, "test.csv")
os.environ["OWNER_ID"] = "111, 222"
os.environ["EGA_ISMI"] = "Zuxriddin"
os.environ["GOOGLE_SHEET_WEBHOOK_URL"] = ""  # .env dagi haqiqiy webhook ishlatilmasin

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402
import zuxriddin_yordamchi_bot as b  # noqa: E402


class JavobAjratishTest(unittest.TestCase):
    def test_lead_tegi_ajratiladi(self):
        javob, tayyor, xulosa = b.toza_javob_ajratish("Rahmat!\n[LEAD: Ali, +998901234567, IT, Hamkorlik]")
        self.assertEqual(javob, "Rahmat!")
        self.assertTrue(tayyor)
        self.assertIn("Ali", xulosa)

    def test_think_bloki_olib_tashlanadi(self):
        javob, tayyor, _ = b.toza_javob_ajratish("<think>ichki fikr</think>\nSalom, qanday yordam kerak?")
        self.assertEqual(javob, "Salom, qanday yordam kerak?")
        self.assertFalse(tayyor)

    def test_yopilmagan_think_bloki(self):
        javob, _, _ = b.toza_javob_ajratish("<think>kesilib qolgan fikr")
        self.assertEqual(javob, "")

    def test_json_javob(self):
        javob, tayyor, xulosa = b.toza_javob_ajratish('```json\n{"javob": "Ok", "tayyor": true, "xulosa": "X"}\n```')
        self.assertEqual((javob, tayyor, xulosa), ("Ok", True, "X"))


class SalomTest(unittest.TestCase):
    def test_birinchi_xabarga_salom_qoshiladi(self):
        self.assertTrue(b.salomni_moslash("Qanday yordam kerak?", True).startswith(b.SALOM_MATNI))

    def test_keyingi_xabarda_salom_olib_tashlanadi(self):
        self.assertEqual(b.salomni_moslash(b.SALOM_MATNI + " Albatta.", False), "Albatta.")


class TelefonVaHtmlTest(unittest.TestCase):
    def test_telefon_regex(self):
        for tel in ["+998 90 123 45 67", "998901234567", "90-123-45-67"]:
            self.assertIsNotNone(b.PHONE_REGEX.search(f"raqamim {tel}"), tel)
        self.assertIsNone(b.PHONE_REGEX.search("narxi 1000 so'm"))

    def test_html_escape(self):
        self.assertEqual(b.h("<b>Ali & Vali</b>"), "&lt;b&gt;Ali &amp; Vali&lt;/b&gt;")
        self.assertEqual(b.h(None), "")

    def test_maktab_rad_etish_tozalanadi(self):
        tarix = [{"role": "user", "content": "Hamkorlik haqida gaplashsak"}]
        javob = b.tozalash_asossiz_maktab_rad_etish("Kechirasiz, men maktab misollarini yechmayman. Albatta!", tarix)
        self.assertEqual(javob, "Albatta!")


class EgaHuquqlariTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        b.egalar.clear()

    def test_owner_id_ruxsati(self):
        self.assertEqual(b.OWNER_IDS, {111, 222})
        self.assertTrue(b.egami(111))
        self.assertFalse(b.egami(999))
        self.assertFalse(b.egami(None))

    def test_bazadagi_begona_ega_emas(self):
        # Avval /start orqali qo'shilib qolgan begona foydalanuvchi OWNER_ID bo'lsa huquq olmaydi
        db.save_owner_id(999)
        self.assertFalse(b.egami(999))
        self.assertNotIn(999, b.hisobot_oluvchilar(None))

    def test_business_egasi(self):
        b.egalar["conn1"] = 555
        self.assertTrue(b.egami(555))
        self.assertIn(555, b.hisobot_oluvchilar(555))

    def test_idlarni_oqish(self):
        self.assertEqual(b._idlarni_oqish("1, 2 3,x"), {1, 2, 3})
        self.assertEqual(b._idlarni_oqish(""), set())


class BazaTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db.get_db() as conn:
            conn.execute("DELETE FROM leads")

    def test_lead_dublikat_bolmaydi(self):
        self.assertTrue(db.upsert_lead(42, "Ali", "@ali", 42, "birinchi", telefon="+998901234567"))
        self.assertFalse(db.upsert_lead(42, "Ali", "@ali", 42, "ikkinchi"))
        leadlar = db.get_all_leads()
        self.assertEqual(len(leadlar), 1)
        self.assertEqual(leadlar[0]["xulosa"], "ikkinchi")
        self.assertEqual(db.get_last_lead_summary(42), "ikkinchi")

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
        self.assertIn("updated_at", ustunlar)

    def test_csv_eksport(self):
        db.upsert_lead(7, "Vali", "", 7, "xulosa, vergul bilan")
        self.assertTrue(asyncio.run(b.csv_yangilash()))
        with open(os.environ["CSV_PATH"], encoding="utf-8-sig") as f:
            qatorlar = f.read().splitlines()
        self.assertEqual(len(qatorlar), 2)
        self.assertIn("Vali", qatorlar[1])

    def test_sheets_sozlanmagan(self):
        self.assertIsNone(asyncio.run(b.google_sheetsga_yozish({"ism": "x"})))


if __name__ == "__main__":
    unittest.main()
