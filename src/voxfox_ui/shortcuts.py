#!/usr/bin/env python3
# Copyright (C) 2025 - Daniël Vos
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""voxfox_ui.shortcuts — Desktop global keyboard shortcut installers (Cinnamon/GNOME/KDE/XFCE/LXQt).

Split out of voxfox_gtk.py in VoxFox 4.0.
"""

import os
import time
import subprocess

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio, Gdk  # noqa: E402

import voxfox_core as vf  # noqa: E402

log = vf.log


_SHORTCUT_ACTIONS = [
    ("read",    "VoxFox: read",         "voxfox --read",           "<Super>z"),
    ("stop",    "VoxFox: stop",         "voxfox --stop",           "<Super>x"),
    ("voice",   "VoxFox: switch voice", "voxfox --toggle-slot",    "<Super>c"),
    ("whisper", "VoxFox: dictation",    "voxfox --whisper-toggle", "<Super>w"),
    ("ocr",     "VoxFox: OCR select",   "voxfox --ocr-select",     "<Super>a"),
    ("ocr_translate", "VoxFox: OCR select & translate",
     "voxfox --ocr-select-translate", ""),
    ("page",    "VoxFox: read web page", "voxfox --read-page",     "<Super>v"),
    ("live",    "VoxFox: live transcription", "voxfox --live-toggle", ""),
    ("translate", "VoxFox: translate & read", "voxfox --translate", ""),
]

# Short, translatable names for the actions, shown in the settings
# Shortcuts tab. Keyed by the action id from _SHORTCUT_ACTIONS.
_SHORTCUT_LABELS = {
    "read":    "Read",
    "stop":    "Stop",
    "voice":   "Switch language",
    "whisper": "Dictate",
    "ocr":     "OCR select",
    "ocr_translate": "OCR select & translate",
    "page":    "Read web page",
    "live":    "Live transcription",
    "translate": "Translate & read",
}


def _binding_for(state, key, default):
    """The effective binding for an action: the user's chosen key from
    state["shortcut_bindings"], or the built-in default when unset."""
    chosen = (state.get("shortcut_bindings") or {}).get(key) if state else None
    return chosen or default


def _binding_display(binding):
    """Human-readable label for an accelerator string ('<Super>z' -> 'Super+Z').
    Falls back to the raw string if it can't be parsed."""
    if not binding:
        return ""
    try:
        ok, keyval, mods = Gtk.accelerator_parse(binding)
        if ok and keyval:
            return Gtk.accelerator_get_label(keyval, mods)
    except Exception:
        pass
    return binding


def _binding_to_lxqt(binding):
    """Convert an accelerator string to LXQt's section-name format:
    '<Super>z' -> 'Meta%2BZ', '<Control><Alt>x' -> 'Control%2BAlt%2BX'.
    Returns None if the binding can't be parsed."""
    try:
        ok, keyval, mods = Gtk.accelerator_parse(binding)
    except Exception:
        ok = False
    if not ok or not keyval:
        return None
    parts = []
    if mods & Gdk.ModifierType.SUPER_MASK:
        parts.append("Meta")
    if mods & Gdk.ModifierType.CONTROL_MASK:
        parts.append("Control")
    if mods & Gdk.ModifierType.ALT_MASK:
        parts.append("Alt")
    if mods & Gdk.ModifierType.SHIFT_MASK:
        parts.append("Shift")
    name = Gdk.keyval_name(Gdk.keyval_to_upper(keyval)) or ""
    if not name:
        return None
    parts.append(name)
    return "%2B".join(parts)

# Non-numeric entry names used by VoxFox <= 2.0.7. These broke Cinnamon's
# "Add custom shortcut" button: its settings panel computes the next free
# slot by walking a numeric customN sequence, and chokes on names like
# "voxfox-read". On install we migrate any of these away to numeric slots.
_LEGACY_SHORTCUT_NAMES = [
    "voxfox-read", "voxfox-stop", "voxfox-voice", "voxfox-whisper", "voxfox-ocr",
]


