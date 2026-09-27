/**
 * ZUXRIDDIN YORDAMCHISI - Google Sheets webhook (Apps Script)
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
 */

const VARAQ_NOMI = "Murojaatlar";

const USTUNLAR = [
  ["sana", "Sana"],
  ["ism", "Murojaatchi Ismi"],
  ["telefon", "Telefon"],
  ["username", "Telegram"],
  ["telegram_id", "Telegram ID"],
  ["tashkilot", "Tashkilot / Kasbi"],
  ["mavzu", "Mavzu"],
  ["muhimlik", "Muhimlik"],
  ["izoh", "Xulosa / Tafsilot"],
  ["holat", "Holati"],
  ["yangilangan_vaqt", "Oxirgi yangilanish"],
];

function varaqniOlish_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(VARAQ_NOMI);
  if (!sheet) {
    sheet = ss.insertSheet(VARAQ_NOMI);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(USTUNLAR.map(function (u) { return u[1]; }));
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, 1, USTUNLAR.length).setFontWeight("bold");
  }
  return sheet;
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const karta = JSON.parse(e.postData.contents);
    karta.yangilangan_vaqt = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm");

    const sheet = varaqniOlish_();
    const qator = USTUNLAR.map(function (u) {
      const qiymat = karta[u[0]];
      return qiymat === undefined || qiymat === null ? "" : String(qiymat);
    });

    // Telegram ID bo'yicha mavjud qatorni qidirish
    const idUstuni = USTUNLAR.findIndex(function (u) { return u[0] === "telegram_id"; }) + 1;
    let topilganQator = -1;
    const oxirgi = sheet.getLastRow();
    if (oxirgi > 1 && karta.telegram_id) {
      const idlar = sheet.getRange(2, idUstuni, oxirgi - 1, 1).getValues();
      for (let i = idlar.length - 1; i >= 0; i--) {
        if (String(idlar[i][0]) === String(karta.telegram_id)) {
          topilganQator = i + 2;
          break;
        }
      }
    }

    if (topilganQator > 0) {
      // Birinchi murojaat sanasini saqlab qolamiz
      qator[0] = sheet.getRange(topilganQator, 1).getValue() || qator[0];
      sheet.getRange(topilganQator, 1, 1, qator.length).setValues([qator]);
    } else {
      sheet.appendRow(qator);
    }

    return ContentService.createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
