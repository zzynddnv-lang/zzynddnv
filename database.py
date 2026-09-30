"""
SAVDO BOT - Ma'lumotlar bazasi moduli (SQLite)
Suhbatlar tarixi, mijozlar kartochkalari (CRM) va narx so'rovlarini doimiy saqlash uchun.
Ulanishlar sizib ketishini (connection leak) oldini oluvchi contextmanager,
WAL rejim (yuqori tezlik) va indekslar bilan jihozlangan.

Baza fayli manzili DB_PATH muhit o'zgaruvchisi orqali o'zgartirilishi mumkin
(masalan, doimiy disk ulangan serverlarda).
"""

import sqlite3
import os
import contextlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FAYLI = os.getenv("DB_PATH") or os.path.join(BASE_DIR, "yordamchi_bot.db")

# Eski (AKFA savdo boti davridan qolgan) va endi ishlatilmaydigan ustunlar
ESKI_USTUNLAR = ["profil", "manzil", "zamer"]

# Narx so'rovi holatlari
FAOL_SOROV_HOLATLARI = ("kutilmoqda", "narx_kiritilmoqda", "tasdiq_kutilmoqda")


@contextlib.contextmanager
def get_db():
    """
    Xavfsiz SQLite ulanishini ochadi, tranzaksiyani avtomatik commit qiladi
    va ulanishni albatta yopadi (connection leak bo'lmaydi).
    """
    conn = sqlite3.connect(DB_FAYLI, timeout=25.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _hozir(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


def init_db():
    """Jadvallarni va unumdorlik indekslarini yaratish."""
    papka = os.path.dirname(DB_FAYLI)
    if papka:
        os.makedirs(papka, exist_ok=True)

    with get_db() as conn:
        cursor = conn.cursor()

        # 1) Tezlikni oshirish va bloklanishlarni oldini olish uchun WAL rejimi
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")

        # 2) Chatlar holati jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                ega_id INTEGER,
                is_completed INTEGER DEFAULT 0,
                owner_last_active TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # Eski bazalar uchun yangi ustunlarni tekshirib qo'shish
        for ustun_nomi, ustun_turi in [
            ("owner_last_active", "TEXT"),
            ("til", "TEXT"),
            ("business_connection_id", "TEXT"),
            ("mijoz_id", "INTEGER"),
            ("menejer_chaqirilgan", "TEXT"),
            ("taqdimot_at", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE chats ADD COLUMN {ustun_nomi} {ustun_turi};")
            except sqlite3.OperationalError:
                pass

        # 3) Suhbat xabarlari tarixi jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id)
            )
        """)

        # 4) Murojaatlar (dosyelar / leadlar) jadvali - har bir chat uchun bitta qator
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                full_name TEXT,
                username TEXT,
                telegram_id INTEGER,
                xulosa TEXT,
                telefon TEXT,
                tashkilot TEXT,
                mavzu TEXT,
                muhimlik TEXT,
                holat TEXT DEFAULT 'Yangi',
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # Yangi ustunlar mavjud bo'lmasa, avtomatik qo'shish (migratsiya)
        for ustun_nomi, ustun_turi in [
            ("telefon", "TEXT"),
            ("tashkilot", "TEXT"),
            ("mavzu", "TEXT"),
            ("muhimlik", "TEXT"),
            ("holat", "TEXT DEFAULT 'Yangi'"),
            ("updated_at", "TEXT"),
            ("lavozim", "TEXT"),
            ("mahsulot", "TEXT"),
            ("bosqich", "TEXT"),
            ("harorat", "TEXT"),
            ("summa", "INTEGER"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE leads ADD COLUMN {ustun_nomi} {ustun_turi};")
            except sqlite3.OperationalError:
                pass

        # Eski, ishlatilmaydigan ustunlarni olib tashlash (SQLite >= 3.35)
        for ustun_nomi in ESKI_USTUNLAR:
            try:
                cursor.execute(f"ALTER TABLE leads DROP COLUMN {ustun_nomi};")
            except sqlite3.OperationalError:
                pass

        # 5) Narx so'rovlari (ombor mas'uli narx va qoldiqni tasdiqlaydi)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sorovlar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                mijoz_id INTEGER,
                business_connection_id TEXT,
                til TEXT,
                pozitsiyalar TEXT,
                kalit TEXT,
                izoh TEXT,
                holat TEXT,
                narxlar TEXT,
                ombor_izohi TEXT,
                summa INTEGER,
                sklad_chat_id INTEGER,
                sklad_msg_id INTEGER,
                prompt_msg_id INTEGER,
                eslatildi INTEGER DEFAULT 0,
                kuzatildi INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                yuborilgan_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sorovlar_chat ON sorovlar (chat_id, id DESC);")

        # 6) Tizim sozlamalari (masalan, suhbat versiyasi)
        cursor.execute("CREATE TABLE IF NOT EXISTS meta (kalit TEXT PRIMARY KEY, qiymat TEXT);")

        # 6a) Bot egalari jadvali
        cursor.execute("CREATE TABLE IF NOT EXISTS owners (user_id INTEGER PRIMARY KEY, updated_at TEXT);")

        # 7) So'rovlarni tezlashtiruvchi indekslar
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages (chat_id, id DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_chat_id ON leads (chat_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_completed ON chats (is_completed);")


def get_chat_history(chat_id: int, limit: int = 12) -> List[Dict[str, str]]:
    """Chatning oxirgi xabarlar tarixini oladi (buzilgan yoki chala xabarlarni chetlab o'tadi)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM (
                SELECT id, role, content FROM messages
                WHERE chat_id = ?
                  AND length(content) > 3
                  AND content NOT IN ('AK', 'Salom! Xush')
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
        """, (chat_id, limit))
        rows = cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]


def add_message(chat_id: int, role: str, content: str):
    """Suhbatga yangi xabar qo'shadi."""
    vaqt = _hozir()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chats (chat_id, is_completed, created_at, updated_at)
            VALUES (?, 0, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET updated_at = ?
        """, (chat_id, vaqt, vaqt, vaqt))

        cursor.execute("""
            INSERT INTO messages (chat_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (chat_id, role, content, vaqt))


def delete_last_message(chat_id: int):
    """Xatolik yuz berganda oxirgi xabarni o'chiradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM messages
            WHERE id = (SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1)
        """, (chat_id,))


def clear_chat_history(chat_id: int):
    """Chat xabarlar tarixini tozalaydi va holatni faollashtiradi."""
    vaqt = _hozir()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cursor.execute("""
            UPDATE chats SET is_completed = 0, owner_last_active = NULL, taqdimot_at = NULL, updated_at = ? WHERE chat_id = ?
        """, (vaqt, chat_id))


def get_last_message_time(chat_id: int) -> Optional[datetime]:
    """Chatdagi eng oxirgi xabar vaqtini oladi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT created_at FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC LIMIT 1
        """, (chat_id,))
        row = cursor.fetchone()
        if row and row["created_at"]:
            try:
                return datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        return None




def mark_chat_completed(chat_id: int):
    """Chatda murojaat dosyesi shakllanganini belgilaydi (statistika uchun)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chats SET is_completed = 1, updated_at = ? WHERE chat_id = ?
        """, (_hozir(), chat_id))


def record_owner_activity(chat_id: int):
    """Bot egasi mijoz bilan o'zi yozishganda vaqtini saqlaydi."""
    vaqt = _hozir()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chats (chat_id, is_completed, owner_last_active, created_at, updated_at)
            VALUES (?, 0, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET owner_last_active = ?, updated_at = ?
        """, (chat_id, vaqt, vaqt, vaqt, vaqt, vaqt))


def is_owner_recently_active(chat_id: int, minutes: int = 30) -> bool:
    """Bot egasi oxirgi belgilangan daqiqalarda chatda faol bo'lganini tekshiradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT owner_last_active FROM chats WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["owner_last_active"]:
            try:
                last_time = datetime.strptime(row["owner_last_active"], "%Y-%m-%d %H:%M:%S")
                return (datetime.now() - last_time).total_seconds() < (minutes * 60)
            except ValueError:
                return False
        return False


def clear_owner_activity(chat_id: int):
    """Bot egasi faolligini tozalash (botni ushbu chatda yana avtomatlashtirish)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE chats SET owner_last_active = NULL WHERE chat_id = ?", (chat_id,))


LEAD_MAYDONLARI = (
    "full_name", "username", "telegram_id", "xulosa", "telefon", "tashkilot", "lavozim",
    "mavzu", "muhimlik", "mahsulot", "bosqich", "harorat", "summa", "holat",
)


def upsert_lead(chat_id: int, **maydonlar) -> bool:
    """
    Mijoz (lead) kartochkasini saqlaydi. Chat uchun kartochka mavjud bo'lsa, yangi qator
    qo'shmasdan yangilaydi. Bo'sh qiymatlar mavjud ma'lumotni o'chirib yubormaydi.
    Qaytaradi: True - yangi kartochka yaratildi, False - mavjudi yangilandi.
    """
    noma_lum = set(maydonlar) - set(LEAD_MAYDONLARI)
    if noma_lum:
        raise ValueError(f"Noma'lum maydonlar: {noma_lum}")
    toldirilgan = {k: v for k, v in maydonlar.items() if v not in (None, "")}

    vaqt = _hozir("%Y-%m-%d %H:%M")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM leads WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,))
        row = cursor.fetchone()
        if row:
            if toldirilgan:
                ustunlar = ", ".join(f"{k} = ?" for k in toldirilgan)
                cursor.execute(
                    f"UPDATE leads SET {ustunlar}, updated_at = ? WHERE id = ?",
                    (*toldirilgan.values(), vaqt, row["id"]),
                )
            return False

        ustunlar = ["chat_id", *toldirilgan, "created_at", "updated_at"]
        cursor.execute(
            f"INSERT INTO leads ({', '.join(ustunlar)}) VALUES ({', '.join('?' for _ in ustunlar)})",
            (chat_id, *toldirilgan.values(), vaqt, vaqt),
        )
        return True


def get_lead(chat_id: int) -> Optional[sqlite3.Row]:
    """Chat bo'yicha mijoz kartochkasini qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {_LEAD_USTUNLARI} FROM leads WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,))
        return cursor.fetchone()


_LEAD_USTUNLARI = (
    "id, chat_id, full_name, username, telegram_id, xulosa, telefon, tashkilot, lavozim, "
    "mavzu, muhimlik, mahsulot, bosqich, harorat, summa, holat, created_at, updated_at"
)


def get_recent_leads(limit: int = 5) -> List[sqlite3.Row]:
    """Oxirgi kelgan murojaatlar ro'yxatini qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {_LEAD_USTUNLARI} FROM leads ORDER BY id DESC LIMIT ?", (limit,))
        return cursor.fetchall()


def get_all_leads() -> List[sqlite3.Row]:
    """Barcha murojaatlar ro'yxatini eksport uchun qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {_LEAD_USTUNLARI} FROM leads ORDER BY id DESC")
        return cursor.fetchall()


def get_stats() -> Dict[str, int]:
    """Baza bo'yicha umumiy statistikani hisoblaydi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM leads")
        total_leads = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM chats WHERE is_completed = 0")
        active_chats = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM chats WHERE is_completed = 1")
        completed_chats = cursor.fetchone()[0]

        return {
            "total_leads": total_leads,
            "active_chats": active_chats,
            "completed_chats": completed_chats,
        }


def save_owner_id(user_id: int):
    """Bot egasining Telegram ID sini bazada saqlaydi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO owners (user_id, updated_at) VALUES (?, ?);", (user_id, _hozir()))


def get_owner_ids() -> List[int]:
    """Barcha ro'yxatdan o'tgan bot egalarining ID larini qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM owners;")
        return [row["user_id"] for row in cursor.fetchall()]


# =====================================================================
#  CHAT MA'LUMOTLARI (til, business ulanish)
# =====================================================================

def save_chat_meta(chat_id: int, mijoz_id: Optional[int], business_connection_id: Optional[str], til: Optional[str] = None):
    """Mijozga keyinroq (masalan, ombor narx bergach) xabar yuborish uchun kerakli ma'lumotlarni saqlaydi."""
    vaqt = _hozir()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO chats (chat_id, is_completed, mijoz_id, business_connection_id, til, created_at, updated_at)
            VALUES (?, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                mijoz_id = COALESCE(excluded.mijoz_id, mijoz_id),
                business_connection_id = excluded.business_connection_id,
                til = COALESCE(excluded.til, til),
                updated_at = excluded.updated_at
        """, (chat_id, mijoz_id, business_connection_id, til, vaqt, vaqt))


def get_chat_meta(chat_id: int) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT chat_id, mijoz_id, business_connection_id, til FROM chats WHERE chat_id = ?",
            (chat_id,),
        )
        return cursor.fetchone()


def menejer_chaqirish_mumkinmi(chat_id: int, minutes: int = 60) -> bool:
    """Menejerga bir chat bo'yicha tez-tez bildirishnoma yuborilmasligi uchun (spamdan himoya)."""
    hozir = datetime.now()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT menejer_chaqirilgan FROM chats WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["menejer_chaqirilgan"]:
            try:
                oxirgi = datetime.strptime(row["menejer_chaqirilgan"], "%Y-%m-%d %H:%M:%S")
                if (hozir - oxirgi).total_seconds() < minutes * 60:
                    return False
            except ValueError:
                pass
        vaqt = hozir.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO chats (chat_id, is_completed, menejer_chaqirilgan, created_at, updated_at)
            VALUES (?, 0, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET menejer_chaqirilgan = excluded.menejer_chaqirilgan
        """, (chat_id, vaqt, vaqt, vaqt))
        return True


def get_last_user_message_time(chat_id: int) -> Optional[datetime]:
    """Mijozning oxirgi xabari vaqti."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT created_at FROM messages WHERE chat_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        row = cursor.fetchone()
    if row and row["created_at"]:
        try:
            return datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


# =====================================================================
#  NARX SO'ROVLARI
# =====================================================================

_SOROV_USTUNLARI = (
    "id, chat_id, mijoz_id, business_connection_id, til, pozitsiyalar, kalit, izoh, holat, narxlar, "
    "ombor_izohi, summa, sklad_chat_id, sklad_msg_id, prompt_msg_id, eslatildi, kuzatildi, "
    "created_at, updated_at, yuborilgan_at"
)


def create_sorov(chat_id: int, mijoz_id: int, business_connection_id: Optional[str], til: str,
                 pozitsiyalar_json: str, kalit: str, izoh: str) -> int:
    vaqt = _hozir()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sorovlar (chat_id, mijoz_id, business_connection_id, til, pozitsiyalar, kalit, izoh,
                                  holat, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'kutilmoqda', ?, ?)
        """, (chat_id, mijoz_id, business_connection_id, til, pozitsiyalar_json, kalit, izoh, vaqt, vaqt))
        return cursor.lastrowid


def get_sorov(sorov_id: int) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT {_SOROV_USTUNLARI} FROM sorovlar WHERE id = ?", (sorov_id,))
        return cursor.fetchone()


def get_faol_sorov(chat_id: int) -> Optional[sqlite3.Row]:
    """Chat bo'yicha ombor hali javob bermagan (faol) so'rov."""
    belgilar = ",".join("?" for _ in FAOL_SOROV_HOLATLARI)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_SOROV_USTUNLARI} FROM sorovlar WHERE chat_id = ? AND holat IN ({belgilar}) ORDER BY id DESC LIMIT 1",
            (chat_id, *FAOL_SOROV_HOLATLARI),
        )
        return cursor.fetchone()


def get_oxirgi_taklif(chat_id: int) -> Optional[sqlite3.Row]:
    """Chat bo'yicha mijozga yuborilgan oxirgi tijorat taklifi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_SOROV_USTUNLARI} FROM sorovlar WHERE chat_id = ? AND holat = 'yuborildi' ORDER BY id DESC LIMIT 1",
            (chat_id,),
        )
        return cursor.fetchone()




_SOROV_YANGILANADIGAN = {
    "narxlar", "ombor_izohi", "summa", "sklad_chat_id", "sklad_msg_id", "prompt_msg_id",
    "eslatildi", "kuzatildi", "yuborilgan_at",
}


def update_sorov(sorov_id: int, **maydonlar):
    noma_lum = set(maydonlar) - _SOROV_YANGILANADIGAN
    if noma_lum:
        raise ValueError(f"Noma'lum maydonlar: {noma_lum}")
    if not maydonlar:
        return
    ustunlar = ", ".join(f"{k} = ?" for k in maydonlar)
    with get_db() as conn:
        conn.execute(
            f"UPDATE sorovlar SET {ustunlar}, updated_at = ? WHERE id = ?",
            (*maydonlar.values(), _hozir(), sorov_id),
        )


def sorov_holatini_ozgartirish(sorov_id: int, eski_holatlar: tuple, yangi_holat: str) -> bool:
    """
    Holatni ATOMAR o'zgartiradi: faqat so'rov hozir eski_holatlar dan birida bo'lsa.
    Tugma ikki marta bosilsa yoki ikki kishi bir vaqtda bossa - faqat bittasi o'tadi.
    """
    belgilar = ",".join("?" for _ in eski_holatlar)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE sorovlar SET holat = ?, updated_at = ? WHERE id = ? AND holat IN ({belgilar})",
            (yangi_holat, _hozir(), sorov_id, *eski_holatlar),
        )
        return cursor.rowcount == 1


def get_eslatiladigan_sorovlar(daqiqa: int) -> List[sqlite3.Row]:
    """Ombor belgilangan vaqtdan beri javob bermagan va hali eslatilmagan so'rovlar."""
    chegara = (datetime.now() - timedelta(minutes=daqiqa)).strftime("%Y-%m-%d %H:%M:%S")
    belgilar = ",".join("?" for _ in FAOL_SOROV_HOLATLARI)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_SOROV_USTUNLARI} FROM sorovlar WHERE holat IN ({belgilar}) AND eslatildi = 0 AND created_at <= ?",
            (*FAOL_SOROV_HOLATLARI, chegara),
        )
        return cursor.fetchall()


def get_kuzatiladigan_takliflar(soat: int) -> List[sqlite3.Row]:
    """Taklif yuborilganidan beri belgilangan vaqt o'tgan va menejerga hali eslatilmagan takliflar."""
    chegara = (datetime.now() - timedelta(hours=soat)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_SOROV_USTUNLARI} FROM sorovlar WHERE holat = 'yuborildi' AND kuzatildi = 0 AND yuborilgan_at <= ?",
            (chegara,),
        )
        return cursor.fetchall()


