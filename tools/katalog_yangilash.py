"""
UMATIC KATALOGINI YANGILASH: umatic.uz saytidagi barcha mahsulotlarni yig'ib, bilimlar/katalog.json ga yozadi.

Ishga tushirish (loyiha papkasidan):
    python tools/katalog_yangilash.py

Saytga yangi mahsulot qo'shilsa yoki o'zgarsa - shu skriptni ishga tushirib, natijani GitHub'ga yuklang.
Narx va "В наличии" (omborda bor) belgisi OLINMAYDI: narx va mavjudlikni menejer/ombor tasdiqlaydi.
"""

import html
import json
import os
import re
import sys
import time
import urllib.request

SAYT = "https://umatic.uz"
CHIQISH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bilimlar", "katalog.json")

# Sayt bo'limi -> katalog bo'limi kodi
BOLIMLAR = {
    "Общепромышленные": "AIR",
    "Крановые": "MTN",
    "Взрывозащищённые": "VA",
    "Синхронные": "SD",
    "Скважинные насосные агрегаты": "ECV",
    "Насосные агрегаты двухстороннего входа": "D",
    "Консольные насосные агрегаты": "K",
    "Моноблочные насосные агрегаты": "KM",
    "Эмалированный провод": "PROVOD",
    "Секции статорных обмоток для эл.двигателей и генераторов постоянных и переменных токов": "STATOR",
    "Лента киперная": "LENTA",
    "Перчатки": "PERCHATKA",
}


def olish(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="ignore")


def qatorlar(s: str) -> list[str]:
    s = re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", s)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", s))
    return [re.sub(r"\s+", " ", x).strip() for x in t.splitlines() if x.strip()]


def model_nomi(nomi: str) -> str:
    """'Электродвигатель АИР132М4У1 11 кВт 1500 об/мин' -> 'АИР132М4У1'."""
    n = re.sub(
        r"^(Синхронный\s+)?(электродвигатель|электронасосный агрегат|насос консольный|моноблочный насос|"
        r"насос двухстороннего входа|медный эмалированный провод)\s*(трехфазный\s*)?",
        "", nomi.strip(" ."), flags=re.IGNORECASE,
    )
    n = re.sub(r"\s+\d[\d\s,.]*\s*кВт.*$", "", n)
    n = re.sub(r"\s+лапы$", "", n)
    return n.strip(" .") or nomi.strip(" .")


def xususiyatlar(q: list[str], tavsif: str) -> dict:
    xus = {}
    for k in range(len(q) - 1):
        if q[k + 1].startswith(": ") and len(q[k]) < 45:
            xus[q[k]] = q[k + 1][2:].strip()
    # Jadvalsiz sahifalar: tavsifdagi "Kalit, birlik: qiymat" juftlari
    for k, v in re.findall(r"([А-ЯЁ][а-яё()., ²³/˜-]{2,60}?(?:,\s*[^:]{1,20})?)\s*:\s*(\d[\d.,;/-]*(?:\s\d[\d.,;/-]*)*(?:\s?[a-zа-я°%³²/][a-zA-Zа-яА-Я°%³²/]*)?)", tavsif):
        k = k.strip(" .,")
        if k and k not in xus and not re.match(r"(Технические|Характеристики)", k):
            xus[k] = v.strip(" .,")
    return xus


def main():
    sitemap = olish(SAYT + "/sitemap.xml")
    urllar = [u for u in re.findall(r"<loc>([^<]+)</loc>", sitemap) if "/magazin/product/" in u]
    print("Mahsulot sahifalari:", len(urllar))
    katalog = []
    for i, url in enumerate(urllar, 1):
        try:
            s = olish(url)
        except Exception as e:
            print("  XATO:", url, e)
            continue
        q = qatorlar(s)
        nomi = q[0].strip(" .")
        ichki = [x for x in q[20:60] if x not in ("/", "Главная")]
        kichik = next((b for b in BOLIMLAR if b in ichki or any(x.startswith("Синхронный") for x in ichki[:3]) and b == "Синхронные"), "")
        if "Синхронный" in nomi:
            kichik = "Синхронные"
        tavsif = []
        if "Описание" in q:
            j = len(q) - 1 - q[::-1].index("Описание")
            for x in q[j + 1:]:
                if x == "Отзывы":
                    break
                tavsif.append(x)
        tavsif = " ".join(tavsif)
        rasm = re.search(r'src="(/thumb/2/[^"]+/750r750/d/[^"]+)"', s) or re.search(r'href="(/d/[^"]+\.(?:webp|jpg|jpeg|png))"', s)
        katalog.append({
            "model": model_nomi(nomi),
            "nomi": nomi,
            "bolim": BOLIMLAR.get(kichik, "BOSHQA"),
            "url": url,
            "rasm": (SAYT + rasm.group(1)) if rasm else "",
            "xus": xususiyatlar(q, tavsif),
            "tavsif": tavsif[:700],
        })
        print(f"  {i}/{len(urllar)} {katalog[-1]['bolim']:9} {katalog[-1]['model']}")
        time.sleep(0.25)

    if len(katalog) < 20:
        sys.exit("Juda kam mahsulot topildi - sayt tuzilishi o'zgargan bo'lishi mumkin. Fayl yozilmadi.")
    with open(CHIQISH, "w", encoding="utf-8") as f:
        json.dump(katalog, f, ensure_ascii=False, indent=1)
    print(f"Yozildi: {CHIQISH} ({len(katalog)} ta mahsulot)")


if __name__ == "__main__":
    main()
