import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "Status.js" as Status

Panel {
    id: root

    property var anchorItem: null
    property var hostWidget: null
    property int selectedAction: 0
    readonly property var snapshot: hostWidget ? hostWidget.snapshot : null
    readonly property bool spanish: hostWidget && hostWidget.spanish

    function switchPanel(direction) {
        return bar && typeof bar.switchPanelFrom === "function" ? bar.switchPanelFrom(hostWidget || root, direction) : false;
    }
    function tr(es, en) {
        return spanish ? es : en;
    }

    manageIpc: false
    moduleName: "io.github.ianmove.logsentinel"

    KeyboardPanel {
        id: surface

        anchorItem: root.anchorItem
        bar: root.bar
        contentHeight: surface.fittedContentHeight(content.implicitHeight)
        contentWidth: surface.fittedContentWidth(Style.space(340))
        focusTarget: keys
        open: root.opened
        owner: root.hostWidget || root

        PanelKeyCatcher {
            id: keys

            anchors.fill: parent

            onActivateRequested: {
                if (!root.hostWidget)
                    return;
                if (root.selectedAction === 0)
                    root.hostWidget.openPortal();
                else
                    root.hostWidget.refresh();
            }
            onCloseRequested: root.close()
            onMoveRequested: function (dx, dy) {
                root.selectedAction = root.selectedAction === 0 ? 1 : 0;
            }
            onTabRequested: function (direction) {
                root.switchPanel(direction);
            }
            onTextKey: function (text) {
                if (text.toLowerCase() === "r" && root.hostWidget)
                    root.hostWidget.refresh();
            }

            Column {
                id: content

                spacing: Style.space(12)
                width: parent.width

                Text {
                    color: root.barForeground
                    font.bold: true
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.subtitle
                    text: "◈ LogSentinel"
                }
                Text {
                    color: root.barForeground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.body
                    text: !root.snapshot ? root.tr("Sin conexión. Vincula el widget en Escritorio dentro del portal y comprueba el servicio o túnel SSH.", "Not connected. Pair the widget in the portal's Desktop page and check the service or SSH tunnel.") : root.snapshot.open_problems + root.tr(" problemas abiertos · ", " open findings · ") + root.snapshot.pending + root.tr(" pendientes\n", " pending\n") + (root.snapshot.analysis_enabled ? root.tr("Análisis automático activo", "Automatic analysis enabled") : root.tr("Análisis automático pausado", "Automatic analysis paused")) + " · " + root.snapshot.health + "\n" + root.snapshot.capacity + root.tr(" eventos sin revisar por capacidad", " events unreviewed due to capacity")
                    textFormat: Text.PlainText
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: root.snapshot ? root.snapshot.machines.slice(0, 4) : []

                    delegate: Text {
                        required property var modelData

                        color: root.barForeground
                        font.family: root.bar ? root.bar.fontFamily : Style.font.family
                        font.pixelSize: Style.font.body
                        text: modelData.name.slice(0, 80) + " · " + modelData.state + "\nCPU " + Status.percent(modelData.cpu_pct) + " · RAM " + Status.percent(modelData.ram_pct) + root.tr(" · Disco ", " · Disk ") + Status.percent(modelData.disk_pct)
                        textFormat: Text.PlainText
                        width: content.width
                        wrapMode: Text.WordWrap
                    }
                }
                Text {
                    color: root.barForeground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.body
                    text: root.tr("Actualizado: ", "Updated: ") + (root.hostWidget ? new Date(root.hostWidget.checkedAt).toLocaleTimeString() : "")
                    visible: !!root.hostWidget && root.hostWidget.checkedAt > 0
                }
                WidgetButton {
                    bar: root.bar
                    text: (root.selectedAction === 0 ? "› " : "  ") + root.tr("Abrir portal ↗", "Open portal ↗")

                    onPressed: function (code) {
                        if (code === Qt.LeftButton && root.hostWidget)
                            root.hostWidget.openPortal();
                    }
                }
                WidgetButton {
                    bar: root.bar
                    text: (root.selectedAction === 1 ? "› " : "  ") + root.tr("Actualizar", "Refresh")

                    onPressed: function (code) {
                        if (code === Qt.LeftButton && root.hostWidget)
                            root.hostWidget.refresh();
                    }
                }
            }
        }
    }
}
