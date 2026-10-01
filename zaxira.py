"""
BAZANI TELEGRAM ORQALI ZAXIRALASH (Render Free kabi diski o'chib ketadigan serverlar uchun).

Render Free'da har deploy/restartda disk tozalanadi - SQLite bazasi (mijozlar, suhbatlar, taklif raqamlari)
yo'qolardi. Bu modul bepul va qo'shimcha xizmatsiz yechim:
  - har ZAXIRA_ORALIQ daqiqada (baza o'zgargan bo'lsa) bazaning siqilgan nusxasini zaxira chatiga yuboradi
    va uni pin qiladi (oldingi nusxa o'chiriladi);
  - server o'chayotganda (deploy) oxirgi nusxani albatta yuboradi;
  - server yangi ishga tushganda diskda baza bo'lmasa - pin qilingan nusxadan tiklaydi.

Zaxira chati: ZAXIRA_CHAT_ID (alohida yopiq guruh yoki kanal tavsiya etiladi, bot admin bo'lishi kerak),
bo'lmasa - birinchi OWNER_ID ning bot bilan shaxsiy chati. ZAXIRA_CHAT_ID=0 - zaxiralash o'chiriladi.
"""

import asyncio
import gzip
import hashlib
import io
import logging
import os

from aiogram import types

import database as db
from vaqt import hozir_matn

FAYL_PREFIKSI = "umatic_baza_"
ZAXIRA_ORALIQ = int(os.getenv("ZAXIRA_ORALIQ", "5")) * 60
# Render'da yangi nusxa ishga tushganda eski nusxa o'chishini va yakuniy zaxirasini kutish (soniya)
TIKLASH_KUTISH = int(os.getenv("TIKLASH_KUTISH", "25" if os.getenv("RENDER") else "0"))
MAKS_HAJM = 19 * 1024 * 1024  # Telegram bot API yuklab olish chegarasi 20 MB

# bloklangan: zaxiradan tiklash xato bilan tugadi - bo'sh baza yaxshi zaxira ustiga yozilib ketmasligi uchun
# bu ishga tushishda yangi zaxira yuborilmaydi
_holat = {"xesh": None, "msg_id": None, "bloklangan": False}


def zaxira_chati(owner_ids) -> int | None:
    qiymat = os.getenv("ZAXIRA_CHAT_ID", "").strip()
    if qiymat == "0":
        return None
    if qiymat.lstrip("-").isdigit():
        return int(qiymat)
    return min(owner_ids) if owner_ids else None


async def tiklash(bot, chat_id: int | None) -> bool:
    """Diskda baza bo'lmasa - zaxira chatidagi pin qilingan oxirgi nusxadan tiklaydi."""
    if chat_id is None:
        logging.warning("Zaxira chati yo'q (OWNER_ID yoki ZAXIRA_CHAT_ID) - baza server qayta ishga tushganda yo'qolishi mumkin.")
        return False
    if await asyncio.to_thread(db.baza_bormi):
        return False
    if TIKLASH_KUTISH:
        logging.info("Eski server nusxasining yakuniy zaxirasi kutilmoqda (%s s)...", TIKLASH_KUTISH)
        await asyncio.sleep(TIKLASH_KUTISH)
    try:
        chat = await bot.get_chat(chat_id)
        pin = chat.pinned_message
        if not pin or not pin.document or not (pin.document.file_name or "").startswith(FAYL_PREFIKSI):
            logging.info("Zaxira nusxa topilmadi - yangi baza bilan ishlanadi.")
            return False
        bufer = io.BytesIO()
        await bot.download(pin.document.file_id, destination=bufer)
        data = gzip.decompress(bufer.getvalue())
        await asyncio.to_thread(db.restore_bytes, data)
        _holat["xesh"] = hashlib.sha256(data).hexdigest()
        _holat["msg_id"] = pin.message_id
        logging.warning("✅ Baza zaxiradan tiklandi: %s (%s KB)", pin.document.file_name, len(data) // 1024)
        return True
    except Exception as e:
        _holat["bloklangan"] = True
        logging.error(
            "Bazani zaxiradan tiklab bo'lmadi: %s. Eski zaxira ustiga yozilmasligi uchun bu safar zaxiralash o'chirildi - "
            "botni qayta ishga tushiring.", e,
        )
        return False


async def zaxiralash(bot, chat_id: int | None, majburiy: bool = False) -> bool:
    """Baza o'zgargan bo'lsa nusxasini zaxira chatiga yuboradi va pin qiladi."""
    if chat_id is None or _holat["bloklangan"]:
        return False
    data = await asyncio.to_thread(db.snapshot_bytes)
    xesh = hashlib.sha256(data).hexdigest()
    if xesh == _holat["xesh"] and not majburiy:
        return False
    siqilgan = gzip.compress(data, 6)
    if len(siqilgan) > MAKS_HAJM:
        await asyncio.to_thread(db.eski_xabarlarni_tozalash, 30)
        data = await asyncio.to_thread(db.snapshot_bytes)
        siqilgan = gzip.compress(data, 6)
        logging.warning("Baza zaxirasi katta - 30 kundan eski suhbat xabarlari tozalandi (%s KB).", len(siqilgan) // 1024)

    msg = await bot.send_document(
        chat_id=chat_id,
        document=types.BufferedInputFile(siqilgan, filename=f"{FAYL_PREFIKSI}{hozir_matn('%Y%m%d_%H%M%S')}.db.gz"),
        caption="🗄 Baza zaxirasi (avtomatik). O'chirmang va pindan olmang — server qayta ishga tushganda shundan tiklanadi.",
        disable_notification=True,
    )
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
    except Exception as e:
        logging.error("Zaxira nusxani pin qilib bo'lmadi (bot guruhda admin bo'lishi kerak): %s", e)
    eski = _holat["msg_id"]
    _holat["xesh"], _holat["msg_id"] = xesh, msg.message_id
    if eski:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=eski)
        except Exception:
            pass  # 48 soatdan eski bo'lsa o'chmaydi - zarari yo'q
    logging.info("Baza zaxirasi saqlandi (%s KB).", len(siqilgan) // 1024)
    return True


async def zaxira_loop(bot, chat_id: int | None):
    if chat_id is None:
        return
    # Ishga tushganda joriy holatni eslab qolamiz - o'zgarmagan baza qayta yuborilmaydi
    if _holat["xesh"] is None:
        _holat["xesh"] = hashlib.sha256(await asyncio.to_thread(db.snapshot_bytes)).hexdigest()
    while True:
        await asyncio.sleep(ZAXIRA_ORALIQ)
        try:
            await zaxiralash(bot, chat_id)
        except Exception as e:
            logging.error("Baza zaxirasini saqlashda xatolik: %s", e)
