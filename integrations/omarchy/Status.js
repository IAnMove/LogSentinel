.pragma library

// Only loopback: remote portals are reached through an SSH tunnel.
function configuration(text) {
  if (text.length > 4096) return null;
  try {
    var value = JSON.parse(text);
    if (!value || typeof value.url !== "string" || typeof value.token !== "string") return null;
    var url = value.url.replace(/\/$/, "");
    var match = /^(https?):\/\/(localhost|127\.0\.0\.1|\[::1\])(?::([1-9][0-9]{0,4}))?$/.exec(url);
    if (!match || (match[3] && Number(match[3]) > 65535) || !/^[A-Za-z0-9_-]{32,128}$/.test(value.token)) return null;
    return {url: url, token: value.token};
  } catch (error) { return null; }
}

function response(text) {
  if (text.length > 65536) return null;
  try {
    var value = JSON.parse(text);
    if (!value || value.schema_version !== 1 || !Array.isArray(value.machines) || value.machines.length > 100) return null;
    if (["ok", "degraded", "starting", "stale"].indexOf(value.health) < 0 || typeof value.analysis_enabled !== "boolean") return null;
    for (var i = 0; i < 3; i++) {
      var n = value[["pending", "capacity", "open_problems"][i]];
      if (typeof n !== "number" || !isFinite(n) || n < 0 || Math.floor(n) !== n) return null;
    }
    value.machines = value.machines.filter(function (m) { return m && typeof m.name === "string"; });
    return value;
  } catch (error) { return null; }
}

function percent(value) {
  return typeof value === "number" && isFinite(value) && value >= 0 && value <= 100 ? Math.round(value) + "%" : "—";
}
