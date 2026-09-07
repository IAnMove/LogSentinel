// The exact JavaScript used by QML: validate URLs, payloads and injection boundaries.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(new URL("../integrations/omarchy/Status.js", import.meta.url), "utf8").replace(/^\.pragma library\s*/, ""), context);
const token = "s".repeat(43);
for (const url of ["http://127.0.0.1:8766", "https://localhost:443", "http://[::1]:8765/"]) assert.ok(context.configuration(JSON.stringify({url, token})));
for (const url of ["https://evil.example", "http://127.0.0.1.evil.example", "http://127.0.0.1:99999", "http://user:pass@localhost", "file:///etc/passwd", "http://localhost\noutput=/tmp/evil", "http://localhost/?token=x", "http://localhost/#x", "http://localhost:0"]) assert.equal(context.configuration(JSON.stringify({url, token})), null, url);
assert.equal(context.configuration(JSON.stringify({url:"http://localhost", token:'"\nurl=https://evil.example'})), null);
const good = {schema_version:1, health:"ok", analysis_enabled:true, pending:0, capacity:0, open_problems:2, machines:[]};
assert.ok(context.response(JSON.stringify(good)));
for (const bad of [{...good, pending:-1}, {...good, open_problems:"2"}, {...good, schema_version:2}, {...good, machines:{}}, {...good, health:"safe!"}]) assert.equal(context.response(JSON.stringify(bad)), null);
assert.equal(context.percent(null), "—");
assert.equal(context.percent(1000), "—");
assert.equal(context.percent(63.4), "63%");
console.log("Omarchy widget configuration and status validation passed");
