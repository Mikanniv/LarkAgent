const fs = require("node:fs");
const path = require("node:path");

function normalizePreferences(input = {}) {
  const value = input && typeof input === "object" ? input : {};
  return {
    form: value.form === "chibi" ? "chibi" : "bird",
    gazeEnabled: value.gazeEnabled !== false,
    position: value.position && Number.isFinite(value.position.x) && Number.isFinite(value.position.y)
      ? { x: Math.round(value.position.x), y: Math.round(value.position.y) } : null,
  };
}
function clampPosition(position, area, size) {
  const x = position?.x ?? area.x + area.width - size.width - 35;
  const y = position?.y ?? area.y + area.height - size.height - 15;
  return {
    x: Math.round(Math.max(area.x, Math.min(x, area.x + Math.max(0, area.width - size.width)))),
    y: Math.round(Math.max(area.y, Math.min(y, area.y + Math.max(0, area.height - size.height)))),
  };
}
function readPreferences(file) {
  try { return normalizePreferences(JSON.parse(fs.readFileSync(file, "utf8"))); }
  catch { return normalizePreferences(); }
}
function writePreferences(file, state) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(normalizePreferences(state), null, 2), { mode: 0o600 });
  fs.renameSync(temporary, file);
}
module.exports = { normalizePreferences, clampPosition, readPreferences, writePreferences };
