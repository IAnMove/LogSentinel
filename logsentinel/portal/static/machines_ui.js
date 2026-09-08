"use strict";

function machineMonitoringState(machine) {
  if (machine.deletion_pending)
    return bilingual("Borrado pendiente", "Deletion pending");
  return machine.monitoring_paused
    ? bilingual("Monitorización pausada", "Monitoring paused")
    : bilingual("Monitorización permitida", "Monitoring allowed");
}
function machineActions(machine) {
  if (machine.deletion_pending)
    return [
      button(bilingual("Ver borrado", "View deletion"), () =>
        showMachineDeletion(machine),
      ),
    ];
  return [
    button(
      machine.monitoring_paused
        ? bilingual("Reanudar esta máquina", "Resume this machine")
        : bilingual("Pausar esta máquina", "Pause this machine"),
      async () => {
        await api("/api/machines/" + machine.id + "/monitoring", {
          paused: !machine.monitoring_paused,
        });
        await refresh();
        notice(
          machine.monitoring_paused
            ? bilingual(
                "Máquina reanudada con sus fuentes y métricas anteriores. El análisis sigue el control global.",
                "Machine resumed with its previous source and metric settings. Analysis follows the global control.",
              )
            : bilingual(
                "Solo esta máquina está pausada: captura, análisis, métricas y avisos. Una llamada ya enviada puede terminar. El historial se conserva.",
                "Only this machine is paused: collection, analysis, metrics and alerts. An already submitted call may finish. History is preserved.",
              ),
        );
      },
    ),
    button(bilingual("Optimizar", "Optimize"), () => openOptimizer(machine.id)),
    button(
      bilingual("Borrar máquina", "Delete machine"),
      () => confirmMachineDeletion(machine),
      "danger",
    ),
  ];
}
async function confirmMachineDeletion(machine) {
  const preview = await api("/api/machines/" + machine.id + "/delete-preview"),
    box = el("div");
  box.append(
    el(
      "p",
      bilingual(
        "Se borrarán de forma permanente los datos retenidos de ",
        "Permanently delete retained data for ",
      ) +
        preview.name +
        ".",
    ),
  );
  const labels = {
    sources: bilingual("Fuentes", "Sources"),
    events: bilingual("Registros", "Log events"),
    problems: bilingual("Problemas", "Findings"),
    jobs: bilingual("Análisis", "Analyses"),
    usage: bilingual("Registros de consumo", "Usage records"),
    telemetry_samples: bilingual("Muestras de métricas", "Metric samples"),
    telemetry_rollups: bilingual("Resúmenes de métricas", "Metric summaries"),
    destinations: bilingual(
      "Notificadores exclusivos",
      "Scoped notification channels",
    ),
    conversations: bilingual("Conversaciones", "Conversations"),
  };
  box.append(
    table(
      [
        bilingual("Datos asociados", "Associated data"),
        bilingual("Cantidad actual", "Current count"),
      ],
      Object.entries(preview.counts).map(([k, v]) => [
        labels[k] || k,
        String(v),
      ]),
    ),
    el(
      "p",
      bilingual(
        "También se eliminarán filtros, investigaciones y claves de los emisores asociados. Se conservarán los archivos originales, el journal, las copias de seguridad existentes y los canales globales. Los avisos ya enviados o exportados no se retiran. La recepción se detendrá al confirmar; los emisores remotos deberán desconectarse o reconfigurarse.",
        "Associated filters, investigations and sender credentials will also be deleted. Original files, the system journal, existing backups and global channels are preserved. Notifications already sent or exported are not withdrawn. Reception stops on confirmation; remote senders must be disconnected or reconfigured.",
      ),
    ),
    el(
      "p",
      bilingual(
        "Si hay operaciones en curso, el borrado esperará a que terminen. El recuento puede cambiar hasta que se detenga la captura.",
        "If operations are in progress, deletion waits for them to finish. Counts may change until collection stops.",
      ),
      "subtle",
    ),
  );
  box.append(
    actions(
      button(bilingual("Cancelar", "Cancel"), () => $("#modal").close()),
      button(
        bilingual("Sí, borrar máquina y datos", "Yes, delete machine and data"),
        async () => {
          await api("/api/machines/" + machine.id + "/delete", {
            confirm_name: preview.name,
          });
          $("#modal").close();
          await showMachineDeletion(machine);
        },
        "danger",
      ),
    ),
  );
  modal(
    bilingual("Confirmar borrado · ", "Confirm deletion · ") + preview.name,
    box,
  );
}
async function showMachineDeletion(machine) {
  const box = el("div"),
    message = el("p"),
    controls = el("div");
  box.append(message, controls);
  modal(
    bilingual("Borrado de máquina · ", "Machine deletion · ") + machine.name,
    box,
  );
  async function update() {
    try {
      const job = await api("/api/machines/" + machine.id + "/deletion");
      if (!box.isConnected) return;
      const labels = {
        queued: bilingual(
          "Borrado en cola. Se completará aunque cierres esta ventana.",
          "Deletion queued. It will complete even if you close this window.",
        ),
        waiting: bilingual(
          "Máquina detenida. Esperando a que finalicen las operaciones en curso con el modelo o notificaciones.",
          "Machine stopped. Waiting for current model or notification operations to finish.",
        ),
        deleting: bilingual(
          "Eliminando datos asociados y recuperando espacio…",
          "Deleting associated data and reclaiming space…",
        ),
        completed: bilingual(
          "Máquina y datos asociados eliminados.",
          "Machine and associated data deleted.",
        ),
        failed: bilingual(
          "El borrado ha fallado. La máquina sigue detenida.",
          "Deletion failed. The machine remains stopped.",
        ),
      };
      message.textContent = labels[job.status] || job.status;
      controls.replaceChildren();
      if (job.status === "completed") {
        if (job.space_reclaimed === false)
          controls.append(
            el(
              "p",
              bilingual(
                "Los datos están borrados, pero la compactación del archivo SQLite quedó pendiente.",
                "Data has been deleted, but SQLite file compaction remains pending.",
              ),
            ),
          );
        if (scope === machine.id) scope = "";
        await refresh();
        return;
      }
      if (job.status === "failed") {
        controls.append(
          el("p", job.error, "error"),
          button(
            bilingual("Reintentar borrado", "Retry deletion"),
            async () => {
              await api("/api/machines/" + machine.id + "/delete", {
                confirm_name: machine.name,
              });
              await update();
            },
          ),
        );
        return;
      }
      setTimeout(() => {
        if (box.isConnected && $("#modal").open) update();
      }, 1500);
    } catch (e) {
      message.textContent = e.message;
    }
  }
  await update();
}
