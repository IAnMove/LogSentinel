"use strict";
// Triage controls above the problem list: which problems to show, what to do
// with the quiet ones, and the daily report that replaces reading every alert.
let problemStatus = "open";

async function triagePanel(root) {
  const [counts, daily] = await Promise.all([
    api("/api/problems/counts?machine_id=" + encodeURIComponent(scope)),
    api("/api/report/daily"),
  ]);
  if (!root.isConnected) return;
  const box = panel(bilingual("Triaje", "Triage"));
  const tabs = actions(
    ...[
      ["open", bilingual("Abiertos", "Open")],
      ["ignored", bilingual("Ignorados", "Ignored")],
      ["resolved", bilingual("Resueltos", "Resolved")],
    ].map(([status, label]) => {
      const tab = button(`${label} (${counts[status]})`, async () => {
        problemStatus = status;
        offset = 0;
        render();
      }, status === problemStatus ? "primary" : "quiet");
      tab.setAttribute("aria-pressed", String(status === problemStatus));
      return tab;
    }),
  );
  box.append(
    tabs,
    el(
      "p",
      bilingual(
        "Ignorar es para lo que conoces y no importa: el problema sigue contando sus apariciones pero no vuelve a avisar ni a aparecer entre los abiertos. Resolver es para lo arreglado: si vuelve a ocurrir, se reabre y avisa.",
        "Ignore is for what you know and does not matter: the problem keeps counting occurrences but never notifies again or shows among the open ones. Resolve is for what was fixed: if it happens again it reopens and notifies.",
      ),
    ),
  );
  const form = el("form", undefined, "form-grid");
  form.onsubmit = (e) => e.preventDefault();
  form.append(
    field(
      "auto_resolve_days",
      bilingual(
        "Resolver solos los que lleven estos días sin repetirse (0 = nunca)",
        "Resolve by themselves after this many quiet days (0 = never)",
      ),
      "number",
      counts.auto_resolve_days,
    ),
    actions(
      button(bilingual("Guardar plazo", "Save period"), async () => {
        await api("/api/settings", { auto_resolve_days: formData(form).auto_resolve_days });
        notice(bilingual("Plazo guardado", "Period saved"));
      }),
      button(bilingual("Resolver ahora los que llevan 7 días callados", "Resolve now those quiet for 7 days"), async () => {
        const result = await api("/api/problems/bulk", {
          action: "resolve",
          all_quiet_days: 7,
          machine_id: scope || "",
        });
        notice(bilingual(`${result.changed} problemas resueltos`, `${result.changed} problems resolved`));
        render();
      }),
    ),
  );
  box.append(form);

  const report = el("details");
  report.append(el("summary", bilingual("Resumen diario", "Daily report")));
  const settings = el("form", undefined, "form-grid");
  settings.onsubmit = (e) => e.preventDefault();
  settings.append(
    field("daily_report", bilingual("Enviar un resumen cada día a los destinos generales", "Send a report every day to the general destinations"), "checkbox", daily.enabled),
    field("daily_report_hour", bilingual("Hora de envío (0–23, hora del servidor)", "Sending hour (0–23, server time)"), "number", daily.hour),
    actions(
      button(bilingual("Guardar resumen diario", "Save daily report"), async () => {
        const data = formData(settings);
        await api("/api/settings", { daily_report: data.daily_report, daily_report_hour: data.daily_report_hour });
        notice(bilingual("Resumen diario guardado", "Daily report saved"));
      }),
      button(bilingual("Enviar ahora", "Send now"), async () => {
        const sent = await api("/api/report/daily/send", {});
        notice(
          sent.results.length
            ? sent.results.map((r) => r.destination + ": " + r.status).join(" · ")
            : bilingual("No hay destinos generales activos", "No general destination is enabled"),
          sent.results.some((r) => r.status !== "delivered"),
        );
      }),
    ),
  );
  report.append(
    el(
      "p",
      bilingual(
        "Un mensaje al día con lo ocurrido en cada equipo: problemas nuevos y repetidos, comprobaciones fallando, en qué se trabajó, cambios en lo instalado y notas de agentes. Se compone sin modelo. Así se vería ahora:",
        "One message a day with what happened on each machine: new and recurring problems, failing checks, what was worked on, installed changes and agent notes. Built without a model. This is how it would read now:",
      ),
    ),
    el("pre", daily.text),
    settings,
  );
  box.append(report);
  root.append(box);
}

function triageActions(problem) {
  const change = (action, done) =>
    button(action.label, async () => {
      await api("/api/problems/bulk", { action: action.name, ids: [problem.id] });
      notice(done);
      render();
    });
  if (problem.status === "open")
    return [
      change({ name: "ignore", label: bilingual("Ignorar", "Ignore") }, bilingual("Problema ignorado", "Problem ignored")),
      change({ name: "resolve", label: bilingual("Resolver", "Resolve") }, bilingual("Problema resuelto", "Problem resolved")),
    ];
  return [change({ name: "reopen", label: bilingual("Reabrir", "Reopen") }, bilingual("Problema reabierto", "Problem reopened"))];
}
