"""
Mahalliy vaqt (Toshkent). Server (Render) UTC da ishlaydi - barcha vaqtlar shu modul orqali olinadi.
O'zbekistonda yozgi vaqt yo'q, shuning uchun tzdata bo'lmasa ham doimiy UTC+5 to'g'ri ishlaydi.
"""

import os
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    MINTAQA = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
except Exception:  # Windows'da tzdata o'rnatilmagan bo'lishi mumkin
    MINTAQA = timezone(timedelta(hours=5))


def hozir() -> datetime:
    """Mahalliy vaqt (tzinfo siz - bazada matn ko'rinishida saqlanadi)."""
    return datetime.now(MINTAQA).replace(tzinfo=None)


def hozir_matn(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return hozir().strftime(fmt)
