// Consistency of the interface dictionary. Prints a JSON report; empty lists mean clean.
//   node scripts/check_i18n.js
const fs = require("fs"), path = require("path"), vm = require("vm");
const dir = path.join(__dirname, "..", "logsentinel", "portal", "static");
const src = fs.readFileSync(path.join(dir, "i18n.js"), "utf8");
const cut = src.indexOf("const reverseTranslations");
const head = src.slice(0, cut);
const sandbox = {};
vm.runInNewContext(head.replace("const translations", "var translations") + ";this.dict=translations", sandbox);
const dict = sandbox.dict;

// A key written twice in the object literals silently keeps only the last value.
const seen = {};
const keyRe = /^\s{2}(?:"((?:[^"\\]|\\.)*)"|([A-Za-zÁÉÍÓÚÑáéíóúñ_]+)):/gm;
for (let m; (m = keyRe.exec(head)); ) {
  const key = m[1] !== undefined ? JSON.parse('"' + m[1] + '"') : m[2];
  seen[key] = (seen[key] || 0) + 1;
}
const duplicates = Object.entries(seen).filter(([, n]) => n > 1).map(([k]) => k);

// Every literal passed to t() must be a key (or an English value the reverse map knows).
const values = new Set(Object.values(dict));
const missing = {};
const call = /\bt\(\s*(?:"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`([^`$]*)`)/g;
for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".js") && f !== "i18n.js")) {
  const text = fs.readFileSync(path.join(dir, file), "utf8");
  for (let m; (m = call.exec(text)); ) {
    const raw = m[1] ?? m[2] ?? m[3];
    let key = raw;
    try { key = m[1] !== undefined ? JSON.parse('"' + raw + '"') : raw; } catch {}
    if (!(key in dict) && !values.has(key)) (missing[file] = missing[file] || []).push(key);
  }
}

const indexHtml = fs.readFileSync(path.join(dir, "index.html"), "utf8");
const staticMissing = [...indexHtml.matchAll(/data-i18n="([^"]*)"/g)].map((m) => m[1]).filter((k) => !(k in dict));

// {name} placeholders must survive translation in both directions.
const holes = (s) => (s.match(/\{[a-zA-Z_]+\}/g) || []).sort().join(",");
const placeholders = Object.entries(dict).filter(([es, en]) => holes(es) !== holes(en)).map(([es]) => es);

console.log(JSON.stringify({ entries: Object.keys(dict).length, duplicates, missing, staticMissing, placeholders }));
