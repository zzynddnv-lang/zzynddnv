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
];

function varaqniOlish_() {
  const ss = jadvalniOlish_();
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

/**
 * Holat tekshiruvi: havolani brauzerda ochsangiz yoki bot /stats da tekshirsa -
 * {"ok": true, ...} qaytadi. Jadvalga hech narsa yozilmaydi.
 */
function doGet() {
  const ss = jadvalniOlish_();
  return ContentService.createTextOutput(JSON.stringify({
    ok: true,
    jadval: ss ? ss.getName() : "",
    varaq: VARAQ_NOMI,
  })).setMimeType(ContentService.MimeType.JSON);
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
