// logimap focus emitter — KWin JavaScript script.
//
// Installed via the org.kde.kwin.Scripting D-Bus service by
// logimap.focus.kwin_dbus.install_kwin_script().
//
// On every window activation this script calls a D-Bus method on
//   service:   org.logimap.Focus1
//   path:      /org/logimap/Focus1
//   interface: org.logimap.Focus1
//   method:    Notify(ss s s i) -> resourceClass, resourceName, caption, pid
//
// The Python daemon owns that service name; if the daemon is not running,
// the callInDBus() call is a no-op.

function emit(window) {
    if (!window) return;
    var rc = (window.resourceClass || "").toString();
    var rn = (window.resourceName || "").toString();
    var cap = (window.caption || "").toString();
    var pid = window.pid || 0;
    print("logimap-focus: emit " + rc + " | " + cap);
    try {
        callDBus(
            "org.logimap.Focus1",
            "/org/logimap/Focus1",
            "org.logimap.Focus1",
            "Notify",
            rc, rn, cap, pid
        );
    } catch (e) {
        print("logimap-focus: callDBus failed: " + e);
    }
}

print("logimap-focus: script loaded");

workspace.windowActivated.connect(function(window) {
    emit(window);
});

// Emit once on load so the daemon paints the right profile on startup.
if (workspace.activeWindow) {
    emit(workspace.activeWindow);
}
