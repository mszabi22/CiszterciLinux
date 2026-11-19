#!/usr/bin/env python3
"""Ciszterci Admin – YaST-szerű vezérlőpult (GTK3) egyszerű felhasználóknak.

Első indításkor (python3 ciszterci-admin.py) telepíti, amire szüksége van, beépül a rendszerbe
(/usr/local/bin/ciszterci-admin, alkalmazásmenü: Rendszer › Ciszterci Admin), majd újraindul.
A jogosultságot pkexec adja: egyetlen hitelesítés után egy szűk műveletkészletű root segéd
dolgozik (nem tetszőleges parancsokat futtat). Eltávolítás: ciszterci-admin --uninstall
"""
import sys, os, json, re, shlex, subprocess, shutil, hashlib, time, threading, urllib.request, datetime

LIBDIR = "/usr/local/lib/ciszterci-admin"
INSTALL_PATH = LIBDIR + "/ciszterci-admin.py"      # root tulajdonú példány, ezt futtatja a pkexec
BIN_PATH = "/usr/local/bin/ciszterci-admin"
DESKTOP_PATH = "/usr/share/applications/ciszterci-admin.desktop"
ICON_PATH = "/usr/share/icons/hicolor/scalable/apps/ciszterci-admin.svg"
LOG = "/var/log/ciszterci-admin-install.log"
REQUIRED = ["python3", "python3-gi", "gir1.2-gtk-3.0", "pkexec"]
POLKIT_AGENTS = ["policykit-1-gnome", "polkit-1-gnome", "xfce-polkit", "lxpolkit"]

GREETER_CONF = "/etc/lightdm/lightdm-gtk-greeter.conf"
LIGHTDM_CONF = "/etc/lightdm/lightdm.conf"
LIGHTDM_DROPIN = "/etc/lightdm/lightdm.conf.d/99-ciszterci-admin.conf"
BG_DIR = "/usr/share/backgrounds/ciszterci"
SCRIPTS = {
    "ad_join": "/usr/local/bin/linux-ad-member.sh",
    "ad_leave": "/usr/local/bin/linux-ad-leave.sh",
    "admin_tools": "/usr/local/bin/add-admin-tools.sh",
    "remove_admin_tools": "/usr/local/bin/remove-admin-tools.sh",
    "old_kernels": "/usr/local/bin/old-kernel-remover",
}