def _next_custom_slots(taken, count):
    """Return `count` fresh 'customN' slot names not already in `taken`,
    lowest indices first, so the desktop's custom-list stays a compact
    numeric sequence (which is what keeps the "Add shortcut" button working)."""
    taken = set(taken)
    out, n = [], 0
    while len(out) < count:
        name = f"custom{n}"
        if name not in taken:
            out.append(name)
            taken.add(name)
        n += 1
    return out


def _slot_sort_key(name):
    """Sort customN names numerically; anything else sorts last, by string."""
    if name.startswith("custom") and name[6:].isdigit():
        return (0, int(name[6:]))
    return (1, name)


def _install_cinnamon_shortcuts(src, state):
    """Cinnamon: custom-list holds slot NAMES; each is a relocatable schema
    under .../custom-keybindings/<name>/ with binding as a LIST. We allocate
    numeric customN slots (never literal names), migrate any legacy
    voxfox-* entries away, and remember our slots in state."""
    if src.lookup("org.cinnamon.desktop.keybindings", True) is None:
        return False
    SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
    base = Gio.Settings.new("org.cinnamon.desktop.keybindings")
    names = list(base.get_strv("custom-list"))

    def path_for(slot):
        return f"/org/cinnamon/desktop/keybindings/custom-keybindings/{slot}/"

    def slot_command(slot):
        try:
            return Gio.Settings.new_with_path(SCHEMA, path_for(slot)).get_string("command")
        except Exception:
            return ""

    # 1. Migrate: drop legacy non-numeric voxfox-* names and clear their values.
    for legacy in _LEGACY_SHORTCUT_NAMES:
        if legacy in names:
            names.remove(legacy)
        try:
            s = Gio.Settings.new_with_path(SCHEMA, path_for(legacy))
            s.reset("name"); s.reset("command"); s.reset("binding")
        except Exception as e:
            log.debug(f"clear legacy {legacy}: {e}")

    # 2. Remove every slot that currently holds a VoxFox command (old binding,
    #    duplicate, or a previous install), then create fresh slots below.
    #    Recreating the keybindings rather than overwriting a slot's binding in
    #    place is what makes cinnamon-settings-daemon re-grab the new keys — an
    #    in-place binding change is not reliably re-grabbed, which left changed
    #    shortcuts dead.
    for slot in list(names):
        if slot_command(slot).startswith("voxfox"):
            try:
                s = Gio.Settings.new_with_path(SCHEMA, path_for(slot))
                s.reset("name"); s.reset("command"); s.reset("binding")
            except Exception as e:
                log.debug(f"clear voxfox slot {slot}: {e}")
            names.remove(slot)

    # 2.5 Allocate fresh numeric slots for the six actions.
    name_set = set(names)
    keys = [a[0] for a in _SHORTCUT_ACTIONS]
    fresh = _next_custom_slots(name_set, len(keys))
    assigned = dict(zip(keys, fresh))

    # 3. Write each slot and ensure it is listed; keep the list numeric & sorted.
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        slot = assigned[key]
        s = Gio.Settings.new_with_path(SCHEMA, path_for(slot))
        s.set_string("name", label)
        s.set_string("command", cmd)
        s.set_strv("binding", [_binding_for(state, key, binding)])
        if slot not in name_set:
            names.append(slot)
            name_set.add(slot)
    # Flush the slot data to dconf *before* changing custom-list: the daemon
    # re-reads the listed slots the moment custom-list changes, so the binding
    # values must already be committed or it grabs nothing (and only a restart
    # fixes it).
    Gio.Settings.sync()
    names.sort(key=_slot_sort_key)
    base.set_strv("custom-list", names)
    Gio.Settings.sync()   # then flush the list itself
    state["cinnamon_shortcut_slots"] = assigned
    log.info("Installed Cinnamon keyboard shortcuts")
    return True


