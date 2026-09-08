// The exact JavaScript used by QML: validate URLs, payloads and injection boundaries.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
const context = vm.createContext({});
vm.runInContext(
  fs
    .readFileSync(
      new URL("../integrations/omarchy/Status.js", import.meta.url),
      "utf8",
    )
    .replace(/^\.pragma library\s*/, ""),
  context,
);
const token = "s".repeat(43);
for (const url of [
  "http://127.0.0.1:8766",
  "https://localhost:443",
  "http://[::1]:8765/",
])
  assert.ok(context.configuration(JSON.stringify({ url, token })));
for (const url of [
  "https://evil.example",
  "http://127.0.0.1.evil.example",
  "http://127.0.0.1:99999",
  "http://user:pass@localhost",
  "file:///etc/passwd",
  "http://localhost\noutput=/tmp/evil",
  "http://localhost/?token=x",
  "http://localhost/#x",
  "http://localhost:0",
])
  assert.equal(
    context.configuration(JSON.stringify({ url, token })),
    null,
    url,
  );
assert.equal(
  context.configuration(
    JSON.stringify({
      url: "http://localhost",
      token: '"\nurl=https://evil.example',
    }),
  ),
  null,
);
const good = {
  schema_version: 1,
  health: "ok",
  analysis_enabled: true,
  pending: 0,
  capacity: 0,
  open_problems: 2,
  machines: [],
};
assert.ok(context.response(JSON.stringify(good)));
for (const bad of [
  { ...good, pending: -1 },
  { ...good, open_problems: "2" },
  { ...good, schema_version: 2 },
  { ...good, machines: {} },
  { ...good, health: "safe!" },
])
  assert.equal(context.response(JSON.stringify(bad)), null);
assert.equal(context.percent(null), "—");
assert.equal(context.percent(1000), "—");
assert.equal(context.percent(63.4), "63%");

// Exercise the actual widget callbacks: pairing after installation must recover,
// and a missing configuration must not start an immediate reload loop.
const widget = fs.readFileSync(
  new URL("../integrations/omarchy/SentinelWidget.qml", import.meta.url),
  "utf8",
);
let reloads = 0;
const scheduled = [];
const widgetContext = vm.createContext({
  Status: context,
  connection: null,
  snapshot: null,
  connectionState: "unpaired",
  responseText: "old response",
  request: { running: false, stdinEnabled: false },
  configFile: {
    reload: () => {
      reloads++;
    },
  },
  Qt: { callLater: (callback) => scheduled.push(callback) },
});
for (const name of ["readConfiguration", "refresh"]) {
  const callback = widget.match(
    new RegExp(`    function ${name}\\([^)]*\\) \\{[\\s\\S]*?^    \\}`, "m"),
  );
  assert.ok(callback, `Missing widget callback: ${name}`);
  vm.runInContext(callback[0], widgetContext);
}
widgetContext.readConfiguration("");
assert.equal(scheduled.length, 0);
widgetContext.refresh();
assert.equal(reloads, 1);
assert.equal(widgetContext.request.running, false);
widgetContext.readConfiguration(
  JSON.stringify({ url: "http://127.0.0.1:8766", token }),
);
assert.equal(scheduled.length, 1);
scheduled.shift()();
assert.equal(widgetContext.request.running, true);
assert.equal(widgetContext.responseText, "");
widgetContext.refresh();
assert.equal(reloads, 1);
console.log("Omarchy widget configuration and status validation passed");
