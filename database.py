"""
ZUXRIDDIN YORDAMCHISI - Ma'lumotlar bazasi moduli (SQLite)
Suhbatlar tarixi, mijozlar holati va leadlarni doimiy saqlash uchun.
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Tuple, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FAYLI = os.path.join(BASE_DIR, "yordamchi_bot.db")


def get_connection():
    """SQLite ulanishini ochadi."""
    conn = sqlite3.connect(DB_FAYLI)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Jadvallarni yaratish (agar mavjud bo'lmasa)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1) Chatlar holati jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                ega_id INTEGER,
                is_completed INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        # 2) Suhbat xabarlari tarixi jadvali
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
        
        # 3) Leadlar (saralangan mijozlar) jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                full_name TEXT,
                username TEXT,
                telegram_id INTEGER,
                xulosa TEXT,
                created_at TEXT
            )
        """)
        conn.commit()


def get_chat_history(chat_id: int, limit: int = 12) -> List[Dict[str, str]]:
    """Chatning oxirgi xabarlar tarixini oladi (buzilgan yoki chala xabarlarni chetlab o'tadi)."""
    with get_connection() as conn:
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
    with get_connection() as conn:
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
        conn.commit()


def delete_last_message(chat_id: int):
    """Xatolik yuz berganda oxirgi xabarni o'chiradi."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM messages 
            WHERE id = (SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1)
        """, (chat_id,))
        conn.commit()


def clear_chat_history(chat_id: int):
    """Chat xabarlar tarixini tozalaydi va holatni faollashtiradi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cursor.execute("""
            UPDATE chats SET is_completed = 0, updated_at = ? WHERE chat_id = ?
        """, (vaqt, chat_id))
        conn.commit()


def get_last_message_time(chat_id: int) -> Optional[datetime]:
    """Chatdagi eng oxirgi xabar vaqtini oladi."""
    with get_connection() as conn:
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
    with get_connection() as conn:
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
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_completed FROM chats WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return bool(row["is_completed"]) if row else False


def mark_chat_completed(chat_id: int):
    """Chatni yakunlangan deb belgilaydi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chats SET is_completed = 1, updated_at = ? WHERE chat_id = ?
        """, (vaqt, chat_id))
        conn.commit()


def reset_chat(chat_id: int):
    """Chatni qayta faollashtiradi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE chats SET is_completed = 0, updated_at = ? WHERE chat_id = ?
        """, (vaqt, chat_id))
        conn.commit()


def save_lead(chat_id: int, full_name: str, username: str, telegram_id: int, xulosa: str):
    """Yangi leadni ma'lumotlar bazasiga saqlaydi."""
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO leads (chat_id, full_name, username, telegram_id, xulosa, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, full_name, username, telegram_id, xulosa, vaqt))
        conn.commit()


def get_recent_leads(limit: int = 5) -> List[sqlite3.Row]:
    """Oxirgi kelgan leadlar ro'yxatini qaytaradi."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, full_name, username, telegram_id, xulosa, created_at
            FROM leads
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def get_stats() -> Dict[str, int]:
    """Baza bo'yicha umumiy statistikani hisoblaydi."""
    with get_connection() as conn:
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