def _install_gnome_shortcuts(src, state):
    """GNOME: custom-keybindings holds entry PATHS; binding is a STRING. Same
    numeric-slot approach as Cinnamon so gnome-control-center's add button
    keeps working and upgraders' legacy voxfox-* paths get migrated."""
    if src.lookup("org.gnome.settings-daemon.plugins.media-keys", True) is None:
        return False
    SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
    PREFIX = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
    base = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
    paths = list(base.get_strv("custom-keybindings"))

    def slot_of(p):
        return p[len(PREFIX):].strip("/") if p.startswith(PREFIX) else p.strip("/")

    def cmd_at(p):
        try:
            return Gio.Settings.new_with_path(SCHEMA, p).get_string("command")
        except Exception:
            return ""

    # 1. Migrate legacy voxfox-* paths.
    for legacy in _LEGACY_SHORTCUT_NAMES:
        lp = f"{PREFIX}{legacy}/"
        if lp in paths:
            paths.remove(lp)
        try:
            s = Gio.Settings.new_with_path(SCHEMA, lp)
            s.reset("name"); s.reset("command"); s.reset("binding")
        except Exception as e:
            log.debug(f"clear legacy gnome {legacy}: {e}")

    # 2. Remove every slot holding a VoxFox command (old binding, duplicate, or
    #    previous install), then create fresh slots below — recreating rather
    #    than overwriting in place is what makes the daemon re-grab the new keys.
    for p in list(paths):
        if cmd_at(p).startswith("voxfox"):
            try:
                s = Gio.Settings.new_with_path(SCHEMA, p)
                s.reset("name"); s.reset("command"); s.reset("binding")
            except Exception as e:
                log.debug(f"clear voxfox slot {slot_of(p)}: {e}")
            paths.remove(p)

    # 2.5 Allocate fresh numeric slots for the six actions.
    slot_set = {slot_of(p) for p in paths}
    keys = [a[0] for a in _SHORTCUT_ACTIONS]
    fresh = _next_custom_slots(slot_set, len(keys))
    assigned = dict(zip(keys, fresh))

    # 3. Write and list.
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        slot = assigned[key]
        p = f"{PREFIX}{slot}/"
        s = Gio.Settings.new_with_path(SCHEMA, p)
        s.set_string("name", label)
        s.set_string("command", cmd)
        s.set_string("binding", _binding_for(state, key, binding))
        if p not in paths:
            paths.append(p)
    Gio.Settings.sync()   # flush slot data before changing the list (see Cinnamon)
    paths.sort(key=lambda p: _slot_sort_key(slot_of(p)))
    base.set_strv("custom-keybindings", paths)
    Gio.Settings.sync()   # then flush the list itself
    state["gnome_shortcut_slots"] = assigned
    log.info("Installed GNOME keyboard shortcuts")
    return True


