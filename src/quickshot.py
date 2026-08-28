#!/usr/bin/env python3
# quickshot - selecteer een gebied op het scherm en sla het direct op.
# Werkt op X11 en op Wayland. Licentie: MIT.

import os
import sys
import time
import atexit
import contextlib
import shutil
import tempfile
import subprocess


def _restart_on_xwayland():
    """Restart as an X11 client so the selector can cover every monitor.

    On Wayland a client may not choose its own position, which left the
    selector stuck on one monitor. As an XWayland client it can be moved
    and sized freely, and set_keep_above() works again.

    GDK_BACKEND is read when the display is opened, and setting it from
    inside the process is already too late, so we hand ourselves a
    corrected environment and start over. This has to happen before gi
    is imported.

    Capturing is unaffected: that goes through grim or the portal, both
    of which key off the session, not off our GTK backend."""
    if os.environ.get("QUICKSHOT_BACKEND_SWITCHED"):
        return
    if os.environ.get("GDK_BACKEND"):
        return
    wayland = (os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
               or bool(os.environ.get("WAYLAND_DISPLAY")))
    if not wayland or not os.environ.get("DISPLAY"):
        return
    env = dict(os.environ)
    env["GDK_BACKEND"] = "x11"
    env["QUICKSHOT_BACKEND_SWITCHED"] = "1"
    try:
        os.execve(sys.executable,
                  [sys.executable, os.path.abspath(__file__)]
                  + sys.argv[1:], env)
    except Exception:
        # Fall back to the old single-monitor behaviour rather than
        # failing to start at all.
        pass


_restart_on_xwayland()

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, Gio


VERSION = "1.0.9"

DEBUG = os.environ.get("QUICKSHOT_DEBUG") == "1"
TARGET = None
PORTAL = False
MUTE = os.environ.get("QUICKSHOT_MUTE") != "0"


def log(message):
    if DEBUG:
        sys.stderr.write("[quickshot] %s\n" % message)
        sys.stderr.flush()


HELP = """Gebruik: quickshot [opties] [bestand.png]

Sleep een rechthoek over het scherm. Bij loslaten wordt die selectie
meteen opgeslagen. Escape of de rechtermuisknop annuleert.

Opties:
      --sound     laat het sluitergeluid gewoon horen
      --portal    laat GNOME of KDE zelf het gebied kiezen
      --overlay   het eigen selectiescherm (standaard)
  -v, --verbose   toon wat het programma doet
  -h, --help      toon deze uitleg
  -V, --version   toon het versienummer

Zonder bestandsnaam gaat de afbeelding naar Afbeeldingen/Screenshots.
Een andere map kies je met de omgevingsvariabele QUICKSHOT_DIR.
"""


def parse_args():
    global DEBUG, TARGET, PORTAL, MUTE
    for arg in sys.argv[1:]:
        if arg == "--sound":
            MUTE = False
        elif arg == "--portal":
            PORTAL = True
        elif arg == "--overlay":
            PORTAL = False
        elif arg in ("-v", "--verbose"):
            DEBUG = True
        elif arg in ("-h", "--help"):
            sys.stdout.write(HELP)
            sys.exit(0)
        elif arg in ("-V", "--version"):
            sys.stdout.write("quickshot %s\n" % VERSION)
            sys.exit(0)
        elif arg.startswith("-"):
            sys.stderr.write("Onbekende optie: %s\n" % arg)
            sys.stderr.write("Gebruik quickshot --help voor uitleg.\n")
            sys.exit(2)
        else:
            TARGET = os.path.abspath(arg)


# ---------------------------------------------------------------- hulpfuncties

@contextlib.contextmanager
def _nothing():
    yield None


def is_wayland():
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return True
    return "WAYLAND_DISPLAY" in os.environ


def total_geometry():
    """Logische afmeting van het hele bureaublad (alle schermen samen)."""
    display = Gdk.Display.get_default()
    x0 = y0 = 1 << 30
    x1 = y1 = -(1 << 30)
    for i in range(display.get_n_monitors()):
        g = display.get_monitor(i).get_geometry()
        x0 = min(x0, g.x)
        y0 = min(y0, g.y)
        x1 = max(x1, g.x + g.width)
        y1 = max(y1, g.y + g.height)
    if x1 <= x0:
        return 0, 0, 1920, 1080
    return x0, y0, x1 - x0, y1 - y0