DESKTOP_FILE = (
    "[Desktop Entry]\nVersion=1.0\nType=Application\n"
    "Name=Ciszterci Vezérlőpult\nGenericName=Vezérlőpult\n"
    "Comment=Ciszterci Vezérlőpult – bejelentkező ablak, távoli segítség, tartomány, idő, rendszer\n"
    "Exec=/usr/local/bin/ciszterci-admin\nIcon=ciszterci-admin\nTerminal=false\n"
    "Categories=System;\nKeywords=admin;vezérlőpult;beállítások;bejelentkezés;tartomány;idő;\n")

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#60a5fa"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient></defs>
<rect x="8" y="8" width="112" height="112" rx="26" fill="url(#g)"/>
<ellipse cx="62" cy="70" rx="27" ry="13" transform="rotate(-22 62 70)" fill="#fff"/>
<circle cx="84" cy="56" r="10" fill="#fff"/>
<path d="M91 53 L114 42 L92 59 Z" fill="#fff"/>
<path d="M50 66 C40 38 64 28 82 34 C72 46 62 57 50 66 Z" fill="#dbeafe"/>
<path d="M38 80 L18 94 L46 84 Z" fill="#fff"/>
<circle cx="86" cy="54" r="2.6" fill="#1d4ed8"/>
</svg>
"""


# ------------------------------------------------- telepítés / eltávolítás
def have(cmd):
    return any(os.path.exists(f"{d}/{cmd}") for d in ("/usr/sbin", "/usr/bin", "/sbin", "/bin"))


def deps_ok():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return have("pkexec")


def self_installed():
    return all(os.path.exists(p) for p in (INSTALL_PATH, BIN_PATH, DESKTOP_PATH, ICON_PATH))


def same_file(a, b):
    try:
        def h(p):
            with open(p, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        return h(a) == h(b)
    except OSError:
        return False


def note(msg):
    print(msg, flush=True)
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "Ciszterci Admin", msg], check=False)


def run_elevated(args):
    cmd = [sys.executable, os.path.realpath(__file__)] + args
    if os.geteuid() == 0:
        return subprocess.call(cmd)
    if sys.stdin.isatty() and shutil.which("sudo"):
        print("Rendszergazdai jogosultság kell (sudo jelszó)…")
        return subprocess.call(["sudo"] + cmd)
    if have("pkexec"):
        return subprocess.call(["pkexec"] + cmd)
    if shutil.which("sudo"):
        return subprocess.call(["sudo"] + cmd)
    print("Nincs sudo és pkexec sem: futtasd rendszergazdaként: " + " ".join(cmd))
    return 1


def ilog(msg):
    print(msg, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def sh(cmd, **kw):
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    try:
        with open(LOG, "a") as lf:
            return subprocess.run(cmd, env=env, stdout=lf, stderr=subprocess.STDOUT, **kw).returncode
    except FileNotFoundError:
        return 127


def pkg_ok(p):
    try:
        r = subprocess.run(["dpkg-query", "-W", "-f=${Status}", p], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return r.returncode == 0 and "install ok installed" in r.stdout


def put(path, data, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def refresh_caches():
    if shutil.which("update-desktop-database"):
        sh(["update-desktop-database", "/usr/share/applications"])
    if shutil.which("gtk-update-icon-cache"):
        sh(["gtk-update-icon-cache", "-f", "-t", "/usr/share/icons/hicolor"])


def install_main(src):
    if os.geteuid() != 0:
        print("A telepítéshez root jog kell.")
        return 1
    ilog("== Ciszterci Admin telepítése ==")
    need = [p for p in REQUIRED if not pkg_ok(p)]
    if need:
        ilog("Hiányzó csomagok telepítése: " + ", ".join(need))
        sh(["apt-get", "update"])
        if sh(["apt-get", "install", "-y"] + need) != 0:
            ilog(f"HIBA: a csomagtelepítés nem sikerült (részletek: {LOG}).")
            return 1
    agent = subprocess.run(["pgrep", "-f", "polkit.*agent|polkit-gnome|xfce-polkit|lxpolkit|polkit-kde"],
                           capture_output=True).returncode == 0
    if not agent:
        for c in POLKIT_AGENTS:
            if sh(["apt-cache", "show", c]) == 0:
                ilog(f"Polkit hitelesítő ügynök telepítése: {c} (kijelentkezés/belépés után él)")
                sh(["apt-get", "install", "-y", c])
                break
    os.makedirs(LIBDIR, exist_ok=True)
    os.chmod(LIBDIR, 0o755)
    if os.path.realpath(src) != INSTALL_PATH:
        shutil.copyfile(src, INSTALL_PATH + ".tmp")
        os.chmod(INSTALL_PATH + ".tmp", 0o755)
        os.replace(INSTALL_PATH + ".tmp", INSTALL_PATH)
    put(BIN_PATH, f'#!/bin/sh\nexec /usr/bin/python3 {INSTALL_PATH} "$@"\n', 0o755)
    put(DESKTOP_PATH, DESKTOP_FILE, 0o644)
    put(ICON_PATH, ICON_SVG, 0o644)
    refresh_caches()
    ilog("Kész: Alkalmazásmenü › Rendszer › Ciszterci Admin (parancs: ciszterci-admin)")
    return 0


def uninstall_main():
    for p in (BIN_PATH, DESKTOP_PATH, ICON_PATH):
        try:
            os.remove(p)
        except OSError:
            pass
    shutil.rmtree(LIBDIR, ignore_errors=True)
    refresh_caches()
    print("Eltávolítva. A telepített csomagokat és a beállításokat nem töröltem.")
    return 0


# --------------------------------------------------------------- ini-kezelés
def ini_get(path, section):
    out, cur = {}, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if not t or t[0] in "#;":
                    continue
                if t.startswith("[") and t.endswith("]"):
                    cur = t[1:-1]
                    continue
                if cur == section and "=" in t:
                    k, v = t.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def ini_set(path, section, updates):
    """Kulcsok beállítása/törlése (None = törlés) egy szakaszban, a megjegyzések megmaradnak."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    start = next((i for i, l in enumerate(lines) if l.strip() == f"[{section}]"), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{section}]")
        start = len(lines) - 1
    for k, v in updates.items():
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        idx = next((i for i in range(start + 1, end)
                    if re.match(rf"^\s*{re.escape(k)}\s*=", lines[i])), None)
        if v is None:
            if idx is not None:
                del lines[idx]
        elif idx is not None:
            lines[idx] = f"{k}={v}"
        else:
            ins = end
            while ins > start + 1 and not lines[ins - 1].strip():
                ins -= 1
            lines.insert(ins, f"{k}={v}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ----------------------------------------------------------- root segéd (pkexec)
def emit(o):
    print(json.dumps(o), flush=True)


def hlog(m):
    emit({"log": m})


def hrun(cmd, check=True):
    hlog("$ " + " ".join(cmd))
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C.UTF-8")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            hlog(line)
    rc = p.wait()
    if check and rc != 0:
        raise RuntimeError(f"A(z) {cmd[0]} hibakóddal állt le: {rc}")
    return rc


INDICATOR_RE = re.compile(r"~(host|spacer|clock|session|language|a11y|power)(;~(host|spacer|clock|session|language|a11y|power))*")
POSITION_RE = re.compile(r"\d{1,3}%(,(start|center|end))? \d{1,3}%(,(start|center|end))?")


def check_image(path):
    st = os.stat(path)
    if not os.path.isfile(path) or st.st_size > 40 * 1024 * 1024:
        raise RuntimeError("A háttérkép nem szabályos fájl, vagy túl nagy (max. 40 MB).")
    with open(path, "rb") as f:
        head = f.read(12)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"BM"):
        return ".bmp"
    raise RuntimeError("Csak PNG, JPEG vagy BMP háttérkép használható.")


def op_login(r):
    if not os.path.isdir("/etc/lightdm"):
        raise RuntimeError("A LightDM nincs telepítve, ezt a beállítást nem lehet alkalmazni.")
    upd = {}
    cf = r.get("clock_format")
    if cf is not None:
        if not re.fullmatch(r"[^\x00-\x1f\x7f]{1,64}", cf):
            raise RuntimeError("Érvénytelen időformátum.")
        upd["clock-format"] = cf
    ind = r.get("indicators")
    if ind is not None:
        if not INDICATOR_RE.fullmatch(ind):
            raise RuntimeError("Érvénytelen fejléc-elemlista.")
        upd["indicators"] = ind
    pp = r.get("panel_position")
    if pp is not None:
        if pp not in ("top", "bottom"):
            raise RuntimeError("Érvénytelen panelhely.")
        upd["panel-position"] = pp
    pos = r.get("position")
    if pos is not None:
        if not POSITION_RE.fullmatch(pos):
            raise RuntimeError("Érvénytelen ablakpozíció.")
        upd["position"] = pos
    bg = r.get("bg")
    if bg and bg.get("src"):
        ext = check_image(bg["src"])
        os.makedirs(BG_DIR, exist_ok=True)
        os.chmod(BG_DIR, 0o755)
        for old in os.listdir(BG_DIR):
            if old.startswith("login-background."):
                os.remove(os.path.join(BG_DIR, old))
        dest = os.path.join(BG_DIR, "login-background" + ext)
        shutil.copyfile(bg["src"], dest)
        os.chmod(dest, 0o644)
        upd["background"] = dest
        hlog(f"Háttérkép másolva: {dest}")
    elif bg and bg.get("reset"):
        upd["background"] = None
    if os.path.exists(GREETER_CONF) and not os.path.exists(GREETER_CONF + ".ciszterci-orig"):
        shutil.copy2(GREETER_CONF, GREETER_CONF + ".ciszterci-orig")
    ini_set(GREETER_CONF, "greeter", upd)
    hlog(f"Greeter beállítás írva: {', '.join(upd) or '(nincs változás)'}")
    if "hide_users" in r:
        # Mindkét állapotot explicit módon rögzítjük, így a kikapcsolás
        # akkor is érvényesül, ha egy korábbi konfiguráció true értéket tartalmaz.
        hide = bool(r["hide_users"])
        lines = ["[Seat:*]", f"greeter-hide-users={'true' if hide else 'false'}"]
        if hide:
            lines.append("greeter-show-manual-login=true")
        put(LIGHTDM_DROPIN, "\n".join(lines) + "\n", 0o644)

        # A korábbi verzió drop-in fájljának eltávolítása, ha létezik.
        legacy_dropin = "/etc/lightdm/lightdm.conf.d/50-ciszterci-admin.conf"
        try:
            os.remove(legacy_dropin)
        except FileNotFoundError:
            pass

        hlog("Felhasználólista elrejtve." if hide else "Felhasználólista újra látható.")
    return "Mentve. A változás a következő bejelentkező képernyőnél lép életbe (kijelentkezés után)."