def _install_lxqt_shortcuts(src, state):
    """LXQt: global shortcuts live in a Qt-INI file read by lxqt-globalkeysd
    (~/.config/lxqt/globalkeyshortcuts.conf). A command shortcut is a section
    named '<KeySeq>.<N>', with '+' encoded as %2B and N a unique index, holding
    Comment / Enabled / Exec — where Exec is comma-separated ('voxfox, --read')
    and the Super key is spelled 'Meta'. On each install we drop our own old
    sections (matched by Exec) and write the current six, preserving any
    sections the user added themselves, then let the daemon's file-watcher
    reload. This makes changing a shortcut replace its old key. No-op outside
    LXQt. `src` is unused (LXQt doesn't use GSettings); kept for a uniform
    installer signature."""
    import re
    import configparser

    conf = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "lxqt", "globalkeyshortcuts.conf")
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    # The dispatcher runs every installer on every desktop, so only act when
    # this really is LXQt (or its config already exists).
    if "lxqt" not in desktop and not os.path.exists(conf):
        return False

    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str  # Qt keys are case-sensitive (Comment, Exec, path)

    our_cmds = {cmd for _k, _l, cmd, _b in _SHORTCUT_ACTIONS}
    max_idx = 0
    if os.path.exists(conf):
        try:
            cp.read(conf, encoding="utf-8")
        except Exception as e:
            log.debug(f"lxqt shortcuts: cannot parse conf: {e}")
            return False
        # Remove any section that runs one of our commands (old VoxFox bindings),
        # so a changed shortcut replaces its old key instead of piling up. Other
        # sections (the user's own shortcuts) are preserved.
        for sect in list(cp.sections()):
            ex = cp[sect].get("Exec", "")
            norm = " ".join(p.strip() for p in ex.split(",")) if ex else ""
            if norm in our_cmds:
                cp.remove_section(sect)
            else:
                m = re.search(r"\.(\d+)$", sect)
                if m:
                    max_idx = max(max_idx, int(m.group(1)))

    if not cp.has_section("General"):
        cp.add_section("General")
        cp["General"]["MultipleActionsBehaviour"] = "first"

    idx = max_idx
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        combo = _binding_to_lxqt(_binding_for(state, key, binding))
        if not combo:
            log.debug(f"LXQt: cannot convert binding for {key}, skipping")
            continue
        idx += 1
        sect = f"{combo}.{idx}"
        cp.add_section(sect)
        cp[sect]["Comment"] = label
        cp[sect]["Enabled"] = "true"
        cp[sect]["Exec"] = ", ".join(cmd.split())     # 'voxfox, --read'

    try:
        os.makedirs(os.path.dirname(conf), exist_ok=True)
        with open(conf, "w", encoding="utf-8") as f:
            cp.write(f, space_around_delimiters=False)
    except Exception as e:
        log.debug(f"lxqt shortcuts write failed: {e}")
        return False
    log.info("Installed LXQt keyboard shortcuts")
    return True


def _kde_key_norm(combo):
    """Normalise a KDE-style key combo ('Meta+Ctrl+A') into an order-
    independent form for comparison: (frozenset of uppercased modifiers,
    uppercased key). Returns None for an empty/unparsable combo."""
    parts = [p for p in (combo or "").replace(" ", "").split("+") if p]
    if not parts:
        return None
    *mods, key = parts
    return (frozenset(m.upper() for m in mods), key.upper())


def _kde_parse_bindings(path):
    """Best-effort read of ~/.config/kglobalshortcutsrc.

    Returns {normalised_key: [(component, action, owner_label), ...]} for
    every bound (non-empty, non-'none') action in the file, across ALL
    components — not just VoxFox's own. Deliberately a small line-based
    reader rather than configparser: KDE's ini dialect (duplicate-looking
    keys, locale-suffixed groups) isn't guaranteed to round-trip cleanly
    through Python's configparser, and all that's needed here is "which
    key does this line bind, and whose component is it".
    """
    out = {}
    if not path or not os.path.exists(path):
        return out
    group = None
    friendly = {}
    entries = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                s = line.strip()
                if not s or s.startswith(("#", ";")):
                    continue
                if s.startswith("[") and s.endswith("]"):
                    group = s[1:-1]
                    continue
                if group is None or "=" not in line:
                    continue
                k, _sep, v = line.partition("=")
                k = k.strip()
                if k == "_k_friendly_name":
                    friendly[group] = v.strip()
                    continue
                if not k:
                    continue
                primary = v.split(",", 1)[0].strip()
                if primary and primary.lower() != "none":
                    entries.append((group, k, primary))
    except Exception as e:
        log.debug(f"KDE: could not read {path}: {e}")
        return out
    for grp, action, primary in entries:
        norm = _kde_key_norm(primary)
        if norm:
            owner = friendly.get(grp) or grp[:-8] if grp.endswith(".desktop") else grp
            out.setdefault(norm, []).append((grp, action, owner))
    return out


