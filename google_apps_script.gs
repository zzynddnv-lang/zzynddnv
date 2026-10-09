/**
 * SAVDO BOT CRM - Google Sheets webhook (Apps Script)
 *
 * O'rnatish:
 *  1. Google Sheets jadvalini oching -> Kengaytmalar (Extensions) -> Apps Script.
 *  2. Ushbu kodni to'liq joylashtiring va saqlang.
 *  3. Deploy -> New deployment -> turi: "Web app".
 *       Execute as: Me (o'zim)
 *       Who has access: Anyone (har kim)
 *  4. Berilgan ".../exec" havolasini .env / Render sozlamalariga
 *     GOOGLE_SHEET_WEBHOOK_URL sifatida yozing.
 *
 * Har bir murojaatchi (Telegram ID) uchun bitta qator saqlanadi:
 * yangilangan dosye kelganda mavjud qator yangilanadi, dublikat qo'shilmaydi.
 *
 * Jadval botning DOIMIY XOTIRASI ham: Render qayta ishga tushib bazasi tozalansa, bot qaytib kelgan
 * mijozni (ismi, murojaatlar soni, oldingi suhbati) shu jadvaldan tiklaydi. Mijoz ma'lumotini o'qish
 * uchun maxfiy kalit kerak: bot birinchi so'rovida yuborgan kalit skript sozlamalariga saqlanadi va
 * keyin faqat shu kalit bilan o'qiladi.
 */

const VARAQ_NOMI = "CRM";

// Skript jadvalga bog'lanmagan (alohida) bo'lsa - jadval ID si shu yerga yoziladi.
// Jadval ichidan (Kengaytmalar -> Apps Script) ochilgan bo'lsa bo'sh qoldirsa ham bo'ladi.
const JADVAL_ID = "1CHBiw7jBSY6_Jqt3ly9nyp6z4BoQIivk2fdRZEi8d-4";

function jadvalniOlish_() {
  return SpreadsheetApp.getActiveSpreadsheet() || SpreadsheetApp.openById(JADVAL_ID);
}

const USTUNLAR = [
  ["sana", "Sana"],
  ["ism", "Mijoz"],
  ["telefon", "Telefon"],
  ["username", "Telegram"],
  ["telegram_id", "Telegram ID"],
  ["tashkilot", "Kompaniya"],
  ["lavozim", "Lavozim"],
  ["ehtiyoj", "Ehtiyoj"],
  ["mahsulot", "Mahsulot"],
  ["bosqich", "Bosqich"],
  ["harorat", "Harorat"],
  ["summa", "Taklif summasi (so'm)"],
  ["izoh", "Xulosa"],
  ["yangilangan_vaqt", "Oxirgi yangilanish"],
  ["sessiya_soni", "Murojaatlar soni"],
  ["mijoz_ismi", "Ism (mijoz o'zi aytgan)"],
  ["oldingi_suhbat", "Oldingi suhbat (bot xotirasi)"],
];

function varaqniOlish_() {
  const ss = jadvalniOlish_();
  let sheet = ss.getSheetByName(VARAQ_NOMI);
  if (!sheet) {
    sheet = ss.insertSheet(VARAQ_NOMI);
  }
  // Sarlavhalar har doim to'liq (yangi ustunlar qo'shilsa ham)
  const sarlavhalar = USTUNLAR.map(function (u) { return u[1]; });
  const birinchi = sheet.getRange(1, 1, 1, sarlavhalar.length);
  if (birinchi.getValues()[0].join("|") !== sarlavhalar.join("|")) {
    birinchi.setValues([sarlavhalar]).setFontWeight("bold");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function javob_(obyekt) {
  return ContentService.createTextOutput(JSON.stringify(obyekt)).setMimeType(ContentService.MimeType.JSON);
}

function qatorniTopish_(sheet, telegramId) {
  const idUstuni = USTUNLAR.findIndex(function (u) { return u[0] === "telegram_id"; }) + 1;
  const oxirgi = sheet.getLastRow();
  if (oxirgi < 2 || !telegramId) {
    return -1;
  }
  const idlar = sheet.getRange(2, idUstuni, oxirgi - 1, 1).getValues();
  for (let i = idlar.length - 1; i >= 0; i--) {
    if (String(idlar[i][0]) === String(telegramId)) {
      return i + 2;
    }
  }
  return -1;
}

function kalitTogrimi_(kalit) {
  if (!kalit) {
    return false;
  }
  const sozlamalar = PropertiesService.getScriptProperties();
  const saqlangan = sozlamalar.getProperty("BOT_KALITI");
  if (!saqlangan) {
    sozlamalar.setProperty("BOT_KALITI", String(kalit));  // birinchi so'rov - kalit eslab qolinadi
    return true;
  }
  return saqlangan === String(kalit);
}

/**
 * - Parametrsiz: holat tekshiruvi ({"ok": true}) - bot /stats da shunday tekshiradi.
 * - ?telegram_id=...&kalit=...: shu mijozning kartochkasi (bot xotirasini tiklash uchun).
 */
function doGet(e) {
  const p = (e && e.parameter) || {};
  if (!p.telegram_id) {
    const ss = jadvalniOlish_();
    return javob_({ ok: true, jadval: ss ? ss.getName() : "", varaq: VARAQ_NOMI });
  }
  if (!kalitTogrimi_(p.kalit)) {
    return javob_({ ok: false, error: "kalit noto'g'ri" });
  }
  const sheet = varaqniOlish_();
  const qator = qatorniTopish_(sheet, p.telegram_id);
  if (qator < 0) {
    return javob_({ ok: true, topildi: false });
  }
  const qiymatlar = sheet.getRange(qator, 1, 1, USTUNLAR.length).getValues()[0];
  const karta = {};
  USTUNLAR.forEach(function (u, i) { karta[u[0]] = qiymatlar[i] === "" ? "" : String(qiymatlar[i]); });
  return javob_({ ok: true, topildi: true, karta: karta });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const karta = JSON.parse(e.postData.contents);
    if (karta.kalit !== undefined && !kalitTogrimi_(karta.kalit)) {
      return javob_({ ok: false, error: "kalit noto'g'ri" });
    }
    karta.yangilangan_vaqt = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm");

    const sheet = varaqniOlish_();
    const qator = USTUNLAR.map(function (u) {
      const qiymat = karta[u[0]];
      return qiymat === undefined || qiymat === null ? "" : String(qiymat);
    });

    const topilganQator = qatorniTopish_(sheet, karta.telegram_id);
    if (topilganQator > 0) {
      // Bo'sh kelgan maydon jadvaldagi mavjud ma'lumotni o'chirmaydi; birinchi murojaat sanasi saqlanadi
      const eski = sheet.getRange(topilganQator, 1, 1, USTUNLAR.length).getValues()[0];
      for (let i = 0; i < qator.length; i++) {
        if (qator[i] === "" || i === 0) {
          qator[i] = eski[i] === "" ? qator[i] : eski[i];
        }
      }
      sheet.getRange(topilganQator, 1, 1, qator.length).setValues([qator]);
    } else {
      sheet.appendRow(qator);
    }
    return javob_({ ok: true });
  } catch (err) {
    return javob_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}
