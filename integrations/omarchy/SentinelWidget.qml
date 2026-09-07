import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import "Status.js" as Status

BarWidget {
    id: root

    property double checkedAt: 0
    readonly property string configPath: String(setting("configPath", "") || (Quickshell.env("HOME") + "/.config/logsentinel/widget.json"))
    property var connection: null
    property string connectionState: "unpaired"
    readonly property bool opened: popup.item ? popup.item.opened === true : false
    readonly property bool popoutSwitchClosing: popup.item ? popup.item.popoutSwitchClosing === true : false
    property string responseText: ""
    property var snapshot: null
    readonly property bool spanish: String(setting("language", "en")) === "es"

    function close() {
        if (popup.item)
            popup.item.close();
    }
    function closeForPopoutSwitch() {
        if (popup.item)
            popup.item.closeForPopoutSwitch();
    }
    function injectPanel() {
        if (!popup.item)
            return;
        popup.item.bar = root.bar;
        popup.item.anchorItem = button;
        popup.item.hostWidget = root;
    }
    function open() {
        if (popup.item)
            popup.item.open();
    }
    function openPortal() {
        Qt.openUrlExternally(connection ? connection.url : "http://127.0.0.1:8765");
    }
    function readConfiguration(text) {
        request.running = false;
        connection = Status.configuration(text);
        snapshot = null;
        connectionState = connection ? "connecting" : "unpaired";
        Qt.callLater(refresh);
    }
    function refresh() {
        if (!connection || request.running)
            return;
        responseText = "";
        request.stdinEnabled = true;
        request.running = true;
    }
    function toggle() {
        if (popup.item)
            popup.item.toggle();
    }

    implicitHeight: button.implicitHeight
    implicitWidth: button.implicitWidth
    moduleName: "io.github.ianmove.logsentinel"

    onBarChanged: injectPanel()

    FileView {
        id: configFile

        path: root.configPath
        printErrors: false
        watchChanges: true

        onFileChanged: reload()
        onLoadFailed: root.readConfiguration("")
        onLoaded: root.readConfiguration(text())
    }
    Timer {
        interval: 1500
        running: true

        onTriggered: configFile.reload()
    }
    Timer {
        interval: 30000
        repeat: true
        running: true

        onTriggered: root.refresh()
    }
    Process {
        id: request

        // curl does not follow redirects. -q ignores user curlrc; credentials use stdin.
        command: ["curl", "-q", "--silent", "--fail", "--max-time", "10", "--max-filesize", "65536", "--noproxy", "*", "--proto", "=http,https", "--config", "-"]
        stdinEnabled: true

        stdout: StdioCollector {
            onStreamFinished: root.responseText = text
        }

        onExited: function (exitCode) {
            var result = exitCode === 0 ? Status.response(root.responseText) : null;
            root.snapshot = result;
            root.connectionState = result ? "connected" : (root.connection ? "unavailable" : "unpaired");
            root.checkedAt = Date.now();
        }
        onStarted: {
            if (!root.connection) {
                running = false;
                return;
            }
            write('url = "' + root.connection.url + '/widget/status"\nheader = "Authorization: Bearer ' + root.connection.token + '"\n');
            stdinEnabled = false;
        }
    }
    Loader {
        id: popup

        active: true
        source: Qt.resolvedUrl("SentinelPanel.qml")
        visible: false

        onLoaded: {
            root.injectPanel();
            Qt.callLater(root.injectPanel);
        }
    }
    WidgetButton {
        id: button

        anchors.fill: parent
        bar: root.bar
        text: root.connectionState !== "connected" ? "LS ?" : "LS " + (root.snapshot.health === "ok" && root.snapshot.analysis_enabled ? "" : "! ") + root.snapshot.open_problems
        tooltipText: root.spanish ? "LogSentinel · estado y portal" : "LogSentinel · status and portal"

        onPressed: function (buttonCode) {
            if (buttonCode === Qt.LeftButton)
                root.toggle();
        }
    }
}
