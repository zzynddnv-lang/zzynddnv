"""
ZUXRIDDIN YORDAMCHISI - Ma'lumotlar bazasi moduli (SQLite)
Suhbatlar tarixi, mijozlar holati va leadlarni doimiy saqlash uchun.
Ulanishlar sizib ketishini (connection leak) oldini oluvchi contextmanager,
WAL rejim (yuqori tezlik) va indekslar bilan jihozlangan.
"""

import sqlite3
import os
import contextlib
from datetime import datetime
from typing import List, Dict, Tuple, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FAYLI = os.path.join(BASE_DIR, "yordamchi_bot.db")


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


def init_db():
    """Jadvallarni va unumdorlik indekslarini yaratish."""
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
        
        # Eski bazalar uchun owner_last_active ustunini tekshirib qo'shish
        try:
            cursor.execute("ALTER TABLE chats ADD COLUMN owner_last_active TEXT;")
        except Exception:
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
        
        # 4) Murojaatlar (dosyelar / leadlar) jadvali
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
                mahsulot TEXT,
                profil TEXT,
                miqdor TEXT,
                manzil TEXT,
                zamer TEXT,
                holat TEXT DEFAULT 'Yangi',
                created_at TEXT
            )
        """)
        
        # Yangi ustunlar mavjud bo'lmasa, avtomatik qo'shish (migratsiya)
        yangi_ustunlar = [
            ("telefon", "TEXT"),
            ("tashkilot", "TEXT"),
            ("mavzu", "TEXT"),
            ("muhimlik", "TEXT"),
            ("mahsulot", "TEXT"),
            ("profil", "TEXT"),
            ("miqdor", "TEXT"),
            ("manzil", "TEXT"),
            ("zamer", "TEXT"),
            ("holat", "TEXT DEFAULT 'Yangi'"),
        ]
        for ustun_nomi, ustun_turi in yangi_ustunlar:
            try:
                cursor.execute(f"ALTER TABLE leads ADD COLUMN {ustun_nomi} {ustun_turi};")
            except Exception:
                pass
        
        # 5) So'rovlarni tezlashtiruvchi indekslar
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
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cursor.execute("""
            UPDATE chats SET is_completed = 0, owner_last_active = NULL, updated_at = ? WHERE chat_id = ?
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
            except Exception:
                return None
        return None


def get_last_lead_summary(chat_id: int) -> Optional[str]:
    """Chat bo'yicha oxirgi saqlangan lead xulosasini qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT xulosa FROM leads 
            WHERE chat_id = ? 
            ORDER BY id DESC LIMIT 1
        """, (chat_id,))
        row = cursor.fetchone()
        return row["xulosa"] if row else None


def is_chat_completed(chat_id: int) -> bool:
    """Chatdagi suhbat yakunlangan yoki yo'qligini tekshiradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_completed FROM chats WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return bool(row["is_completed"]) if row else False


def mark_chat_completed(chat_id: int):
    """Chatni yakunlangan deb belgilaydi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chats SET is_completed = 1, updated_at = ? WHERE chat_id = ?
        """, (vaqt, chat_id))


def reset_chat(chat_id: int):
    """Chatni qayta faollashtiradi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chats SET is_completed = 0, owner_last_active = NULL, updated_at = ? WHERE chat_id = ?
        """, (vaqt, chat_id))


def record_owner_activity(chat_id: int):
    """Bot egasi mijoz bilan o'zi yozishganda vaqtini saqlaydi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            except Exception:
                return False
        return False


def clear_owner_activity(chat_id: int):
    """Bot egasi faolligini tozalash (botni ushbu chatda yana avtomatlashtirish)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE chats SET owner_last_active = NULL WHERE chat_id = ?", (chat_id,))


def save_lead(
    chat_id: int,
    full_name: str,
    username: str,
    telegram_id: int,
    xulosa: str,
    telefon: str = "",
    tashkilot: str = "",
    mavzu: str = "",
    muhimlik: str = "Oddiy",
    mahsulot: str = "",
    profil: str = "",
    miqdor: str = "",
    manzil: str = "",
    zamer: str = "",
    holat: str = "🟡 Yangi murojaat",
):
    """Yangi murojaat dosyesini SQLite bazasiga saqlaydi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO leads (
                chat_id, full_name, username, telegram_id, xulosa,
                telefon, tashkilot, mavzu, muhimlik, mahsulot, profil, miqdor, manzil, zamer, holat, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chat_id, full_name, username, telegram_id, xulosa,
            telefon, tashkilot, mavzu, muhimlik, mahsulot, profil, miqdor, manzil, zamer, holat, vaqt
        ))


def get_recent_leads(limit: int = 5) -> List[sqlite3.Row]:
    """Oxirgi kelgan murojaatlar ro'yxatini qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, username, telegram_id, xulosa, telefon, tashkilot, mavzu, muhimlik, mahsulot, profil, miqdor, manzil, zamer, holat, created_at
            FROM leads
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def get_all_leads() -> List[sqlite3.Row]:
    """Barcha murojaatlar ro'yxatini eksport uchun qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, username, telegram_id, xulosa, telefon, tashkilot, mavzu, muhimlik, mahsulot, profil, miqdor, manzil, zamer, holat, created_at
            FROM leads
            ORDER BY id DESC
        """)
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
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS owners (user_id INTEGER PRIMARY KEY, updated_at TEXT);")
        cursor.execute("INSERT OR REPLACE INTO owners (user_id, updated_at) VALUES (?, ?);", (user_id, vaqt))


def get_owner_ids() -> List[int]:
    """Barcha ro'yxatdan o'tgan bot egalarining ID larini qaytaradi."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS owners (user_id INTEGER PRIMARY KEY, updated_at TEXT);")
        cursor.execute("SELECT user_id FROM owners;")
        return [row["user_id"] for row in cursor.fetchall()]