def get_faol_sorovlar() -> List[sqlite3.Row]:
    """Barcha javob kutilayotgan so'rovlar (/sorovlar buyrug'i uchun)."""
    belgilar = ",".join("?" for _ in FAOL_SOROV_HOLATLARI)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {_SOROV_USTUNLARI} FROM sorovlar WHERE holat IN ({belgilar}) ORDER BY id DESC",
            FAOL_SOROV_HOLATLARI,
        )
        return cursor.fetchall()


# =====================================================================
#  TAQDIMOT VA SUHBAT VERSIYASI
# =====================================================================

def taqdimot_yuborilganmi(chat_id: int) -> bool:
    """Ushbu chatga kompaniya taqdimoti (joriy sessiyada) yuborilganmi?"""
    with get_db() as conn:
        row = conn.execute("SELECT taqdimot_at FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return bool(row and row["taqdimot_at"])


def taqdimot_belgilash(chat_id: int):
    vaqt = _hozir()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO chats (chat_id, is_completed, taqdimot_at, created_at, updated_at)
            VALUES (?, 0, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET taqdimot_at = excluded.taqdimot_at
        """, (chat_id, vaqt, vaqt, vaqt))


def suhbat_versiyasini_yangilash(versiya: str) -> bool:
    """
    Bot versiyasi o'zgargan bo'lsa (masalan, shaxsiy yordamchidan savdo botiga), eski suhbat tarixini
    bir marta tozalaydi - AI eski uslubni takrorlamasligi uchun. Mijoz kartochkalari (leads) saqlanadi.
    Qaytaradi: True - tarix tozalandi.
    """
    with get_db() as conn:
        row = conn.execute("SELECT qiymat FROM meta WHERE kalit = 'suhbat_versiyasi'").fetchone()
        if row and row["qiymat"] == versiya:
            return False
        conn.execute("DELETE FROM messages")
        conn.execute("UPDATE chats SET taqdimot_at = NULL, owner_last_active = NULL")
        conn.execute(
            "INSERT OR REPLACE INTO meta (kalit, qiymat) VALUES ('suhbat_versiyasi', ?)", (versiya,)
        )
        return True