def _install_kde_shortcuts(state, conflicts=None):
    """Install VoxFox's global shortcuts on KDE Plasma.

    KDE stores global shortcuts in ~/.config/kglobalshortcutsrc, keyed per
    component. We register each VoxFox command as its own component there via
    kwriteconfig, which is what actually binds (and rebinds) the key — writing
    a .desktop file alone only registers a shortcut the first time KDE indexes
    it and never updates an existing binding. Each install overwrites the
    stored value, so changing a key in Settings replaces the old one.

    Before writing, each key is checked against every OTHER component already
    in kglobalshortcutsrc (another app's shortcut, a Plasma shortcut, or even
    a different VoxFox action). KGlobalAccel silently drops a shortcut that
    clashes with one already registered elsewhere — writing straight to the
    file bypasses the normal KGlobalAccel API, which would otherwise catch
    that itself — so a colliding key is skipped here rather than written and
    then quietly lost on reload. When `conflicts` (a list) is given, each
    skipped action is appended as (action_key, effective_binding, owner_label)
    so the caller can tell the user what happened and with what it collided.

    We also drop a matching .desktop launcher so the command has a name in the
    KDE shortcuts UI and so kglobalaccel can resolve the key to a runnable
    command; a brand-new launcher needs a sycoca rebuild (done below) before
    KDE recognises it, or the key gets bound with no command behind it.
    No-op when not on KDE. A change may need a re-login in the worst case.
    Returns True on success (at least one binding written).
    """
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    if "kde" not in desktop and "plasma" not in desktop:
        return False

    kwriteconfig = None
    for tool in ("kwriteconfig6", "kwriteconfig5"):
        if vf._have(tool):
            kwriteconfig = tool
            break
    if not kwriteconfig:
        log.debug("KDE: no kwriteconfig tool found")
        return False

    cfg = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "kglobalshortcutsrc")
    existing = _kde_parse_bindings(cfg)

    written = 0
    for key, label, cmd, binding in _SHORTCUT_ACTIONS:
        eff = _binding_for(state, key, binding)
        combo = _binding_to_kde(eff)
        if not combo:
            continue
        component = f"voxfox-{key}.desktop"

        clash_owner = None
        for grp, _action, owner in existing.get(_kde_key_norm(combo), []):
            if grp != component:
                clash_owner = owner
                break
        if clash_owner:
            log.debug(f"KDE: {key} ({combo}) clashes with {clash_owner}, "
                      "skipping so it isn't silently dropped by kglobalaccel")
            if conflicts is not None:
                conflicts.append((key, eff, clash_owner))
            continue

        # kglobalshortcutsrc format per action:
        #   [component][_k_friendly_name]=...
        #   ActionName=<key>,<default>,<friendly text>
        # The "_launch" action name is what a .desktop launcher uses.
        value = f"{combo},none,{label}"
        try:
            subprocess.run(
                [kwriteconfig, "--file", cfg, "--group", component,
                 "--key", "_launch", value],
                capture_output=True, timeout=15)
            subprocess.run(
                [kwriteconfig, "--file", cfg, "--group", component,
                 "--key", "_k_friendly_name", label],
                capture_output=True, timeout=15)
            written += 1
        except Exception as e:
            log.debug(f"KDE: kwriteconfig failed for {key}: {e}")

    if not written:
        return False

    # A matching launcher so the command exists and has a name in the UI.
    appdir = os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
        "applications")
    try:
        os.makedirs(appdir, exist_ok=True)
        for key, label, cmd, binding in _SHORTCUT_ACTIONS:
            path = os.path.join(appdir, f"voxfox-{key}.desktop")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\n"
                        "Type=Application\n"
                        f"Name={label}\n"
                        f"Exec={cmd}\n"
                        "NoDisplay=true\n"
                        "Terminal=false\n"
                        "StartupNotify=false\n")
    except Exception as e:
        log.debug(f"KDE: cannot write launcher: {e}")

    # A key only actually launches its command once KDE's service database
    # (sycoca) knows the .desktop file — existing shortcuts survive a
    # kglobalaccel restart alone, but a *brand-new* one (like a shortcut a
    # user just assigned to an action that never had a key before) needs an
    # explicit rebuild, or the binding is registered with no command behind
    # it and the key silently does nothing.
    for tool in ("kbuildsycoca6", "kbuildsycoca5"):
        if vf._have(tool):
            try:
                subprocess.run([tool, "--noincremental"],
                               capture_output=True, timeout=15)
            except Exception as e:
                log.debug(f"KDE: kbuildsycoca failed: {e}")
            break

    # Ask kglobalaccel to reload so the new/changed bindings take effect
    # without a full re-login where possible.
    for tool in ("kquitapp6", "kquitapp5"):
        if vf._have(tool):
            try:
                subprocess.run([tool, "kglobalaccel"],
                               capture_output=True, timeout=10)
                time.sleep(0.5)
            except Exception:
                pass
            break
    for tool in ("kglobalaccel6", "kglobalaccel5"):
        if vf._have(tool):
            try:
                subprocess.Popen([tool],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except Exception:
                pass
            break

    log.info(f"Installed {written} KDE keyboard shortcuts")
    return True


def _binding_to_kde(binding):
    """Convert a stored accelerator ('<Super>z') to the KDE X-KDE-Shortcuts
    spelling ('Meta+Z'). Returns '' when it can't be parsed."""
    if not binding:
        return ""
    mods = {"<Super>": "Meta+", "<Primary>": "Ctrl+", "<Ctrl>": "Ctrl+",
            "<Control>": "Ctrl+", "<Shift>": "Shift+", "<Alt>": "Alt+"}
    rest = binding
    out = ""
    changed = True
    while changed:
        changed = False
        for token, kde in mods.items():
            if rest.startswith(token):
                out += kde
                rest = rest[len(token):]
                changed = True
    key = rest.strip()
    if not key:
        return ""
    return out + key.upper()


def _install_xfce_shortcuts(state):
    """Install VoxFox's global shortcuts on XFCE via xfconf-query.

    XFCE stores custom keyboard shortcuts in the xfce4-keyboard-shortcuts
    channel under /commands/custom/<binding>. xfconf-query is the only stable
    interface (the XML file location varies between XFCE versions and is not
    meant for direct editing). The Super key maps to <Super> in XFCE bindings.

    The `state` parameter is unused (no numeric-slot tracking needed here);
    kept for a uniform installer signature. On each install we first remove any
    existing custom binding that runs one of our commands (whatever key it is
    on), then write the current six — so changing a shortcut replaces the old
    key instead of leaving it bound. No-op when not on XFCE or xfconf-query is
    unavailable."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    if "xfce" not in desktop:
        return False
    if not vf._have("xfconf-query"):
        log.debug("xfconf-query not found; skipping XFCE shortcut install")
        return False

    CHANNEL = "xfce4-keyboard-shortcuts"
    our_cmds = {cmd for _k, _l, cmd, _b in _SHORTCUT_ACTIONS}
    # List existing custom command properties.
    try:
        out = subprocess.run(
            ["xfconf-query", "-c", CHANNEL, "-l"],
            capture_output=True, text=True, timeout=5)
        props = [p.strip() for p in out.stdout.splitlines()
                 if p.strip().startswith("/commands/custom/")]
    except Exception as e:
        log.debug(f"xfconf-query list failed: {e}")
        return False

    # Remove any existing binding that runs one of our commands, so a changed
    # shortcut doesn't leave its previous key working.
    for prop in props:
        try:
            r = subprocess.run(
                ["xfconf-query", "-c", CHANNEL, "-p", prop],
                capture_output=True, text=True, timeout=5)
            if r.stdout.strip() in our_cmds:
                subprocess.run(
                    ["xfconf-query", "-c", CHANNEL, "-p", prop, "-r"],
                    capture_output=True, text=True, timeout=5)
        except Exception:
            pass

    # Write the current six.
    written = 0
    for key, _label, cmd, binding in _SHORTCUT_ACTIONS:
        # XFCE uses the same accelerator format as the stored binding.
        prop = f"/commands/custom/{_binding_for(state, key, binding)}"
        try:
            subprocess.run(
                ["xfconf-query", "-c", CHANNEL, "-p", prop,
                 "--create", "-t", "string", "-s", cmd],
                capture_output=True, text=True, timeout=5, check=True)
            written += 1
        except Exception as e:
            log.debug(f"xfconf-query set {prop} failed: {e}")

    log.info(f"Installed {written} XFCE keyboard shortcuts")
    return True


def _cinnamon_reload():
    """Soft-restart the Cinnamon shell (windows are preserved) so it re-grabs
    freshly-installed custom keybindings. Cinnamon rebuilds its keybindings only
    on certain triggers that a plain settings write doesn't hit, so without this
    an install needs a manual Ctrl+Alt+Esc. Uses the same DBus call as Alt+F2 r.
    No-op off Cinnamon or if the call fails."""
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " "
               + os.environ.get("XDG_SESSION_DESKTOP", "")).lower()
    if "cinnamon" not in desktop:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync("org.Cinnamon", "/org/Cinnamon", "org.Cinnamon",
                      "RestartCinnamon", GLib.Variant("(b)", (False,)),
                      None, Gio.DBusCallFlags.NONE, 4000, None)
        log.info("Requested Cinnamon reload to activate shortcuts")
        return True
    except Exception as e:
        log.debug(f"cinnamon reload failed: {e}")
        return False


def _install_shortcuts(state, conflicts=None):
    """Register VoxFox's global keyboard shortcuts with the desktop:

        Super+Z  read          (voxfox --read)
        Super+X  stop          (voxfox --stop)
        Super+C  switch voice  (voxfox --toggle-slot)
        Super+W  dictation     (voxfox --whisper-toggle)
        Super+A  OCR select    (voxfox --ocr-select)
        Super+V  read web page (voxfox --read-page)

    On GNOME and Cinnamon these are written as custom keybindings via GSettings
    (numeric customN slots tracked in `state`, legacy voxfox-* names migrated,
    idempotent). On LXQt they are appended to globalkeyshortcuts.conf as Meta+
    command entries. On XFCE they are written via xfconf-query into the
    xfce4-keyboard-shortcuts channel. On KDE Plasma they are registered as
    .desktop files with X-KDE-Shortcuts lines. Writing for several desktops is
    harmless;
    each installer is a no-op where its desktop isn't present. Mutates `state`
    (the caller persists it) and returns True if at least one desktop accepted
    them. Users can change or remove them in the system keyboard settings."""
    installed = False
    # LXQt and XFCE use config files / CLI tools, not GSettings; try them
    # independently (a pure LXQt/XFCE box may have no relevant GSettings schemas).
    try:
        if _install_lxqt_shortcuts(None, state):
            installed = True
    except Exception as e:
        log.debug(f"_install_lxqt_shortcuts failed: {e}")
    try:
        if _install_xfce_shortcuts(state):
            installed = True
    except Exception as e:
        log.debug(f"_install_xfce_shortcuts failed: {e}")
    try:
        if _install_kde_shortcuts(state, conflicts):
            installed = True
    except Exception as e:
        log.debug(f"_install_kde_shortcuts failed: {e}")
    try:
        src = Gio.SettingsSchemaSource.get_default()
        if src is not None:
            for fn in (_install_cinnamon_shortcuts, _install_gnome_shortcuts):
                try:
                    if fn(src, state):
                        installed = True
                except Exception as e:
                    log.debug(f"{fn.__name__} failed: {e}")
    except Exception as e:
        log.debug(f"shortcut install skipped: {e}")
    return installed