PKG_WHITELIST = {"chrony", "nextcloud-desktop"}


def op_pkg(r):
    names = r.get("pkgs", [])
    if not names or not set(names) <= PKG_WHITELIST:
        raise RuntimeError("Nem engedélyezett csomag.")
    if r["action"] == "install":
        hrun(["apt-get", "update"], check=False)
        hrun(["apt-get", "install", "-y"] + names)
        return "Telepítve."
    if r["action"] == "remove":
        hrun(["apt-get", "remove", "-y"] + names)
        return "Eltávolítva."
    raise RuntimeError("Ismeretlen művelet.")


def download(url, dest, sha256=None):
    hlog(f"Letöltés: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ciszterci-admin"})
    h, done, last = hashlib.sha256(), 0, 0
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if done - last >= 10 << 20:
                last = done
                hlog(f"  {done >> 20} MB letöltve…")
    with open(dest, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise RuntimeError("A letöltött fájl nem .deb csomag.")
    if sha256 and h.hexdigest() != sha256.lower():
        raise RuntimeError("A letöltött csomag ellenőrző összege nem egyezik.")
    hlog(f"Letöltve ({done >> 20} MB)." + (" Ellenőrző összeg rendben." if sha256 else ""))


def op_deb(r):
    kind = r.get("kind")
    arch = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True).stdout.strip()
    os.makedirs("/var/cache/ciszterci-admin", exist_ok=True)
    dest = f"/var/cache/ciszterci-admin/{kind}.deb"
    sha = None
    if kind == "teamviewer":
        if arch not in ("amd64", "arm64", "armhf"):
            raise RuntimeError(f"A TeamViewer nem érhető el ehhez az architektúrához: {arch}")
        url = f"https://download.teamviewer.com/download/linux/teamviewer_{arch}.deb"
    elif kind == "rustdesk":
        suffix = {"amd64": "x86_64.deb", "arm64": "aarch64.deb", "armhf": "armv7-sciter.deb"}.get(arch)
        if not suffix:
            raise RuntimeError(f"A RustDesk nem érhető el ehhez az architektúrához: {arch}")
        api = urllib.request.Request("https://api.github.com/repos/rustdesk/rustdesk/releases/latest",
                                     headers={"User-Agent": "ciszterci-admin", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(api, timeout=30) as resp:
            rel = json.load(resp)
        asset = next((a for a in rel.get("assets", []) if a["name"].endswith("-" + suffix)), None)
        if not asset or not asset["browser_download_url"].startswith("https://github.com/rustdesk/rustdesk/releases/download/"):
            raise RuntimeError("Nem találom a RustDesk .deb csomagot a legfrissebb kiadásban.")
        url = asset["browser_download_url"]
        d = asset.get("digest") or ""
        sha = d.split(":", 1)[1] if d.startswith("sha256:") else None
        hlog(f"RustDesk verzió: {rel.get('tag_name', '?')}")
    else:
        raise RuntimeError("Ismeretlen csomag.")
    download(url, dest, sha)
    hrun(["apt-get", "update"], check=False)
    hrun(["apt-get", "install", "-y", dest])
    os.remove(dest)
    return "Telepítve."


def op_debremove(r):
    if r.get("kind") not in ("teamviewer", "rustdesk"):
        raise RuntimeError("Ismeretlen csomag.")
    hrun(["apt-get", "remove", "-y", r["kind"]])
    return "Eltávolítva."


HOST_RE = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


def op_chrony(r):
    servers = r.get("servers") or []
    if not servers or not all(HOST_RE.fullmatch(s) for s in servers):
        raise RuntimeError("Érvénytelen időszerver-lista.")
    hrun(["apt-get", "update"], check=False)
    hrun(["apt-get", "install", "-y", "chrony"])
    os.makedirs("/etc/chrony/sources.d", exist_ok=True)
    lines = [("pool" if "pool" in s else "server") + f" {s} iburst" for s in servers]
    put("/etc/chrony/sources.d/ciszterci.sources", "# Ciszterci Admin\n" + "\n".join(lines) + "\n", 0o644)
    conf = "/etc/chrony/chrony.conf"
    try:
        with open(conf, encoding="utf-8") as f:
            txt = f.read()
        if "sourcedir /etc/chrony/sources.d" not in txt:
            with open(conf, "a", encoding="utf-8") as f:
                f.write("\nsourcedir /etc/chrony/sources.d\n")
            hlog("A chrony.conf kiegészítve a sources.d könyvtárral.")
    except OSError:
        pass
    hrun(["systemctl", "enable", "chrony"])
    hrun(["systemctl", "restart", "chrony"])
    hrun(["chronyc", "reload", "sources"], check=False)
    time.sleep(2)
    hrun(["chronyc", "makestep"], check=False)
    return "Az internetes időszinkron be van állítva."


def op_chrony_ctl(r):
    if r.get("action") == "enable":
        hrun(["systemctl", "enable", "--now", "chrony"])
        return "Az internetes időszinkron bekapcsolva."
    if r.get("action") == "disable":
        hrun(["systemctl", "disable", "--now", "chrony"])
        return "Az internetes időszinkron kikapcsolva."
    raise RuntimeError("Ismeretlen művelet.")


def op_time(r):
    dt = r.get("datetime", "")
    try:
        datetime.datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise RuntimeError("Érvénytelen dátum/idő.")
    hrun(["systemctl", "stop", "chrony"], check=False)
    hrun(["timedatectl", "set-ntp", "false"], check=False)
    hrun(["timedatectl", "set-time", dt])
    return "Az idő beállítva. (Az internetes szinkron, ha be volt kapcsolva, újraindításkor visszaáll.)"


OPS = {"login": op_login, "pkg": op_pkg, "deb": op_deb, "debremove": op_debremove,
       "chrony": op_chrony, "chrony_ctl": op_chrony_ctl, "time": op_time}


def helper_main():
    for line in sys.stdin:
        try:
            req = json.loads(line)
            emit({"rc": 0, "msg": OPS[req["op"]](req) or "Kész."})
        except Exception as e:  # noqa: BLE001
            emit({"rc": 1, "msg": str(e)})


class Helper:
    def __init__(self):
        self.p = None

    def _start(self):
        if self.p is None or self.p.poll() is not None:
            self.p = subprocess.Popen(["pkexec", "/usr/bin/python3", INSTALL_PATH, "--helper"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8")

    def call(self, req, on_log=None):
        try:
            self._start()
            self.p.stdin.write(json.dumps(req) + "\n")
            self.p.stdin.flush()
            while True:
                line = self.p.stdout.readline()
                if not line:
                    return 126, "A hitelesítés megszakadt, vagy a segédfolyamat leállt."
                r = json.loads(line)
                if "log" in r:
                    if on_log:
                        on_log(r["log"])
                    continue
                return r["rc"], r["msg"]
        except (BrokenPipeError, OSError, ValueError) as e:
            return 126, f"A segédfolyamat nem érhető el: {e}"


# ------------------------------------------------------------------------ GUI
TERMINALS = [
    ("xfce4-terminal", lambda t, c: ["xfce4-terminal", "--title", t, "-x", "bash", "-c", c]),
    ("gnome-terminal", lambda t, c: ["gnome-terminal", "--title", t, "--", "bash", "-c", c]),
    ("konsole", lambda t, c: ["konsole", "-e", "bash", "-c", c]),
    ("xterm", lambda t, c: ["xterm", "-T", t, "-e", "bash", "-c", c]),
    ("x-terminal-emulator", lambda t, c: ["x-terminal-emulator", "-e", "bash", "-c", c]),
]
POSITIONS = [("Középen", "50%,center 50%,center"), ("Balra", "5%,start 50%,center"),
             ("Jobbra", "95%,end 50%,center"), ("Fent, középen", "50%,center 5%,start"),
             ("Lent, középen", "50%,center 95%,end")]
CLOCK_FORMATS = ["%H:%M", "%Y.%m.%d. %H:%M", "%A, %Y. %B %d., %H:%M", "%a %H:%M", "%H:%M:%S", "%I:%M %p"]
INDICATORS = [("~host", "Gépnév"), ("~clock", "Dátum és idő"), ("~session", "Munkamenet-választó"),
              ("~language", "Nyelvválasztó"), ("~a11y", "Akadálymentesítés"),
              ("~power", "Kikapcsolás / újraindítás menü")]


def svc_active(name):
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", name]).returncode == 0
    except FileNotFoundError:
        return False


def lightdm_hides_users():
    import glob
    val = None
    for p in [LIGHTDM_CONF] + sorted(glob.glob("/etc/lightdm/lightdm.conf.d/*.conf")):
        v = ini_get(p, "Seat:*").get("greeter-hide-users")
        if v is not None:
            val = v
    return str(val).lower() == "true"


def default_dm():
    try:
        with open("/etc/X11/default-display-manager") as f:
            return os.path.basename(f.read().strip()) or "ismeretlen"
    except OSError:
        return "ismeretlen"


def gui_main(helper=None, run=True):
    import gi
    import locale
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib, GdkPixbuf
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    GLib.set_prgname("ciszterci-admin")
    GLib.set_application_name("Ciszterci Admin")
    Gtk.Window.set_default_icon_name("ciszterci-admin")
    V, H = Gtk.Orientation.VERTICAL, Gtk.Orientation.HORIZONTAL

    class Win(Gtk.Window):
        def __init__(self, helper):
            super().__init__(title="Ciszterci Vezérlőpult")
            self.set_default_size(980, 720)
            self.connect("destroy", Gtk.main_quit)
            self.h = helper or Helper()
            self.busy = False
            self.pkgrows = []
            self.bg_path = None

            outer = Gtk.Box(orientation=V)
            self.add(outer)
            body = Gtk.Box(orientation=H)
            outer.pack_start(body, True, True, 0)
            self.side = Gtk.ListBox()
            self.side.set_size_request(240, -1)
            self.stack = Gtk.Stack()
            self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
            pages = [("Bejelentkező ablak", self.page_login), ("Távoli segítség", self.page_remote),
                     ("Felhő tárhely", self.page_cloud), ("Tartományba léptetés", self.page_domain),
                     ("Rendszeridő", self.page_time), ("Rendszer", self.page_system)]
            self.page_names = []
            for i, (title, builder) in enumerate(pages):
                row = Gtk.ListBoxRow()
                lab = Gtk.Label(label=title, xalign=0)
                lab.set_margin_top(12)
                lab.set_margin_bottom(12)
                lab.set_margin_start(16)
                row.add(lab)
                self.side.add(row)
                sw = Gtk.ScrolledWindow()
                sw.add(builder())
                self.stack.add_named(sw, f"p{i}")
                self.page_names.append(f"p{i}")
            self.side.connect("row-selected", self.on_row)
            body.pack_start(self.side, False, False, 0)
            body.pack_start(Gtk.Separator(orientation=H), False, False, 0)
            body.pack_start(self.stack, True, True, 0)

            bottom = Gtk.Box(orientation=V, spacing=4)
            bottom.set_border_width(6)
            self.progress = Gtk.ProgressBar()
            self.status = Gtk.Label(xalign=0)
            self.status.set_line_wrap(True)
            self.logview = Gtk.TextView(editable=False, monospace=True)
            lsw = Gtk.ScrolledWindow()
            lsw.set_min_content_height(130)
            lsw.add(self.logview)
            self.expander = Gtk.Expander(label="Napló")
            self.expander.add(lsw)
            for w in (self.progress, self.status, self.expander):
                bottom.pack_start(w, False, False, 0)
            outer.pack_start(Gtk.Separator(), False, False, 0)
            outer.pack_start(bottom, False, False, 0)
            self.show_all()
            self.progress.hide()
            self.side.select_row(self.side.get_row_at_index(0))
            self.refresh_status()

        # ---------------------------------------------------------- segédek
        def on_row(self, _lb, row):
            if row is not None:
                self.stack.set_visible_child_name(self.page_names[row.get_index()])

        def mk_page(self, title, sub=""):
            box = Gtk.Box(orientation=V, spacing=8)
            box.set_border_width(18)
            t = Gtk.Label(xalign=0)
            t.set_markup(f"<span size='x-large' weight='bold'>{title}</span>")
            box.pack_start(t, False, False, 0)
            if sub:
                box.pack_start(self.lab(sub), False, False, 0)
            box.pack_start(Gtk.Separator(), False, False, 6)
            return box

        def lab(self, text):
            l = Gtk.Label(label=text, xalign=0)
            l.set_line_wrap(True)
            return l

        def head(self, box, text):
            l = Gtk.Label(xalign=0)
            l.set_markup(f"<b>{text}</b>")
            l.set_margin_top(10)
            box.pack_start(l, False, False, 2)

        def btn(self, text, cb):
            b = Gtk.Button(label=text)
            b.connect("clicked", cb)
            return b

        def say(self, rc, msg):
            self.status.set_text(("✔ " if rc == 0 else "✖ ") + msg)

        def log(self, msg):
            buf = self.logview.get_buffer()
            buf.insert(buf.get_end_iter(), msg + "\n")
            mark = buf.create_mark(None, buf.get_end_iter(), False)
            self.logview.scroll_mark_onscreen(mark)
            if self.busy and msg.strip():
                self.status.set_text(msg.strip()[:160])
            return False

        def confirm(self, text):
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.OK_CANCEL, text=text)
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            return ok

        def run_task(self, steps):
            if self.busy:
                return
            self.busy = True
            self.stack.set_sensitive(False)
            self.progress.show()
            self.status.set_text("Folyamatban… (hitelesítést kérhet)")
            GLib.timeout_add(120, self.pulse)

            def worker():
                rc, msg = 0, ""
                for op, params in steps:
                    rc, msg = self.h.call(dict(params, op=op), on_log=lambda m: GLib.idle_add(self.log, m))
                    if rc != 0:
                        break
                GLib.idle_add(self.task_done, rc, msg)
            threading.Thread(target=worker, daemon=True).start()

        def pulse(self):
            if self.busy:
                self.progress.pulse()
            return self.busy

        def task_done(self, rc, msg):
            self.busy = False
            self.progress.hide()
            self.stack.set_sensitive(True)
            self.log(("OK: " if rc == 0 else "HIBA: ") + msg)
            if rc != 0:
                self.expander.set_expanded(True)
            self.say(rc, msg)
            self.refresh_status()
            return False

        def run_terminal(self, title, path):
            if not os.path.exists(path):
                self.say(1, f"Hiányzik a script: {path}")
                return
            # A pkexec közvetlenül a scriptet indítva Permission denied hibát
            # adhat, ha azon nincs végrehajtási bit. A bash-t indítjuk rootként,
            # a scriptet pedig argumentumként adjuk át.
            cmd = (f'pkexec /bin/bash -- {shlex.quote(path)}; rc=$?; echo; '
                   f'echo "[Kilépési kód: $rc]"; '
                   'read -rp "Nyomj Entert a bezáráshoz… " _')
            for term, build in TERMINALS:
                if shutil.which(term):
                    subprocess.Popen(build(title, cmd), start_new_session=True)
                    self.say(0, f"Terminál megnyitva: {title} (a jelszót ott kéri a rendszer).")
                    return
            self.say(1, "Nem találok terminál-emulátort (xfce4-terminal, xterm…).")

        def pkg_row(self, box, title, desc, pkg, inst_steps, rm_steps):
            row = Gtk.Box(spacing=10)
            left = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(xalign=0)
            t.set_markup(f"<b>{title}</b>")
            st = Gtk.Label(xalign=0)
            for w in (t, self.lab(desc), st):
                left.pack_start(w, False, False, 0)
            bi = self.btn("Telepítés", lambda *_: self.run_task(inst_steps))
            br = self.btn("Eltávolítás",
                          lambda *_: self.confirm(f"Eltávolítod: {title}?") and self.run_task(rm_steps))
            row.pack_start(left, True, True, 0)
            row.pack_start(bi, False, False, 0)
            row.pack_start(br, False, False, 0)
            box.pack_start(row, False, False, 6)
            box.pack_start(Gtk.Separator(), False, False, 4)
            self.pkgrows.append((st, pkg, bi, br))

        def script_row(self, box, title, desc, key, button, confirm_text=None):
            path = SCRIPTS[key]
            row = Gtk.Box(spacing=10)
            left = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(xalign=0)
            t.set_markup(f"<b>{title}</b>")
            left.pack_start(t, False, False, 0)
            left.pack_start(self.lab(desc), False, False, 0)
            exists = os.path.exists(path)
            left.pack_start(self.lab(path if exists else f"Hiányzik: {path}"), False, False, 0)

            def go(*_):
                if confirm_text is None or self.confirm(confirm_text):
                    self.run_terminal(title, path)
            b = self.btn(button, go)
            b.set_sensitive(exists)
            row.pack_start(left, True, True, 0)
            row.pack_start(b, False, False, 0)
            box.pack_start(row, False, False, 6)
            box.pack_start(Gtk.Separator(), False, False, 4)

        def stub_row(self, box, title, desc):
            row = Gtk.Box(spacing=10)
            left = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(xalign=0)
            t.set_markup(f"<b>{title}</b>")
            left.pack_start(t, False, False, 0)
            left.pack_start(self.lab(desc), False, False, 0)
            b = Gtk.Button(label="Hamarosan")
            b.set_sensitive(False)
            row.pack_start(left, True, True, 0)
            row.pack_start(b, False, False, 0)
            box.pack_start(row, False, False, 6)
            box.pack_start(Gtk.Separator(), False, False, 4)

        def refresh_status(self):
            for st, pkg, bi, br in self.pkgrows:
                ok = pkg_ok(pkg)
                st.set_markup('<span foreground="#15803d">● telepítve</span>' if ok
                              else '<span foreground="#b45309">○ nincs telepítve</span>')
                bi.set_sensitive(not ok)
                br.set_sensitive(ok)
            if hasattr(self, "chrony_lbl"):
                self.chrony_lbl.set_text(self.chrony_state())

        # ------------------------------------------------ Bejelentkező ablak
        def page_login(self):
            b = self.mk_page("Bejelentkező ablak beállítása",
                             "A LightDM (GTK greeter) képernyőjét állítja. A változás a következő "
                             "bejelentkező képernyőnél lép életbe (kijelentkezés után).")
            usable = pkg_ok("lightdm-gtk-greeter") and os.path.isdir("/etc/lightdm")
            if not usable:
                b.pack_start(self.lab(f"⚠ Ez a modul a LightDM + GTK greeter párosra készült "
                                      f"(aktív bejelentkezéskezelő: {default_dm()}); itt nem használható."),
                             False, False, 0)
            conf = ini_get(GREETER_CONF, "greeter")
            ap = self.btn("Alkalmaz", self.apply_login)
            ap.set_halign(Gtk.Align.START)
            b.pack_start(ap, False, False, 0)

            self.head(b, "Felhasználók")
            self.c_hide = Gtk.CheckButton(label="Felhasználónevek elrejtése (a nevet be kell gépelni)")
            self.c_hide.set_active(lightdm_hides_users())
            b.pack_start(self.c_hide, False, False, 0)

            self.head(b, "Fejléc (felső sáv)")
            g = Gtk.Grid(column_spacing=10, row_spacing=6)
            g.attach(Gtk.Label(label="Dátum/idő formátum:", xalign=1), 0, 0, 1, 1)
            self.cb_clock = Gtk.ComboBoxText()
            for f in CLOCK_FORMATS:
                self.cb_clock.append(f, f"{time.strftime(f)}    [{f}]")
            self.cb_clock.connect("changed", lambda c: self.e_clock.set_text(c.get_active_id() or ""))
            g.attach(self.cb_clock, 1, 0, 1, 1)
            g.attach(Gtk.Label(label="Egyéni (strftime):", xalign=1), 0, 1, 1, 1)
            self.e_clock = Gtk.Entry()
            self.e_clock.set_text(conf.get("clock-format", "%a, %H:%M"))
            self.clock_prev = Gtk.Label(xalign=0)
            self.e_clock.connect("changed", self.on_clock_changed)
            g.attach(self.e_clock, 1, 1, 1, 1)
            g.attach(Gtk.Label(label="Előnézet:", xalign=1), 0, 2, 1, 1)
            g.attach(self.clock_prev, 1, 2, 1, 1)
            g.attach(Gtk.Label(label="Sáv helye:", xalign=1), 0, 3, 1, 1)
            self.cb_panel = Gtk.ComboBoxText()
            self.cb_panel.append("top", "Fent")
            self.cb_panel.append("bottom", "Lent")
            self.cb_panel.set_active_id(conf.get("panel-position", "top"))
            g.attach(self.cb_panel, 1, 3, 1, 1)
            b.pack_start(g, False, False, 0)
            self.on_clock_changed(self.e_clock)
            b.pack_start(self.lab("A sávban megjelenő elemek:"), False, False, 4)
            cur = conf.get("indicators")
            toks = set(cur.split(";")) if cur else {t for t, _n in INDICATORS}
            self.ind = {}
            fg = Gtk.Grid(column_spacing=18, row_spacing=2)
            for i, (tok, name) in enumerate(INDICATORS):
                c = Gtk.CheckButton(label=name)
                c.set_active(tok in toks)
                self.ind[tok] = c
                fg.attach(c, i % 2, i // 2, 1, 1)
            b.pack_start(fg, False, False, 0)

            self.head(b, "Bejelentkező doboz helye")
            self.cb_pos = Gtk.ComboBoxText()
            for name, val in POSITIONS:
                self.cb_pos.append(val, name)
            curpos = conf.get("position", POSITIONS[0][1])
            if curpos not in [v for _n, v in POSITIONS]:
                self.cb_pos.append(curpos, f"Egyéni: {curpos}")
            self.cb_pos.set_active_id(curpos)
            b.pack_start(self.cb_pos, False, False, 0)

            self.head(b, "Háttérkép")
            row = Gtk.Box(spacing=8)
            self.fc = Gtk.FileChooserButton(title="Háttérkép kiválasztása", action=Gtk.FileChooserAction.OPEN)
            flt = Gtk.FileFilter()
            flt.set_name("Képek (PNG, JPEG, BMP)")
            for pat in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
                flt.add_pattern(pat)
            self.fc.add_filter(flt)
            self.fc.connect("file-set", self.on_bg_chosen)
            self.c_bgreset = Gtk.CheckButton(label="Alapértelmezett háttér")
            self.c_bgreset.connect("toggled", lambda *_: self.c_bgreset.get_active() and self.set_preview(None))
            row.pack_start(self.fc, False, False, 0)
            row.pack_start(self.c_bgreset, False, False, 0)
            b.pack_start(row, False, False, 0)
            self.bg_img = Gtk.Image()
            b.pack_start(self.bg_img, False, False, 4)
            curbg = conf.get("background")
            if curbg and os.path.isfile(curbg):
                self.set_preview(curbg)
            self.login_widgets = [w for w in (self.c_hide, self.cb_clock, self.e_clock, self.cb_panel,
                                              self.cb_pos, self.fc, self.c_bgreset, ap, fg)]
            for w in self.login_widgets:
                w.set_sensitive(usable)
            return b

        def on_clock_changed(self, entry):
            try:
                self.clock_prev.set_text(time.strftime(entry.get_text()))
            except ValueError:
                self.clock_prev.set_text("(érvénytelen formátum)")

        def set_preview(self, path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 360, 200, True) if path else None
            except GLib.Error:
                pb = None
            self.bg_img.set_from_pixbuf(pb)

        def on_bg_chosen(self, fc):
            self.bg_path = fc.get_filename()
            self.c_bgreset.set_active(False)
            self.set_preview(self.bg_path)

        def build_indicators(self):
            on = {t: c.get_active() for t, c in self.ind.items()}
            parts = []
            if on["~host"]:
                parts.append("~host")
            parts.append("~spacer")
            if on["~clock"]:
                parts.append("~clock")
            parts.append("~spacer")
            parts += [t for t in ("~session", "~language", "~a11y", "~power") if on[t]]
            return ";".join(parts)

        def login_params(self):
            bg = None
            if self.c_bgreset.get_active():
                bg = {"reset": True}
            elif self.bg_path:
                bg = {"src": self.bg_path}
            pos = self.cb_pos.get_active_id()
            return {"hide_users": self.c_hide.get_active(),
                    "clock_format": self.e_clock.get_text().strip() or None,
                    "indicators": self.build_indicators(),
                    "panel_position": self.cb_panel.get_active_id(),
                    "position": pos if pos and POSITION_RE.fullmatch(pos) else None,
                    "bg": bg}

        def apply_login(self, *_):
            self.run_task([("login", self.login_params())])

        # ------------------------------------------------- Távoli segítség
        def page_remote(self):
            b = self.mk_page("Távoli segítség", "Programok, amelyekkel egy rendszergazda távolról segíthet.")
            self.pkg_row(b, "TeamViewer",
                         "A hivatalos teamviewer.com Debian-csomagot tölti le és telepíti az apt-tal.",
                         "teamviewer", [("deb", {"kind": "teamviewer"})], [("debremove", {"kind": "teamviewer"})])
            self.pkg_row(b, "RustDesk",
                         "A GitHub legfrissebb hivatalos kiadását tölti le (az ellenőrző összeget ellenőrzi, "
                         "ha a kiadás tartalmazza).",
                         "rustdesk", [("deb", {"kind": "rustdesk"})], [("debremove", {"kind": "rustdesk"})])
            return b

        # ------------------------------------------------------ Felhő tárhely
        def page_cloud(self):
            b = self.mk_page("Felhő tárhely")
            self.pkg_row(b, "Nextcloud kliens", "A nextcloud-desktop csomag (Debian-tárolóból).",
                         "nextcloud-desktop", [("pkg", {"action": "install", "pkgs": ["nextcloud-desktop"]})],
                         [("pkg", {"action": "remove", "pkgs": ["nextcloud-desktop"]})])
            return b

        # ------------------------------------------------ Tartományba léptetés
        def page_domain(self):
            b = self.mk_page("Tartományba léptetés",
                             "A műveletek terminálban futnak, rendszergazdai jelszót kér a rendszer.")
            self.script_row(b, "Belépés SAMBA-DC tartományba",
                            "A meglévő linux-ad-member.sh futtatása.", "ad_join", "Tartományba lépés")
            self.script_row(b, "Kilépés a SAMBA-DC tartományból",
                            "A tartománytagság és a beléptetéskor létrehozott helyi beállítások eltávolítása.",
                            "ad_leave", "Kilépés a tartományból",
                            "Biztosan kilépteted ezt a gépet a samba.crnl.lan tartományból?")
            return b

        # ----------------------------------------------------------- Rendszeridő
        def chrony_state(self):
            if not pkg_ok("chrony"):
                return "A chrony nincs telepítve."
            act = "fut" if svc_active("chrony") else "nem fut"
            try:
                sync = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                                      capture_output=True, text=True).stdout.strip()
            except FileNotFoundError:
                sync = ""
            return f"chrony: telepítve, {act}; szinkronban: {'igen' if sync == 'yes' else 'nem/ismeretlen'}"

        def page_time(self):
            b = self.mk_page("Rendszeridő")
            self.head(b, "Internetes idő szinkron (chrony)")
            self.chrony_lbl = self.lab("")
            b.pack_start(self.chrony_lbl, False, False, 0)
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Label(label="Időszerver(ek):"), False, False, 0)
            self.e_ntp = Gtk.Entry()
            self.e_ntp.set_text("hu.pool.ntp.org")
            self.e_ntp.set_width_chars(34)
            row.pack_start(self.e_ntp, False, False, 0)
            b.pack_start(row, False, False, 0)
            b.pack_start(self.lab("Több szervert szóközzel vagy vesszővel válassz el. A Debian alap "
                                  "időszerverei tartalékként megmaradnak."), False, False, 0)
            r2 = Gtk.Box(spacing=8)
            r2.pack_start(self.btn("Telepítés és bekapcsolás", self.on_chrony_install), False, False, 0)
            r2.pack_start(self.btn("Kikapcsolás",
                                   lambda *_: self.run_task([("chrony_ctl", {"action": "disable"})])), False, False, 0)
            r2.pack_start(self.btn("Bekapcsolás",
                                   lambda *_: self.run_task([("chrony_ctl", {"action": "enable"})])), False, False, 0)
            b.pack_start(r2, False, False, 4)

            self.head(b, "Kézi beállítás")
            self.cal = Gtk.Calendar()
            b.pack_start(self.cal, False, False, 0)
            tr = Gtk.Box(spacing=6)
            self.sp = [Gtk.SpinButton.new_with_range(0, mx, 1) for mx in (23, 59, 59)]
            for i, s in enumerate(self.sp):
                s.set_width_chars(2)
                s.set_numeric(True)
                s.connect("output", lambda sp: (sp.set_text(f"{int(sp.get_value()):02d}"), True)[1])
                tr.pack_start(s, False, False, 0)
                if i < 2:
                    tr.pack_start(Gtk.Label(label=":"), False, False, 0)
            tr.pack_start(self.btn("Mostani idő betöltése", lambda *_: self.load_now()), False, False, 8)
            b.pack_start(tr, False, False, 4)
            b.pack_start(self.btn("Idő beállítása", self.on_set_time), False, False, 4)
            b.pack_start(self.lab("A kézi beállítás leállítja a chrony-t, hogy ne írja felül az időt."),
                         False, False, 0)
            self.load_now()
            return b

        def load_now(self):
            n = datetime.datetime.now()
            self.cal.select_month(n.month - 1, n.year)
            self.cal.select_day(n.day)
            for s, v in zip(self.sp, (n.hour, n.minute, n.second)):
                s.set_value(v)

        def on_chrony_install(self, *_):
            servers = [s for s in re.split(r"[\s,;]+", self.e_ntp.get_text().strip()) if s]
            if not servers or not all(HOST_RE.fullmatch(s) for s in servers):
                self.say(1, "Érvénytelen időszerver-név.")
                return
            self.run_task([("chrony", {"servers": servers})])

        def on_set_time(self, *_):
            y, m, d = self.cal.get_date()
            h, mi, s = (int(x.get_value()) for x in self.sp)
            dt = f"{y:04d}-{m + 1:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
            if self.confirm(f"A rendszeridő beállítása: {dt}\nA chrony leáll. Folytatod?"):
                self.run_task([("time", {"datetime": dt})])

        # --------------------------------------------------------------- Rendszer
        def page_system(self):
            b = self.mk_page("Rendszer", "A műveletek terminálban futnak, rendszergazdai jelszót kér a rendszer.")
            self.script_row(b, "Rendszergazdai eszközök telepítése",
                            "A meglévő add-admin-tools.sh futtatása.", "admin_tools", "Indítás terminálban")
            self.script_row(b, "Rendszergazdai eszközök eltávolítása",
                            "Az add-admin-tools.sh által telepített csomagok és WinBox eltávolítása.",
                            "remove_admin_tools", "Eltávolítás",
                            "Eltávolítod a rendszergazdai eszközöket és a WinBoxot?")
            self.script_row(b, "Szükségtelen kernelek törlése",
                            "A meglévő old-kernel-remover futtatása.", "old_kernels", "Indítás terminálban",
                            "Törlöd a régi, már nem használt kerneleket?")
            return b

    win = Win(helper)
    if run:
        Gtk.main()
    return win


# ------------------------------------------------------------- belépési pont
def main():
    a = sys.argv[1:]
    if "--helper" in a:
        helper_main()
        return
    if a[:1] == ["--install"]:
        sys.exit(install_main(a[1] if len(a) > 1 else INSTALL_PATH))
    if "--uninstall" in a:
        sys.exit(uninstall_main() if os.geteuid() == 0 else run_elevated(["--uninstall"]))
    me = os.path.realpath(__file__)
    if os.geteuid() == 0:
        rc = install_main(me)
        print("Kész. Normál felhasználóként indítsd: ciszterci-admin (vagy az alkalmazásmenüből).")
        sys.exit(rc)
    tried = os.environ.get("KOLIBRI_TRIED") == "1"
    if me != INSTALL_PATH:
        if not (self_installed() and same_file(me, INSTALL_PATH) and deps_ok()):
            note("Első indítás: függőségek telepítése és beépülés a rendszerbe…")
            if run_elevated(["--install", me]) != 0:
                sys.exit(f"A telepítés nem sikerült. Részletek: {LOG}")
        os.environ["KOLIBRI_TRIED"] = "1"
        os.execv(sys.executable, [sys.executable, INSTALL_PATH] + a)
    if not deps_ok():
        if tried:
            sys.exit(f"Hiányzó függőség a telepítés után is. Részletek: {LOG}")
        note("Hiányzó függőségek pótlása…")
        if run_elevated(["--install", me]) != 0:
            sys.exit(f"A telepítés nem sikerült. Részletek: {LOG}")
        os.environ["KOLIBRI_TRIED"] = "1"
        os.execv(sys.executable, [sys.executable, INSTALL_PATH] + a)
    gui_main()


if __name__ == "__main__":
    main()
