/**
 * Privacy-minimal completion bridge for the HRC Participant tracker.
 *
 * Create this under the Monash account, set the Script Property
 * HRC_FORM_COMPLETION_TOKEN, and deploy it as a web app executable by the owner
 * and accessible to anyone with the URL. It opens only the fixed Participant
 * tracker below and returns whether the requested anonymous participant/stage
 * row exists; it never returns questionnaire answers.
 */

const RESPONSE_TABS = Object.freeze({
  intake: { sheet: "Intake responses", participantColumn: 2 },
  block: { sheet: "Block responses", participantColumn: 2, blockColumn: 3 },
  end: { sheet: "End responses", participantColumn: 2 },
});
const RESPONSE_SPREADSHEET_ID = "1lMwfR9C0gdXSHmUB7cWqinKMdPDXPpKJdXPhavGqTco";

function doGet(event) {
  const suppliedToken = String(event.parameter.token || "");
  const expectedToken = PropertiesService.getScriptProperties()
    .getProperty("HRC_FORM_COMPLETION_TOKEN");
  if (!expectedToken || suppliedToken !== expectedToken) {
    return jsonResponse({ ok: false, error: "unauthorized" });
  }

  const participantId = String(event.parameter.participant_id || "").trim();
  const stage = String(event.parameter.stage || "").trim();
  const block = String(event.parameter.block || "").trim().toUpperCase();
  const spec = RESPONSE_TABS[stage];
  if (!participantId || !spec || (stage === "block" && !/^[ABC]$/.test(block))) {
    return jsonResponse({ ok: false, error: "invalid request" });
  }

  const sheet = SpreadsheetApp.openById(RESPONSE_SPREADSHEET_ID)
    .getSheetByName(spec.sheet);
  if (!sheet) return jsonResponse({ ok: false, error: "response tab missing" });
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return jsonResponse({ ok: true, submitted: false });

  const width = spec.blockColumn ? 2 : 1;
  const rows = sheet.getRange(2, spec.participantColumn, lastRow - 1, width)
    .getDisplayValues();
  const submitted = rows.some(row => {
    if (String(row[0]).trim() !== participantId) return false;
    return stage !== "block" || String(row[1]).trim().toUpperCase() === block;
  });
  return jsonResponse({ ok: true, submitted });
}

function jsonResponse(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