def output_path():
    if TARGET:
        return TARGET
    folder = os.environ.get("QUICKSHOT_DIR")
    if not folder:
        base = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        if not base:
            base = os.path.expanduser("~")
        folder = os.path.join(base, "Screenshots")
    os.makedirs(folder, exist_ok=True)
    name = time.strftime("Screenshot_%Y-%m-%d_%H-%M-%S.png")
    return os.path.join(folder, name)


def brightness(pixbuf):
    """Ruwe gemiddelde helderheid, om een volledig zwarte opname te herkennen."""
    try:
        data = pixbuf.get_pixels()
    except Exception:
        return -1
    if not data:
        return -1
    channels = pixbuf.get_n_channels()
    step = max(channels, (len(data) // (4000 * channels)) * channels)
    sample = data[0:len(data):step]
    if not sample:
        return -1
    return sum(sample) / float(len(sample))


# ---------------------------------------------------------- scherm vastleggen

def capture_x11():
    root = Gdk.get_default_root_window()
    if root is None:
        log("x11: geen root window")
        return None
    try:
        pixbuf = Gdk.pixbuf_get_from_window(root, 0, 0,
                                            root.get_width(), root.get_height())
    except Exception as err:
        log("x11: fout %s" % err)
        return None
    log("x11: %s" % ("gelukt" if pixbuf else "leeg"))
    return pixbuf


def capture_grim():
    """Wayland op wlroots (Sway, Hyprland, labwc): grim."""
    if not GLib.find_program_in_path("grim"):
        log("grim: niet geinstalleerd")
        return None
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["grim", path], check=True, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        log("grim: gelukt")
        return pixbuf
    except Exception as err:
        log("grim: mislukt (%s)" % err)
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def cleanup_portal_file(path):
    """De portal legt een volledige schermfoto op schijf. Die is voor ons
    alleen tussenstap, dus die ruimen we op zodra hij ingelezen is."""
    if os.environ.get("QUICKSHOT_KEEP") == "1":
        log("bewaar tussenbestand: %s" % path)
        return
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return
    if age > 120:
        log("tussenbestand is ouder dan twee minuten, niet verwijderd: %s" % path)
        return
    try:
        os.unlink(path)
        log("tussenbestand verwijderd: %s" % path)
    except OSError as err:
        log("kon tussenbestand niet verwijderen (%s)" % err)


class QuietMoment(object):
    """Zet de systeemgeluiden van GNOME heel even uit, zodat het sluitergeluid
    van de schermopname niet klinkt. Daarna gaat de instelling terug."""

    def __init__(self):
        self.settings = None
        self.was_on = None

    def __enter__(self):
        if not MUTE:
            return self
        try:
            source = Gio.SettingsSchemaSource.get_default()
            if source is None or source.lookup("org.gnome.desktop.sound", True) is None:
                log("geluid: schema niet aanwezig, niets gedempt")
                return self
            settings = Gio.Settings.new("org.gnome.desktop.sound")
            if not settings.get_boolean("event-sounds"):
                log("geluid: stond al uit")
                return self
            settings.set_boolean("event-sounds", False)
            Gio.Settings.sync()
            self.settings = settings
            self.was_on = True
            atexit.register(self.restore)
            time.sleep(0.25)
            log("geluid: tijdelijk uit")
        except Exception as err:
            log("geluid: dempen mislukt (%s)" % err)
        return self

    def restore(self):
        if self.settings is None:
            return
        try:
            self.settings.set_boolean("event-sounds", True)
            Gio.Settings.sync()
            log("geluid: weer aan")
        except Exception as err:
            log("geluid: herstellen mislukt (%s)" % err)
        finally:
            self.settings = None

    def __exit__(self, *args):
        time.sleep(0.15)
        self.restore()
        return False


def portal_screenshot(interactive):
    """Vraag de portal om een opname. Geeft een bestandspad terug.
    Met interactive=True kiest de gebruiker zelf het gebied."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as err:
        log("portal: geen sessiebus (%s)" % err)
        return None

    token = "quickshot_%d_%d" % (os.getpid(), int(time.time()))
    sender = bus.get_unique_name()[1:].replace(".", "_")
    request_path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)

    answer = {}
    loop = GLib.MainLoop()

    def on_response(conn, sender_name, obj_path, iface, signal, params):
        code, results = params.unpack()
        answer["code"] = code
        answer["uri"] = results.get("uri")
        loop.quit()

    sub = bus.signal_subscribe("org.freedesktop.portal.Desktop",
                               "org.freedesktop.portal.Request",
                               "Response", request_path, None,
                               Gio.DBusSignalFlags.NONE, on_response)

    options = {
        "handle_token": GLib.Variant("s", token),
        "interactive": GLib.Variant("b", bool(interactive)),
    }

    # Bij een niet-interactieve opname klinkt meteen het sluitergeluid.
    # Dat dempen we heel even. Kiest de gebruiker zelf in het venster van
    # GNOME, dan laten we het geluid met rust.
    with QuietMoment() if not interactive else _nothing():
        try:
            bus.call_sync("org.freedesktop.portal.Desktop",
                          "/org/freedesktop/portal/desktop",
                          "org.freedesktop.portal.Screenshot",
                          "Screenshot",
                          GLib.Variant("(sa{sv})", ("", options)),
                          None, Gio.DBusCallFlags.NONE, 10000, None)
        except GLib.Error as err:
            log("portal: aanroep mislukt (%s)" % err)
            bus.signal_unsubscribe(sub)
            return None

        GLib.timeout_add_seconds(60, lambda: (loop.quit(), False)[1])
        loop.run()
    bus.signal_unsubscribe(sub)

    log("portal: antwoord code=%s uri=%s" % (answer.get("code"), answer.get("uri")))
    if answer.get("code") != 0 or not answer.get("uri"):
        return None

    return GLib.filename_from_uri(answer["uri"])[0]


def capture_portal():
    """Volledige schermopname via de portal, als afbeelding in het geheugen."""
    path = portal_screenshot(False)
    if not path:
        return None
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    except GLib.Error as err:
        log("portal: kan bestand niet lezen (%s)" % err)
        return None
    cleanup_portal_file(path)
    return pixbuf


def portal_select_and_save():
    """De portal laat de gebruiker zelf het gebied kiezen en levert dat
    uitgesneden aan. Zo is er maar een opname en geen flits vooraf."""
    path = portal_screenshot(True)
    if not path:
        return None
    target = output_path()
    try:
        shutil.move(path, target)
        log("opgeslagen via portal: %s" % target)
        return target
    except Exception as err:
        log("verplaatsen mislukt (%s), nu kopieren" % err)
    try:
        shutil.copyfile(path, target)
        cleanup_portal_file(path)
        return target
    except Exception as err:
        log("kopieren mislukt (%s)" % err)
        return None


def capture_screen():
    """Op Wayland nooit terugvallen op X11: dat levert een zwart beeld op."""
    if is_wayland():
        return capture_grim() or capture_portal()
    return capture_x11() or capture_grim() or capture_portal()


# ------------------------------------------------------------- selectievenster

class Selector(Gtk.Window):

    def __init__(self, pixbuf, scale, origin_x, origin_y, width, height, x11):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)
        self.pixbuf = pixbuf
        self.scale = scale
        self.ox = origin_x
        self.oy = origin_y
        # True when GTK talks to an X server: a real X11 session or
        # XWayland. Decides placement and whether a grab is allowed.
        self.x11 = x11
        self.start = None
        self.current = None
        self.saved = None
        self.grabbed = False
        self.mapped_once = False

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_resizable(False)
        self.set_accept_focus(True)
        self.set_can_focus(True)
        self.set_title("quickshot")

        # Een echte tekenlaag als kind: zonder kind krijgt het venster onder
        # Wayland geen afmeting en verschijnt het niet in beeld.
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(width, height)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                             | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("button-release-event", self.on_release)
        self.add(self.area)

        self.add_events(Gdk.EventMask.KEY_PRESS_MASK
                        | Gdk.EventMask.KEY_RELEASE_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("key-press-event", self.on_key)
        self.connect("map-event", self.on_map)
        self.connect("destroy", lambda *a: Gtk.main_quit())

        self.set_default_size(width, height)
        if x11:
            # Cover the whole desktop, however many monitors that is.
            self.move(origin_x, origin_y)
            self.resize(width, height)
        else:
            # No XWayland: we cannot place ourselves, so the best we can
            # do is fill the monitor the compositor gives us.
            self.fullscreen()

        # noodrem: nooit langer dan twee minuten een scherm blokkeren
        GLib.timeout_add_seconds(120, self.on_timeout)

    # -- muis en toetsen

    def on_map(self, *args):
        # Belangrijk: hier nooit present() aanroepen. Dat zet het venster
        # opnieuw op het scherm en veroorzaakt een eindeloze lus.
        if self.mapped_once:
            return False
        self.mapped_once = True

        display = self.get_display()
        cursor = Gdk.Cursor.new_from_name(display, "crosshair")
        window = self.get_window()
        if window is not None and cursor is not None:
            window.set_cursor(cursor)

        # Globale grabs bestaan alleen op X11; onder XWayland mogen ze wel.
        if self.x11:
            seat = display.get_default_seat()
            status = seat.grab(window, Gdk.SeatCapabilities.ALL, True,
                               cursor, None, None, None)
            self.grabbed = (status == Gdk.GrabStatus.SUCCESS)
            log("grab: %s" % status)

        self.grab_focus()
        log("venster zichtbaar, grootte %dx%d, focus=%s"
            % (self.get_allocated_width(), self.get_allocated_height(),
               self.has_toplevel_focus()))
        GLib.idle_add(self.after_map)
        return False

    def after_map(self):
        if not self.has_toplevel_focus():
            log("nog geen toetsenbordfocus; klik in het venster om te selecteren")
        return False

    def release_grab(self):
        if not self.grabbed:
            return
        try:
            self.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self.grabbed = False

    def on_timeout(self):
        log("tijdslimiet bereikt, afsluiten")
        self.cancel()
        return False

    def on_press(self, widget, event):
        log("knop %s op %.0f,%.0f" % (event.button, event.x, event.y))
        if event.button != 1:
            self.cancel()
            return True
        self.start = (event.x, event.y)
        self.current = (event.x, event.y)
        self.area.queue_draw()
        return True

    def on_motion(self, widget, event):
        if self.start:
            self.current = (event.x, event.y)
            self.area.queue_draw()
        return True

    def on_release(self, widget, event):
        if event.button != 1 or not self.start:
            return True
        self.current = (event.x, event.y)
        rect = self.rect()
        self.release_grab()
        self.hide()
        if rect and rect[2] > 2 and rect[3] > 2:
            self.saved = self.save(rect)
        else:
            log("selectie te klein, niets opgeslagen")
        Gtk.main_quit()
        return True

    def on_key(self, widget, event):
        log("toets %s" % Gdk.keyval_name(event.keyval))
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q, Gdk.KEY_Q):
            self.cancel()
        return True

    def cancel(self):
        self.release_grab()
        self.hide()
        Gtk.main_quit()

    # -- tekenen

    def rect(self):
        if not self.start or not self.current:
            return None
        x0, y0 = self.start
        x1, y1 = self.current
        return (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    def paint_screenshot(self, cr):
        cr.save()
        cr.scale(1.0 / self.scale, 1.0 / self.scale)
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf,
                                    -self.ox * self.scale,
                                    -self.oy * self.scale)
        cr.paint()
        cr.restore()

    def on_draw(self, widget, cr):
        self.paint_screenshot(cr)
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.paint()

        rect = self.rect()
        if rect and rect[2] > 0 and rect[3] > 0:
            x, y, w, h = rect
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            self.paint_screenshot(cr)
            cr.restore()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(1)
            cr.rectangle(x + 0.5, y + 0.5, w, h)
            cr.stroke()
        return True

    # -- opslaan

    def save(self, rect):
        x, y, w, h = rect
        pw_total = self.pixbuf.get_width()
        ph_total = self.pixbuf.get_height()

        px = int(round((x + self.ox) * self.scale))
        py = int(round((y + self.oy) * self.scale))
        pw = int(round(w * self.scale))
        ph = int(round(h * self.scale))

        px = max(0, min(px, pw_total - 1))
        py = max(0, min(py, ph_total - 1))
        pw = max(1, min(pw, pw_total - px))
        ph = max(1, min(ph, ph_total - py))

        log("uitsnede %d,%d %dx%d" % (px, py, pw, ph))
        piece = GdkPixbuf.Pixbuf.new_subpixbuf(self.pixbuf, px, py, pw, ph)
        path = output_path()
        piece.savev(path, "png", [], [])
        return path


# ---------------------------------------------------------------------- start

def check_cairo():
    """Zonder python3-gi-cairo mislukt elke tekenopdracht en blijft het
    scherm zwart. Beter meteen duidelijk zeggen wat er ontbreekt."""
    try:
        gi.require_foreign("cairo")
    except Exception as err:
        log("cairo-koppeling ontbreekt (%s)" % err)
        return False
    return True


def main():
    parse_args()

    if not check_cairo():
        sys.stderr.write("Onderdeel ontbreekt: de cairo-koppeling van Python.\n")
        sys.stderr.write("Installeer die met: sudo apt install python3-gi-cairo\n")
        return 1

    if Gdk.Display.get_default() is None:
        sys.stderr.write("Geen grafische sessie gevonden.\n")
        return 1

    wayland = is_wayland()
    log("quickshot %s, sessie: %s, backend: %s"
        % (VERSION, "wayland" if wayland else "x11",
           type(Gdk.Display.get_default()).__name__))

    if wayland and PORTAL:
        # Op verzoek: GNOME of KDE kiest zelf het gebied.
        saved = portal_select_and_save()
        if not saved:
            sys.stderr.write("Er is geen selectie opgeslagen.\n")
            return 1
        print(saved)
        return 0

    # Standaard: eigen selectiescherm. Onder Wayland mag een programma het
    # scherm niet zelf uitlezen, dus gaat de opname via grim of de portal.
    # Op GNOME hoort daar een flits en een geluidje bij; dat komt van de
    # compositor en is van buitenaf niet uit te zetten.
    pixbuf = capture_screen()

    if pixbuf is None:
        sys.stderr.write("Kon het scherm niet vastleggen.\n")
        if wayland:
            sys.stderr.write("Probeer: sudo apt install grim\n")
        return 1

    level = brightness(pixbuf)
    log("opname %dx%d, helderheid %.1f" % (pixbuf.get_width(),
                                           pixbuf.get_height(), level))
    if 0 <= level < 1.0:
        sys.stderr.write("De opname is volledig zwart; er is niets opgeslagen.\n")
        return 1

    tx, ty, tw, th = total_geometry()
    scale = pixbuf.get_width() / float(tw) if tw else 1.0
    log("bureaublad %d,%d %dx%d, schaal %.3f" % (tx, ty, tw, th, scale))

    # Ask the display what it actually is rather than what we asked for:
    # the restart above may have been skipped or may have failed.
    x11_window = type(Gdk.Display.get_default()).__name__.startswith("X11")
    if x11_window:
        # One window over the entire desktop, so a selection may cross
        # from one monitor to the next.
        ox, oy, w, h = tx, ty, tw, th
    else:
        # Native Wayland: no placement, so the primary monitor it is.
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        g = monitor.get_geometry()
        ox, oy, w, h = g.x, g.y, g.width, g.height
    log("venster %d,%d %dx%d, x11=%s" % (ox, oy, w, h, x11_window))

    window = Selector(pixbuf, scale, ox, oy, w, h, x11_window)
    window.show_all()
    Gtk.main()

    if window.saved:
        print(window.saved)
        return 0
    log("geannuleerd")
    return 1


if __name__ == "__main__":
    sys.exit(main())
