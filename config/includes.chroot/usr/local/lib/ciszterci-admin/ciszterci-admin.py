#!/usr/bin/env python3
"""Ciszterci Admin – YaST-szerű vezérlőpult (GTK3) egyszerű felhasználóknak.

Első indításkor (python3 ciszterci-admin.py) telepíti, amire szüksége van, beépül a rendszerbe
(/usr/local/bin/ciszterci-admin, alkalmazásmenü: Rendszer › Ciszterci Admin), majd újraindul.
A jogosultságot pkexec adja: egyetlen hitelesítés után egy szűk műveletkészletű root segéd
dolgozik (nem tetszőleges parancsokat futtat). Eltávolítás: ciszterci-admin --uninstall
"""
import sys, os, json, re, shlex, subprocess, shutil, hashlib, time, threading, urllib.request, datetime
import base64, ipaddress, pwd, grp

LIBDIR = "/usr/local/lib/ciszterci-admin"
INSTALL_PATH = LIBDIR + "/ciszterci-admin.py"      # root tulajdonú példány, ezt futtatja a pkexec
BIN_PATH = "/usr/local/bin/ciszterci-admin"
DESKTOP_PATH = "/usr/share/applications/ciszterci-admin.desktop"
ICON_PATH = "/usr/share/icons/hicolor/scalable/apps/ciszterci-admin.svg"
LOG = "/var/log/ciszterci-admin-install.log"
APP_NAME = os.path.basename(LIBDIR)                  # az alkalmazás neve (a LIBDIR utolsó eleme)
APP_TITLE = APP_NAME.replace("-", " ").title()
VPN_GROUP = "vpn"                                    # tagjai jelszó nélkül kapcsolhatják a VPN-t
VPN_HELPER = LIBDIR + "/vpn-helper"                  # szűk root segéd: csak wg_list / wg_up / wg_down
POLKIT_ID = "hu." + APP_NAME.replace("-", ".") + ".vpn"
POLKIT_POLICY = f"/usr/share/polkit-1/actions/{POLKIT_ID}.policy"
POLKIT_RULE = f"/etc/polkit-1/rules.d/49-{APP_NAME}-vpn.rules"
REQUIRED = ["python3", "python3-gi", "gir1.2-gtk-3.0", "pkexec"]
POLKIT_AGENTS = ["policykit-1-gnome", "polkit-1-gnome", "xfce-polkit", "lxpolkit"]

GREETER_CONF = "/etc/lightdm/lightdm-gtk-greeter.conf"
LIGHTDM_CONF = "/etc/lightdm/lightdm.conf"
LIGHTDM_DROPIN = "/etc/lightdm/lightdm.conf.d/99-ciszterci-admin.conf"
BG_DIR = "/usr/share/backgrounds/ciszterci"
SCRIPTS = {
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


# ------------------------------------- jelszó nélküli VPN (vpn csoport + polkit)
def vpn_helper_script():
    """A pkexec-kel indított szűk segéd: a fő program moduljából csak a vpn_helper_main()-t hívja."""
    return ("#!/usr/bin/python3 -I\n"
            f"# {APP_TITLE}: szűk jogosultságú VPN-segéd. A polkit-szabály a(z) '{VPN_GROUP}' csoport tagjainak\n"
            "# jelszó nélkül engedi; csak a wg_list / wg_up / wg_down műveletet hajtja végre.\n"
            "import importlib.util\n"
            f"spec = importlib.util.spec_from_file_location(\"admin_core\", {INSTALL_PATH!r})\n"
            "core = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(core)\n"
            "core.vpn_helper_main()\n")


def vpn_policy_xml():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1.0/policyconfig.dtd">
<policyconfig>
  <vendor>{APP_TITLE}</vendor>
  <action id="{POLKIT_ID}">
    <description>VPN (WireGuard) ki/be kapcsolása</description>
    <message>A VPN kapcsolásához hitelesítés szükséges</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">{VPN_HELPER}</annotate>
  </action>
</policyconfig>
"""


def vpn_rule_js():
    return (f"// {APP_TITLE}: a '{VPN_GROUP}' csoport tagjai jelszó nélkül kapcsolhatják a VPN-t\n"
            "polkit.addRule(function(action, subject) {\n"
            f'    if (action.id == "{POLKIT_ID}" && subject.isInGroup("{VPN_GROUP}")) {{\n'
            "        return polkit.Result.YES;\n"
            "    }\n"
            "});\n")


def invoking_user():
    """Az a felhasználó, aki a telepítést (sudo-val vagy pkexec-kel) elindította."""
    u = os.environ.get("SUDO_USER")
    if not u and os.environ.get("PKEXEC_UID", "").isdigit():
        try:
            u = pwd.getpwuid(int(os.environ["PKEXEC_UID"])).pw_name
        except KeyError:
            u = None
    return u if u and u != "root" else None


def vpn_group_setup(user=None, log=None):
    """A vpn csoport létrehozása (ha kell) és a felhasználó felvétele. A root segédből hlog-gal hívjuk,
    mert az ilog stdoutra írna, ami ott a JSON-protokoll csatornája. True: a felhasználó tag lett."""
    log = log or ilog
    if subprocess.run(["getent", "group", VPN_GROUP], capture_output=True).returncode != 0:
        if sh(["groupadd", "-r", VPN_GROUP]) != 0:
            log(f"HIBA: a(z) {VPN_GROUP} csoport létrehozása nem sikerült (részletek: {LOG}).")
            return False
        log(f"A(z) {VPN_GROUP} csoport létrehozva.")
    if not user:
        log(f"Figyelem: nem derült ki, melyik felhasználót vegyem fel a(z) {VPN_GROUP} csoportba. "
            f"Pótlás: {APP_NAME} --vpn-user FELHASZNÁLÓ")
        return False
    try:
        pwd.getpwnam(user)
    except KeyError:
        log(f"HIBA: nincs ilyen felhasználó: {user}")
        return False
    if sh(["usermod", "-aG", VPN_GROUP, user]) != 0:
        log(f"HIBA: {user} hozzáadása a(z) {VPN_GROUP} csoporthoz nem sikerült (részletek: {LOG}).")
        return False
    log(f"{user} hozzáadva a(z) {VPN_GROUP} csoporthoz: a VPN jelszó nélkül kapcsolható.")
    return True


def vpn_files_install():
    put(VPN_HELPER, vpn_helper_script(), 0o755)
    put(POLKIT_POLICY, vpn_policy_xml(), 0o644)
    put(POLKIT_RULE, vpn_rule_js(), 0o644)


def vpn_first_setup():
    """Új profil létrehozásakor/importálásakor (root segéd): szűk segéd + polkit-szabály, vpn csoport,
    és az adott felhasználó felvétele. Hiba esetén a profil mentése attól még sikeres."""
    try:
        vpn_files_install()
        user = invoking_user()
        if vpn_group_setup(user, hlog):
            return f" A(z) {user} a(z) {VPN_GROUP} csoport tagja lett: a VPN innentől jelszó nélkül kapcsolható."
    except Exception as e:  # noqa: BLE001
        hlog(f"Figyelem: a jelszó nélküli VPN beállítása nem sikerült: {e}")
    return ""


def vpn_user_main(user):
    vpn_files_install()
    if not vpn_group_setup(user):
        return 1
    print(f"Kész: {user} a(z) {VPN_GROUP} csoport tagja.")
    return 0


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
    for p in (BIN_PATH, DESKTOP_PATH, ICON_PATH, POLKIT_POLICY, POLKIT_RULE):
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


def hrun(cmd, check=True, stdin_text=None):
    """Parancs futtatása a segédben. A stdin_text (pl. jelszó) a gyerekfolyamat stdin-jére megy, és nem kerül naplóba."""
    hlog("$ " + " ".join(cmd))
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C.UTF-8")
    p = subprocess.Popen(cmd, stdin=(subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    if stdin_text is not None:
        try:
            p.stdin.write(stdin_text + "\n")
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
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


PKG_WHITELIST = {"chrony", "nextcloud-desktop", "wireguard-tools"}


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


# ------------------------------------------------------- Tartományba léptetés (AD / Samba DC)
# realmd + adcli + SSSD. A belépés a root segédben fut: ellenőrzött mezőket kap (gépnév, tartomány,
# felhasználó, jelszó), a jelszót a realm join stdin-jén keresztül adja át, és nem naplózza.
AD_HOST_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,13}[a-z0-9])?")                 # NetBIOS-korlát: max. 15
AD_DOM_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
AD_USER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
AD_PKGS = ["realmd", "sssd", "sssd-ad", "sssd-tools", "libnss-sss", "libpam-sss", "adcli",
           "samba-common-bin", "krb5-user", "libpam-modules", "sudo"]
# Kilépés után eltávolított csomagok (a libpam-modules lényeges rendszercsomag, azt nem töröljük)
AD_PURGE_PKGS = ["realmd", "sssd", "sssd-ad", "sssd-tools", "libnss-sss", "libpam-sss",
                 "adcli", "samba-common-bin", "krb5-user"]
SSSD_CONF = "/etc/sssd/sssd.conf"
AD_SUDOERS = "/etc/sudoers.d/ad-admins"
AD_MKHOME_PROFILE = "/usr/share/pam-configs/mkhomedir"


AD_DIAG = ""          # a legutóbbi állapotlekérdezés diagnosztikája (a GUI a Naplóba írja)


def ad_krb5_realm():
    """A /etc/krb5.conf default_realm értéke (a fájl mindenki számára olvasható)."""
    try:
        with open("/etc/krb5.conf", encoding="utf-8", errors="replace") as f:
            m = re.search(r"^\s*default_realm\s*=\s*(\S+)", f.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def ad_info():
    """A gép tartományi állapota; None, ha nincs tartományban.
    Elsődleges forrás: `realm list`. Ha az nem futtatható vagy hibával tér vissza (pl. normál felhasználóként
    nincs D-Bus/polkit jogosultság), tartalék: nem üres gépi kulcstábla + Kerberos realm a krb5.conf-ban."""
    global AD_DIAG
    AD_DIAG = ""
    if have("realm"):
        try:
            p = subprocess.run(["realm", "list"], capture_output=True, text=True, timeout=30,
                               env=dict(os.environ, LC_ALL="C.UTF-8"))
        except (OSError, subprocess.TimeoutExpired) as e:
            AD_DIAG = f"realm list nem futtatható: {e}"
        else:
            if p.returncode == 0:
                if re.search(r"^\s*configured:\s*kerberos-member", p.stdout, re.M):
                    m = re.search(r"^\s*domain-name:\s*(\S+)", p.stdout, re.M)
                    return {"domain": (m.group(1) if m else "ismeretlen").lower()}
                AD_DIAG = f"realm list: nincs tartomány (kimenet: {p.stdout.strip()[:200]!r})"
                return None
            AD_DIAG = (f"realm list hibakód: {p.returncode}; stderr: {p.stderr.strip()[:200]!r}; "
                       f"stdout: {p.stdout.strip()[:200]!r}")
    else:
        AD_DIAG = "a realm parancs nincs telepítve"
    realm = ad_krb5_realm()
    try:
        keytab = os.path.getsize("/etc/krb5.keytab") > 8
    except OSError:
        keytab = False
    if realm and keytab:
        AD_DIAG += " | tartalék: a gépi kulcstábla és a krb5.conf alapján tagnak tűnik"
        return {"domain": realm.lower()}
    return None


def ad_clean(v, need_login=True, need_host=True):
    """Bemenet ellenőrzése és tisztítása (a GUI és a segéd is ezt használja)."""
    host = (v.get("host") or "").strip().lower()
    dom = (v.get("domain") or "").strip().lower()
    user = (v.get("user") or "").strip().split("@")[0]
    pw = v.get("password") or ""
    if need_host and not AD_HOST_RE.fullmatch(host):
        raise RuntimeError("Érvénytelen gépnév: legfeljebb 15 karakter, csak kisbetű, szám és kötőjel "
                           "lehet, kötőjellel nem kezdődhet és nem végződhet.")
    if not AD_DOM_RE.fullmatch(dom):
        raise RuntimeError("Érvénytelen tartománynév (pl. samba.lan).")
    if need_login:
        if not AD_USER_RE.fullmatch(user):
            raise RuntimeError("Add meg a tartományi felhasználónevet (domain nélkül, pl. mszabi).")
        if not pw or "\n" in pw or "\r" in pw or len(pw) > 256:
            raise RuntimeError("Add meg a tartományi felhasználó jelszavát.")
    return {"host": host, "domain": dom, "user": user, "password": pw, "sudo": bool(v.get("sudo"))}


def ad_sssd_section(path=SSSD_CONF):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*\[(domain/[^\]]+)\]", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None


def ad_fix_nsswitch(path="/etc/nsswitch.conf"):
    """A winbind kivétele a passwd/group sorokból, az sss biztosítása (passwd, group, shadow)."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = []
    for line in lines:
        m = re.match(r"^(passwd|group|shadow):(.*)$", line)
        if m:
            toks = m.group(2).split()
            if m.group(1) in ("passwd", "group"):
                toks = [t for t in toks if t != "winbind"]
            if "sss" not in toks:
                toks.append("sss")
            line = f"{m.group(1)}:".ljust(16) + " ".join(toks)
        out.append(line)
    put(path, "\n".join(out) + "\n", 0o644)


def ad_clear_sss_cache():
    import glob
    for pat in ("/var/lib/sss/db/*", "/var/lib/sss/mc/*"):
        for p in glob.glob(pat):
            try:
                os.remove(p)
            except OSError:
                pass


def op_ad_join(r):
    v = ad_clean(r)
    host, dom, user, pw = v["host"], v["domain"], v["user"], v["password"]
    realm, fqdn = dom.upper(), f"{host}.{dom}"
    if ad_info():
        raise RuntimeError("A gép már tagja egy tartománynak. Előbb lépj ki belőle.")

    hlog("[1/9] Csomagok telepítése…")
    hrun(["apt-get", "update"], check=False)
    hrun(["apt-get", "install", "-y"] + AD_PKGS)

    hlog("[2/9] Gépnév és /etc/hosts beállítása…")
    hrun(["hostnamectl", "set-hostname", fqdn])
    try:
        with open("/etc/hosts", encoding="utf-8") as f:
            hl = [l for l in f.read().splitlines() if not re.match(r"^127\.0\.1\.1\s", l)]
    except OSError:
        hl = ["127.0.0.1 localhost"]
    hl.append(f"127.0.1.1 {fqdn} {host}")
    put("/etc/hosts", "\n".join(hl) + "\n", 0o644)
    hrun(["timedatectl", "set-ntp", "true"], check=False)

    hlog("[3/9] DNS ellenőrzése és Kerberos beállítása…")
    if subprocess.run(["getent", "hosts", dom], stdout=subprocess.DEVNULL).returncode != 0:
        raise RuntimeError(f"A(z) {dom} nem oldható fel. A gép DNS-szervere a Samba DC legyen.")
    if os.path.exists("/etc/krb5.conf") and not os.path.exists("/etc/krb5.conf.bak-ad"):
        shutil.copy2("/etc/krb5.conf", "/etc/krb5.conf.bak-ad")
    put("/etc/krb5.conf",
        f"[libdefaults]\n    default_realm = {realm}\n    dns_lookup_realm = false\n"
        "    dns_lookup_kdc = true\n    rdns = false\n    forwardable = true\n"
        "    ticket_lifetime = 24h\n    renew_lifetime = 7d\n", 0o644)

    hlog("[4/9] Tartomány felderítése…")
    if hrun(["realm", "discover", realm], check=False) != 0:
        raise RuntimeError(f"A(z) {dom} tartomány nem található. Ellenőrizd a DNS-t (SRV rekordok: _ldap._tcp.{dom}).")

    hlog(f"[5/9] Belépés a tartományba ({user})…")
    rc = hrun(["realm", "join", "--verbose", "--membership-software=adcli", "--client-software=sssd",
               f"--user={user}", realm], check=False, stdin_text=pw)
    if rc != 0:
        raise RuntimeError("A tartományba lépés nem sikerült. Lehetséges ok: hibás jelszó, nincs jogosultság "
                           "a gép felvételére, a gép órája eltér a DC-étől (max. 5 perc), vagy DNS-hiba.")
    hrun(["realm", "permit", "--all"], check=False)

    hlog("[6/9] SSSD beállítása…")
    sec = ad_sssd_section()
    if not sec:
        raise RuntimeError(f"Nem találom a domain szekciót a(z) {SSSD_CONF} fájlban.")
    ini_set(SSSD_CONF, sec, {
        "use_fully_qualified_names": "False",
        "fallback_homedir": "/home/%d/%u",
        "default_shell": "/bin/bash",
        "ad_gpo_access_control": "permissive",
        "krb5_ccname_template": "FILE:%d/krb5cc_%U_XXXXXX",
        "ad_hostname": fqdn,
        "cache_credentials": "True",
        "krb5_store_password_if_offline": "True"})
    os.chmod(SSSD_CONF, 0o600)

    hlog("[7/9] NSS és PAM (home könyvtár automatikus létrehozása)…")
    ad_fix_nsswitch()
    put(AD_MKHOME_PROFILE,
        "Name: Create home directory on login\nDefault: yes\nPriority: 900\nSession-Type: Additional\n"
        "Session:\n\trequired\tpam_mkhomedir.so umask=0077 skel=/etc/skel\n", 0o644)
    try:
        with open("/etc/pam.d/common-session", encoding="utf-8") as f:
            cs = [l for l in f.read().splitlines() if "pam_mkhomedir.so" not in l]
        put("/etc/pam.d/common-session", "\n".join(cs) + "\n", 0o644)
    except OSError:
        pass
    hrun(["pam-auth-update", "--enable", "sss", "mkhomedir", "--force"], check=False)

    hlog("[8/9] Sudo jogosultság…")
    for old in ("/etc/sudoers.d/domain_admins", AD_SUDOERS):
        try:
            os.remove(old)
        except OSError:
            pass
    if v["sudo"]:
        txt = ("%domain\\ admins ALL=(ALL:ALL) ALL\n%Domain\\ Admins ALL=(ALL:ALL) ALL\n"
               f"{user} ALL=(ALL:ALL) ALL\n")
        tmp = "/run/ciszterci-sudoers.tmp"
        put(tmp, txt, 0o440)
        try:
            hrun(["visudo", "-cf", tmp])
            put(AD_SUDOERS, txt, 0o440)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    hlog("[9/9] SSSD újraindítása tiszta gyorsítótárral…")
    hrun(["systemctl", "stop", "sssd"], check=False)
    ad_clear_sss_cache()
    hrun(["systemctl", "enable", "sssd"], check=False)
    hrun(["systemctl", "start", "sssd"])
    time.sleep(3)
    if hrun(["id", user], check=False) != 0:
        return (f"A gép bekerült a tartományba, de a(z) {user} felhasználó még nem található. "
                "Indítsd újra a gépet, és ha a bejelentkezés nem megy, nézd meg: journalctl -u sssd", None)
    return (f"Sikeres tartományba léptetés: {fqdn} ({realm}). Indítsd újra a gépet, utána a tartományi "
            "felhasználóval jelentkezhetsz be (felhasználónév domain nélkül).", None)


def op_ad_leave(r):
    info = ad_info()
    if not info:
        raise RuntimeError("A gép nem tagja tartománynak.")
    dom = info["domain"]
    removed = False
    if r.get("remove_account"):
        v = ad_clean(r, need_host=False)
        hlog("A gépfiók törlése az AD-ból…")
        rc = hrun(["realm", "leave", "--remove", f"--user={v['user']}", dom], check=False, stdin_text=v["password"])
        removed = rc == 0
        if not removed:
            hlog("A gépfiókot nem sikerült törölni (jogosultság/jelszó?), helyi kilépés következik.")
    if not removed:
        hrun(["realm", "leave", dom])
    for f in (AD_SUDOERS, "/etc/sudoers.d/domain_admins"):
        try:
            os.remove(f)
        except OSError:
            pass
    hrun(["systemctl", "stop", "sssd"], check=False)
    ad_clear_sss_cache()
    # A gépfiók kulcstáblája a kilépés után értelmetlen (és a GUI tartalék-felismerését is megzavarná).
    try:
        os.remove("/etc/krb5.keytab")
    except OSError:
        pass

    hlog("Tartományi csomagok eltávolítása (purge)…")
    purged = hrun(["apt-get", "remove", "--purge", "-y"] + AD_PURGE_PKGS, check=False) == 0
    msg = f"A gép kilépett a(z) {dom} tartományból."
    if not removed:
        msg += " A gépfiók az AD-ban megmaradt (a tartomány adminisztrátora törölheti)."
    if purged:
        msg += " A tartományi csomagok eltávolítva."
    else:
        msg += " A csomagok eltávolítása nem sikerült (részletek a Naplóban)."
    return msg + " A gépnév változatlan maradt."


# ------------------------------------------------------------------ WireGuard
# A profilok az /etc/wireguard/<név>.conf fájlokban vannak (root:root, 0600), a kapcsolást
# a wg-quick végzi. A root segéd a GUI-tól NEM nyers konfigot fogad (abban PostUp/PreUp
# parancsok lehetnének), hanem ellenőrzött mezőket, és abból maga állítja össze a fájlt.
WG_DIR = "/etc/wireguard"
WG_NAME_RE = re.compile(r"[A-Za-z0-9_=+.-]{1,15}")      # Linux interfésznév-korlát
WG_KEY_RE = re.compile(r"[A-Za-z0-9+/]{43}=")
WG_IFACE_KEYS = {"privatekey", "address", "dns", "mtu"}
WG_PEER_KEYS = {"publickey", "presharedkey", "endpoint", "allowedips", "persistentkeepalive"}


def wg_key_ok(k):
    if not WG_KEY_RE.fullmatch(k or ""):
        return False
    try:
        return len(base64.b64decode(k, validate=True)) == 32
    except ValueError:
        return False


def wg_split(s):
    return [x for x in re.split(r"[\s,;]+", (s or "").strip()) if x]


def wg_pubkey(priv):
    """Kliens nyilvános kulcs a privátból (a wg pubkey stdin-ről olvas, a kulcs nem kerül parancssorba)."""
    if not wg_key_ok(priv):
        return ""
    try:
        r = subprocess.run(["wg", "pubkey"], input=priv + "\n", capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def wg_active(name):
    """Fel van-e hozva a profil WireGuard-interfésze (root nélkül is kiolvasható)."""
    try:
        with open(f"/sys/class/net/{name}/uevent") as f:
            return "DEVTYPE=wireguard" in f.read()
    except OSError:
        return False


def wg_parse_text(text):
    iface, peers, cur = {}, [], None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low == "[interface]":
            cur = iface
        elif low == "[peer]":
            cur = {}
            peers.append(cur)
        elif low.startswith("["):
            cur = {}                                  # ismeretlen szakasz: eldobjuk
        elif "=" in line and cur is not None:
            k, v = line.split("=", 1)
            cur.setdefault(k.strip().lower(), []).append(v.strip())
    return iface, peers


def wg_fields(iface, peers):
    """Az űrlapmezők + az 'extra' (nem támogatott) kulcsok listája. simple=True: itt szerkeszthető."""
    def j(d, k):
        return ", ".join(x for v in d.get(k, []) for x in wg_split(v))

    def first(d, k):
        return (d.get(k) or [""])[0]
    p = peers[0] if peers else {}
    extra = sorted(set(iface) - WG_IFACE_KEYS) + sorted(set(p) - WG_PEER_KEYS)
    if len(peers) > 1:
        extra.append("további [Peer] szakaszok")
    out = {"private_key": first(iface, "privatekey"), "address": j(iface, "address"),
           "dns": j(iface, "dns"), "mtu": first(iface, "mtu"),
           "server_pub": first(p, "publickey"), "psk": first(p, "presharedkey"),
           "endpoint": first(p, "endpoint"), "allowed": j(p, "allowedips"),
           "keepalive": first(p, "persistentkeepalive")}
    out["simple"] = len(peers) == 1 and not extra
    return out, extra


def wg_endpoint_ok(e):
    m = re.fullmatch(r"\[([0-9A-Fa-f:.]+)\]:([0-9]{1,5})", e)
    if m:
        host, port = m.groups()
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return False
    else:
        if e.count(":") != 1:
            return False
        host, port = e.split(":")
        if not HOST_RE.fullmatch(host) or not re.fullmatch(r"[0-9]{1,5}", port):
            return False
    return 1 <= int(port) <= 65535


def wg_validate(f, need_priv=True):
    """Az űrlap ellenőrzése és normalizálása. Hibánál RuntimeError (magyar üzenettel)."""
    o = {}
    pk = (f.get("private_key") or "").strip()
    if (pk or need_priv) and not wg_key_ok(pk):
        raise RuntimeError("Érvénytelen kliens privát kulcs (44 karakteres base64 kulcs kell).")
    o["private_key"] = pk
    sp = (f.get("server_pub") or "").strip()
    if not wg_key_ok(sp):
        raise RuntimeError("Érvénytelen szerver nyilvános kulcs.")
    o["server_pub"] = sp
    psk = (f.get("psk") or "").strip()
    if psk and not wg_key_ok(psk):
        raise RuntimeError("Érvénytelen előmegosztott kulcs.")
    o["psk"] = psk
    try:
        o["address"] = [str(ipaddress.ip_interface(a)) for a in wg_split(f.get("address"))]
    except ValueError:
        raise RuntimeError("Érvénytelen kliens cím (pl. 10.8.0.2/32).") from None
    if not o["address"]:
        raise RuntimeError("Add meg a kliens címét (pl. 10.8.0.2/32).")
    try:
        o["allowed"] = [str(ipaddress.ip_network(a, strict=False)) for a in wg_split(f.get("allowed"))]
    except ValueError:
        raise RuntimeError("Érvénytelen az engedélyezett IP-k listája (pl. 10.8.0.0/24 vagy 0.0.0.0/0, ::/0).") from None
    if not o["allowed"]:
        raise RuntimeError("Add meg az engedélyezett IP-ket (pl. 10.8.0.0/24).")
    dns = []
    for d in wg_split(f.get("dns")):
        try:
            dns.append(str(ipaddress.ip_address(d)))
        except ValueError:
            if not HOST_RE.fullmatch(d):
                raise RuntimeError(f"Érvénytelen DNS-bejegyzés: {d}") from None
            dns.append(d)
    o["dns"] = dns
    ep = (f.get("endpoint") or "").strip()
    if not wg_endpoint_ok(ep):
        raise RuntimeError("Érvénytelen szerver-végpont (host:port, pl. vpn.example.hu:51820).")
    o["endpoint"] = ep
    mtu = str(f.get("mtu") or "").strip()
    if mtu and not (re.fullmatch(r"[0-9]{3,4}", mtu) and 576 <= int(mtu) <= 9000):
        raise RuntimeError("Érvénytelen MTU (576–9000).")
    o["mtu"] = mtu
    ka = str(f.get("keepalive") or "").strip()
    if ka and not (re.fullmatch(r"[0-9]{1,5}", ka) and int(ka) <= 65535):
        raise RuntimeError("Érvénytelen keepalive érték.")
    o["keepalive"] = "" if ka in ("", "0") else ka
    return o


def wg_render_conf(o):
    lines = ["# Ciszterci Admin – WireGuard profil", "[Interface]",
             f"PrivateKey = {o['private_key']}", f"Address = {', '.join(o['address'])}"]
    if o["dns"]:
        lines.append(f"DNS = {', '.join(o['dns'])}")
    if o["mtu"]:
        lines.append(f"MTU = {o['mtu']}")
    lines += ["", "[Peer]", f"PublicKey = {o['server_pub']}"]
    if o["psk"]:
        lines.append(f"PresharedKey = {o['psk']}")
    lines.append(f"Endpoint = {o['endpoint']}")
    lines.append(f"AllowedIPs = {', '.join(o['allowed'])}")
    if o["keepalive"]:
        lines.append(f"PersistentKeepalive = {o['keepalive']}")
    return "\n".join(lines) + "\n"


def put_secret(path, data):
    """Titkos fájl írása: a tartalom sosem kerül világ által olvasható fájlba."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)


def wg_read_profile(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        iface, peers = wg_parse_text(fh.read(1 << 20))
    out, extra = wg_fields(iface, peers)
    out["extra"] = extra
    return out


def wg_autostart_on(name):
    try:
        return subprocess.run(["systemctl", "is-enabled", "--quiet", f"wg-quick@{name}"]).returncode == 0
    except FileNotFoundError:
        return False


def wg_collect():
    """A profilok listája a GUI-nak. Privát kulcs és PSK soha nem hagyja el a segédet."""
    out = []
    try:
        names = sorted(fn[:-5] for fn in os.listdir(WG_DIR) if fn.endswith(".conf"))
    except OSError:
        return out
    for n in names:
        if not WG_NAME_RE.fullmatch(n):
            continue
        try:
            info = wg_read_profile(f"{WG_DIR}/{n}.conf")
        except OSError:
            continue
        priv, psk = info.pop("private_key", ""), info.pop("psk", "")
        info.update(name=n, has_psk=bool(psk), client_pub=wg_pubkey(priv), autostart=wg_autostart_on(n))
        out.append(info)
    return out


def wg_need_tools():
    if not (have("wg") and have("wg-quick")):
        raise RuntimeError("A WireGuard eszközök nincsenek telepítve (wireguard-tools).")


def wg_profile(r, must_exist=True):
    name = r.get("name", "")
    if not WG_NAME_RE.fullmatch(name):
        raise RuntimeError("Érvénytelen profilnév (1–15 karakter: betű, szám, _ = + . -).")
    path = f"{WG_DIR}/{name}.conf"
    if must_exist and not os.path.isfile(path):
        raise RuntimeError(f"Nincs ilyen profil: {name}")
    return name, path


def op_wg_list(r):
    return "A lista frissítve.", wg_collect()


def op_wg_save(r):
    wg_need_tools()
    name, path = wg_profile(r, must_exist=False)
    form = dict(r)
    if r.get("edit"):
        name, path = wg_profile(r)
        old = wg_read_profile(path)
        if not old["simple"]:
            raise RuntimeError("Összetett profil (több peer vagy egyéb beállítás), itt nem szerkeszthető.")
        if wg_active(name):
            raise RuntimeError("Szerkesztés előtt kapcsold ki a VPN-t.")
        if not (r.get("private_key") or "").strip():
            form["private_key"] = old["private_key"]
        if not (r.get("psk") or "").strip():
            form["psk"] = "" if r.get("psk_clear") else old["psk"]
    else:
        if os.path.exists(path):
            raise RuntimeError(f"Már van ilyen nevű profil: {name}")
        if os.path.exists(f"/sys/class/net/{name}"):
            raise RuntimeError(f"Ilyen nevű hálózati eszköz már létezik: {name}")
    o = wg_validate(form)
    os.makedirs(WG_DIR, exist_ok=True)
    os.chmod(WG_DIR, 0o700)
    put_secret(path, wg_render_conf(o))
    hlog(f"Profil mentve: {path}")
    note = "" if r.get("edit") else vpn_first_setup()
    return f"Profil mentve: {name}." + note, wg_collect()


def op_wg_up(r):
    wg_need_tools()
    name, path = wg_profile(r)
    if wg_active(name):
        return "Már csatlakozva.", wg_collect()
    if wg_read_profile(path)["dns"] and not have("resolvconf"):
        # A wg-quick a DNS beállításához resolvconfot használ: első használatkor pótoljuk.
        hlog("A profil DNS-t állít be, de a resolvconf hiányzik: az openresolv telepítése…")
        hrun(["apt-get", "update"], check=False)
        hrun(["apt-get", "install", "-y", "openresolv"])
        if not have("resolvconf"):
            raise RuntimeError("Az openresolv telepítése után sem található a resolvconf.")
    hrun(["wg-quick", "up", name])
    return f"A VPN csatlakozott: {name}", wg_collect()


def op_wg_down(r):
    wg_need_tools()
    name, _path = wg_profile(r)
    if not wg_active(name):
        return "Már le van kapcsolva.", wg_collect()
    hrun(["wg-quick", "down", name])
    return f"A VPN lekapcsolva: {name}", wg_collect()


def op_wg_delete(r):
    name, path = wg_profile(r)
    if wg_active(name):
        hrun(["wg-quick", "down", name], check=False)
    hrun(["systemctl", "disable", f"wg-quick@{name}"], check=False)
    os.remove(path)
    return f"Profil törölve: {name}", wg_collect()


def op_wg_autostart(r):
    name, _path = wg_profile(r)
    if r.get("action") not in ("enable", "disable"):
        raise RuntimeError("Ismeretlen művelet.")
    hrun(["systemctl", r["action"], f"wg-quick@{name}"])
    return ("Indítás rendszerindításkor: bekapcsolva." if r["action"] == "enable"
            else "Indítás rendszerindításkor: kikapcsolva."), wg_collect()


OPS = {"login": op_login, "pkg": op_pkg, "deb": op_deb, "debremove": op_debremove,
       "chrony": op_chrony, "chrony_ctl": op_chrony_ctl, "time": op_time,
       "wg_list": op_wg_list, "wg_save": op_wg_save, "wg_up": op_wg_up, "wg_down": op_wg_down,
       "wg_delete": op_wg_delete, "wg_autostart": op_wg_autostart,
       "ad_join": op_ad_join, "ad_leave": op_ad_leave}


def helper_main():
    for line in sys.stdin:
        try:
            req = json.loads(line)
            res = OPS[req["op"]](req)
            if isinstance(res, tuple):          # (üzenet, adat): az adat a GUI-nak szól (pl. WireGuard lista)
                emit({"rc": 0, "msg": res[0] or "Kész.", "data": res[1]})
            else:
                emit({"rc": 0, "msg": res or "Kész."})
        except Exception as e:  # noqa: BLE001
            emit({"rc": 1, "msg": str(e)})


VPN_OPS = ("wg_list", "wg_up", "wg_down")


def vpn_helper_main():
    """A szűk segéd: ugyanaz a JSON-protokoll, de csak a VPN ki/be kapcsolása és a lista."""
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if req.get("op") not in VPN_OPS:
                raise RuntimeError("Ez a művelet jelszó nélkül nem engedélyezett.")
            msg, data = OPS[req["op"]](req)
            emit({"rc": 0, "msg": msg, "data": data})
        except Exception as e:  # noqa: BLE001
            emit({"rc": 1, "msg": str(e)})


class Helper:
    def __init__(self, cmd=None):
        self.cmd = cmd or ["pkexec", "/usr/bin/python3", INSTALL_PATH, "--helper"]
        self.p = None
        self.data = None

    def _start(self):
        if self.p is None or self.p.poll() is not None:
            self.p = subprocess.Popen(self.cmd,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8")

    def call(self, req, on_log=None):
        self.data = None
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
                self.data = r.get("data")
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


def vpn_direct():
    """Tagja-e a program felhasználója a vpn csoportnak (a polkit-szabály a /etc/group alapján dönt,
    így újrabejelentkezés nélkül is él), és telepítve van-e a szűk segéd."""
    try:
        g = grp.getgrnam(VPN_GROUP)
        u = pwd.getpwuid(os.getuid())
    except KeyError:
        return False
    return ((u.pw_name in g.gr_mem or u.pw_gid == g.gr_gid)
            and os.path.exists(VPN_HELPER) and os.path.exists(POLKIT_POLICY))


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
            self.helper_injected = helper is not None
            self.hv = Helper(["pkexec", VPN_HELPER]) if (helper is None and vpn_direct()) else None
            self.busy = False
            self.pkgrows = []
            self.bg_path = None
            self.wg_profiles, self.wg_loaded, self.wg_editing = [], False, None

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
                     ("WireGuard VPN", self.page_wg), ("Rendszeridő", self.page_time), ("Rendszer", self.page_system)]
            self.page_names = []
            self.wg_idx = [t for t, _b in pages].index("WireGuard VPN")
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
                if row.get_index() == self.wg_idx and not self.wg_loaded and pkg_ok("wireguard-tools"):
                    self.wg_refresh()

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

        def run_task(self, steps, cb=None):
            if self.busy:
                return False
            self.busy = True
            self.stack.set_sensitive(False)
            self.progress.show()
            self.status.set_text("Folyamatban… (hitelesítést kérhet)")
            GLib.timeout_add(120, self.pulse)

            def worker():
                rc, msg, data = 0, "", None
                for op, params in steps:
                    h = self.hv if (self.hv and op in VPN_OPS) else self.h
                    rc, msg = h.call(dict(params, op=op), on_log=lambda m: GLib.idle_add(self.log, m))
                    data = h.data
                    if rc != 0:
                        break
                GLib.idle_add(self.task_done, rc, msg, cb, data)
            threading.Thread(target=worker, daemon=True).start()
            return True

        def pulse(self):
            if self.busy:
                self.progress.pulse()
            return self.busy

        def task_done(self, rc, msg, cb=None, data=None):
            self.busy = False
            self.progress.hide()
            self.stack.set_sensitive(True)
            self.log(("OK: " if rc == 0 else "HIBA: ") + msg)
            if rc != 0:
                self.expander.set_expanded(True)
            self.say(rc, msg)
            if cb:
                cb(rc, msg, data)
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
            if hasattr(self, "ad_state"):
                self.ad_refresh()
            if hasattr(self, "wg_ctrls"):
                ok = pkg_ok("wireguard-tools")
                for w in self.wg_ctrls:
                    w.set_sensitive(ok)
                if not ok:
                    hint = "⚠ A WireGuard eszközök nincsenek telepítve: előbb telepítsd őket fent."
                elif self.hv:
                    hint = (f"✔ A(z) {VPN_GROUP} csoport tagja vagy: a VPN jelszó nélkül kapcsolható. "
                            "Profil létrehozásához, szerkesztéséhez és törléséhez rendszergazdai jelszó kell.")
                else:
                    hint = (f"A VPN kapcsolásához jelszó kell. Az első profil létrehozásakor a program felveszi "
                            f"a felhasználót a(z) {VPN_GROUP} csoportba, utána jelszó nélkül kapcsolható. "
                            f"Más felhasználó: {APP_NAME} --vpn-user FELHASZNÁLÓ")
                self.wg_hint.set_text(hint)
                if ok and not self.wg_loaded and self.stack.get_visible_child_name() == self.page_names[self.wg_idx]:
                    self.wg_refresh()

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
                             "Add meg az adatokat, a program mindent beállít, és szükség esetén telepít is. "
                             "A művelethez rendszergazdai jelszót kér a rendszer.")
            self.ad_joined_dom = None
            self.ad_state = Gtk.Label(xalign=0)
            self.ad_state.set_line_wrap(True)
            fr = Gtk.Frame()
            inner = Gtk.Box(orientation=V)
            inner.set_border_width(12)
            inner.pack_start(self.ad_state, False, False, 0)
            fr.add(inner)
            b.pack_start(fr, False, False, 4)

            self.head(b, "A tartomány és a gép adatai")
            grid = Gtk.Grid(column_spacing=14, row_spacing=10)
            self.ad_e = {}
            spec = [("host", "Gépnév", "pl. pc-cl-01", False),
                    ("domain", "Tartomány neve", "pl. samba.lan", False),
                    ("user", "Tartományi felhasználó", "domain nélkül, pl. mszabi", False),
                    ("password", "Jelszó", "", True)]
            for i, (k, label, ph, secret) in enumerate(spec):
                l = Gtk.Label(label=label, xalign=0)
                e = Gtk.Entry()
                e.set_placeholder_text(ph)
                e.set_width_chars(36)
                e.set_hexpand(True)
                if secret:
                    e.set_visibility(False)
                    e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
                    e.connect("activate", self.ad_join_clicked)
                grid.attach(l, 0, i, 1, 1)
                grid.attach(e, 1, i, 1, 1)
                self.ad_e[k] = e
            self.ad_e["host"].set_text(os.uname().nodename.split(".")[0])
            self.ad_e["domain"].set_text("samba.lan")
            b.pack_start(grid, False, False, 4)
            b.pack_start(self.lab("A gépnév legfeljebb 15 karakter lehet (kisbetű, szám, kötőjel). "
                                  "A felhasználónak jogosultnak kell lennie a gép tartományba vételére."),
                         False, False, 2)

            self.ad_c_sudo = Gtk.CheckButton(
                label="Sudo jog a Domain Admins csoportnak és a belépést végző felhasználónak")
            self.ad_c_sudo.set_active(True)
            self.ad_c_rm = Gtk.CheckButton(
                label="Kilépéskor a gépfiókot az AD-ból is töröljék (a fenti felhasználó és jelszó kell hozzá)")
            b.pack_start(self.ad_c_sudo, False, False, 2)
            b.pack_start(self.ad_c_rm, False, False, 2)

            bt = Gtk.Box(spacing=10)
            bt.set_margin_top(10)
            self.ad_btn_join = self.btn("Belépés a tartományba", self.ad_join_clicked)
            self.ad_btn_join.get_style_context().add_class("suggested-action")
            self.ad_btn_leave = self.btn("Kilépés a tartományból", self.ad_leave_clicked)
            self.ad_btn_leave.get_style_context().add_class("destructive-action")
            bt.pack_start(self.ad_btn_join, False, False, 0)
            bt.pack_start(self.ad_btn_leave, False, False, 0)
            b.pack_start(bt, False, False, 4)
            return b

        def ad_refresh(self):
            info = ad_info()
            if AD_DIAG:
                self.log("Tartomány-állapot: " + AD_DIAG)
            self.ad_joined_dom = info["domain"] if info else None
            if info:
                dom = GLib.markup_escape_text(info["domain"])
                self.ad_state.set_markup(f'<span foreground="#15803d" weight="bold" size="large">'
                                         f'● A gép tagja a(z) {dom} tartománynak.</span>')
            else:
                extra = "" if have("realm") else " (a szükséges csomagokat a program telepíti)"
                self.ad_state.set_markup(f'<span foreground="#b45309" weight="bold" size="large">'
                                         f'○ A gép nincs tartományban.</span>{GLib.markup_escape_text(extra)}')
            joined = info is not None
            self.ad_btn_join.set_sensitive(not joined)
            self.ad_btn_leave.set_sensitive(joined)
            for k in ("host", "domain"):
                self.ad_e[k].set_sensitive(not joined)
            self.ad_c_sudo.set_sensitive(not joined)
            self.ad_c_rm.set_sensitive(joined)

        def ad_values(self):
            v = {k: e.get_text() for k, e in self.ad_e.items()}
            v["sudo"] = self.ad_c_sudo.get_active()
            return v

        def ad_join_clicked(self, *_):
            if self.busy or self.ad_joined_dom:
                return
            try:
                v = ad_clean(self.ad_values())
            except RuntimeError as ex:
                self.say(1, str(ex))
                return
            if not self.confirm(f"A(z) {v['host']} gép belép a(z) {v['domain']} tartományba, "
                                f"a gépnevet is átállítja. Folytatod?"):
                return
            self.run_task([("ad_join", v)], self.ad_joined)

        def ad_joined(self, rc, msg, data):
            if rc != 0:
                return
            self.ad_e["password"].set_text("")
            if self.confirm("A tartományba lépés kész. Újraindítod most a gépet? (ajánlott)"):
                subprocess.Popen(["systemctl", "reboot"])

        def ad_leave_clicked(self, *_):
            if self.busy or not self.ad_joined_dom:
                return
            params = {"remove_account": self.ad_c_rm.get_active()}
            if params["remove_account"]:
                try:
                    v = ad_clean(self.ad_values(), need_host=False)
                except RuntimeError as ex:
                    self.say(1, str(ex))
                    return
                params.update(domain=v["domain"], user=v["user"], password=v["password"])
            if not self.confirm(f"Biztosan kilépteted ezt a gépet a(z) {self.ad_joined_dom} tartományból? "
                                "Utána a tartományi csomagok (sssd, realmd, adcli…) is eltávolításra kerülnek."):
                return
            self.run_task([("ad_leave", params)], self.ad_left)

        def ad_left(self, rc, msg, data):
            if rc == 0:
                self.ad_e["password"].set_text("")

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

        # -------------------------------------------------------------- WireGuard VPN
        def page_wg(self):
            b = self.mk_page("WireGuard VPN",
                             "Meglévő kliens-kulcsok (profilok) importálása és kezelése; a VPN profilonként "
                             "kapcsolható ki/be. Ha nem vagy a vpn csoport tagja, a lista megnyitásakor és a "
                             "kapcsoláskor hitelesítést kér a rendszer.")
            self.pkg_row(b, "WireGuard eszközök", "A wireguard-tools csomag (wg, wg-quick) a Debian-tárolóból.",
                         "wireguard-tools", [("pkg", {"action": "install", "pkgs": ["wireguard-tools"]})],
                         [("pkg", {"action": "remove", "pkgs": ["wireguard-tools"]})])
            self.head(b, "Kapcsolatok")
            bar = Gtk.Box(spacing=8)
            self.wg_ctrls = [self.btn("Új profil…", self.wg_new),
                             self.btn("Importálás .conf fájlból…", self.wg_import),
                             self.btn("Lista frissítése", self.wg_refresh)]
            for w in self.wg_ctrls:
                bar.pack_start(w, False, False, 0)
            b.pack_start(bar, False, False, 0)
            self.wg_hint = self.lab("")
            b.pack_start(self.wg_hint, False, False, 0)
            self.wg_box = Gtk.Box(orientation=V, spacing=4)
            b.pack_start(self.wg_box, False, False, 4)
            self.wg_render()

            # --- űrlap (új / szerkesztés)
            self.wg_exp = Gtk.Expander(label="Profil")
            g = Gtk.Grid(column_spacing=10, row_spacing=6)
            g.set_margin_start(12)
            g.set_margin_top(6)
            self.wg_e, self.wg_ph = {}, {}

            def entry(key, label, row, width=44, ph=""):
                g.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
                e = Gtk.Entry()
                e.set_width_chars(width)
                e.set_placeholder_text(ph)
                g.attach(e, 1, row, 1, 1)
                self.wg_e[key], self.wg_ph[key] = e, ph
                return e
            entry("name", "Profil neve:", 0, 18, "pl. iskola (max. 15 karakter)")
            pk = entry("private_key", "Kliens privát kulcs:", 1)
            pk.set_visibility(False)
            pk.connect("changed", self.wg_on_priv_changed)
            kb = Gtk.Box(spacing=6)
            kb.pack_start(self.btn("Új kulcs generálása", self.wg_gen), False, False, 0)
            self.wg_c_show = Gtk.CheckButton(label="Mutat")
            self.wg_c_show.connect("toggled", lambda c: pk.set_visibility(c.get_active()))
            kb.pack_start(self.wg_c_show, False, False, 0)
            g.attach(kb, 2, 1, 1, 1)
            g.attach(Gtk.Label(label="Kliens nyilvános kulcs:", xalign=1), 0, 2, 1, 1)
            self.wg_pub = Gtk.Label(xalign=0)
            self.wg_pub.set_selectable(True)
            g.attach(self.wg_pub, 1, 2, 2, 1)
            entry("address", "Kliens cím:", 3, 44, "pl. 10.8.0.2/32")
            entry("dns", "DNS (nem kötelező):", 4, 44, "pl. 10.8.0.1")
            entry("server_pub", "Szerver nyilvános kulcsa:", 5)
            entry("psk", "Előmegosztott kulcs (nem kötelező):", 6)
            self.wg_c_pskclear = Gtk.CheckButton(label="Meglévő törlése")
            g.attach(self.wg_c_pskclear, 2, 6, 1, 1)
            entry("endpoint", "Szerver végpontja:", 7, 44, "pl. vpn.example.hu:51820")
            entry("allowed", "Engedélyezett IP-k:", 8, 44, "pl. 10.8.0.0/24")
            g.attach(self.btn("Teljes forgalom",
                              lambda *_: self.wg_e["allowed"].set_text("0.0.0.0/0, ::/0")), 2, 8, 1, 1)
            g.attach(Gtk.Label(label="Keepalive (mp, 0 = ki):", xalign=1), 0, 9, 1, 1)
            self.wg_sp = Gtk.SpinButton.new_with_range(0, 3600, 1)
            self.wg_sp.set_value(25)
            kk = Gtk.Box()
            kk.pack_start(self.wg_sp, False, False, 0)
            g.attach(kk, 1, 9, 1, 1)
            entry("mtu", "MTU (nem kötelező):", 10, 8)
            hb = Gtk.Box(spacing=8)
            hb.pack_start(self.btn("Mentés", self.wg_save), False, False, 0)
            hb.pack_start(self.btn("Mégse", self.wg_cancel), False, False, 0)
            g.attach(hb, 1, 11, 1, 1)
            self.wg_exp.add(g)
            b.pack_start(self.wg_exp, False, False, 6)
            return b

        # --- lista
        def wg_render(self):
            for c in self.wg_box.get_children():
                self.wg_box.remove(c)
            if not self.wg_profiles:
                self.wg_box.pack_start(self.lab("(Nincs betöltött profil.)"), False, False, 0)
            for p in self.wg_profiles:
                self.wg_box.pack_start(self.wg_row(p), False, False, 0)
            self.wg_box.show_all()

        def wg_row(self, p):
            name = p["name"]
            act = wg_active(name)
            box = Gtk.Box(orientation=V, spacing=2)
            row = Gtk.Box(spacing=10)
            left = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(xalign=0)
            state = ('<span foreground="#15803d">● csatlakozva</span>' if act
                     else '<span foreground="#6b7280">○ lekapcsolva</span>')
            t.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>   {state}")
            left.pack_start(t, False, False, 0)
            left.pack_start(self.lab(f"Végpont: {p.get('endpoint') or '–'}    Cím: {p.get('address') or '–'}"),
                            False, False, 0)
            pub = self.lab("Kliens nyilvános kulcs: " + (p.get("client_pub") or "–"))
            pub.set_selectable(True)
            left.pack_start(pub, False, False, 0)
            if not p.get("simple"):
                extra = ", ".join(p.get("extra") or []) or "több peer"
                left.pack_start(self.lab(f"Összetett profil ({extra}): csak ki/be kapcsolható és törölhető."),
                                False, False, 0)
            sw = Gtk.Switch()
            sw.set_active(act)
            sw.set_valign(Gtk.Align.CENTER)
            sw.connect("state-set", self.on_wg_switch, name)
            ca = Gtk.CheckButton(label="Indul rendszerindításkor")
            ca.set_active(bool(p.get("autostart")))
            ca.connect("toggled", self.on_wg_auto, name)
            be = self.btn("Szerkesztés", lambda *_: self.wg_edit(p))
            be.set_sensitive(bool(p.get("simple")))
            bd = self.btn("Törlés", lambda *_: self.wg_delete(name))
            row.pack_start(left, True, True, 0)
            for w in (sw, ca, be, bd):
                row.pack_start(w, False, False, 0)
            box.pack_start(row, False, False, 4)
            box.pack_start(Gtk.Separator(), False, False, 2)
            return box

        def on_wg_switch(self, sw, state, name):
            if not self.busy:
                self.run_task([("wg_up" if state else "wg_down", {"name": name})], self.wg_done)
            return True        # a kapcsoló állapotát a művelet után a lista újrarajzolása állítja be

        def on_wg_auto(self, cb, name):
            if not self.busy:
                self.run_task([("wg_autostart", {"name": name,
                                                 "action": "enable" if cb.get_active() else "disable"})],
                              self.wg_done)

        def wg_delete(self, name):
            if self.confirm(f"Törlöd a(z) {name} profilt? A kliens kulcs is törlődik erről a gépről."):
                self.run_task([("wg_delete", {"name": name})], self.wg_done)

        def wg_refresh(self, *_):
            if self.run_task([("wg_list", {})], self.wg_done):
                self.wg_loaded = True
                return True
            return False

        def wg_done(self, rc, msg, data):
            if data is not None:
                self.wg_profiles = data
            self.wg_render()

        # --- űrlap
        def wg_clear_form(self):
            for k, e in self.wg_e.items():
                e.set_text("")
                e.set_placeholder_text(self.wg_ph[k])
                e.set_sensitive(True)
            self.wg_sp.set_value(25)
            self.wg_c_pskclear.set_active(False)
            self.wg_pub.set_text("")

        def wg_new(self, *_):
            self.wg_editing = None
            self.wg_clear_form()
            self.wg_exp.set_label("Új profil")
            self.wg_exp.set_expanded(True)
            self.wg_e["name"].grab_focus()

        def wg_edit(self, p):
            if wg_active(p["name"]):
                self.say(1, "Szerkesztés előtt kapcsold ki a VPN-t.")
                return
            self.wg_clear_form()
            self.wg_editing = p["name"]
            e = self.wg_e
            e["name"].set_text(p["name"])
            e["name"].set_sensitive(False)
            e["private_key"].set_placeholder_text("(változatlan marad, ha üresen hagyod)")
            if p.get("has_psk"):
                e["psk"].set_placeholder_text("(változatlan marad, ha üresen hagyod)")
            for k in ("address", "dns", "server_pub", "endpoint", "allowed", "mtu"):
                e[k].set_text(p.get(k) or "")
            ka = p.get("keepalive") or "0"
            self.wg_sp.set_value(int(ka) if ka.isdigit() else 0)
            self.wg_pub.set_text(p.get("client_pub") or "")
            self.wg_exp.set_label(f"Profil szerkesztése: {p['name']}")
            self.wg_exp.set_expanded(True)

        def wg_on_priv_changed(self, entry):
            t = entry.get_text().strip()
            if not t:
                self.wg_pub.set_text("")
            else:
                self.wg_pub.set_text(wg_pubkey(t) or "(érvénytelen kulcs, vagy hiányzik a wireguard-tools)")

        def wg_gen(self, *_):
            if not have("wg"):
                self.say(1, "Előbb telepítsd a WireGuard eszközöket.")
                return
            e = self.wg_e["private_key"]
            if e.get_text().strip() and not self.confirm("A mezőben már van kulcs. Felülírod egy újonnan generálttal?"):
                return
            r = subprocess.run(["wg", "genkey"], capture_output=True, text=True)
            if r.returncode == 0:
                e.set_text(r.stdout.strip())
                self.say(0, "Új kulcs generálva. A nyilvános kulcsot add meg a szerver adminisztrátorának.")

        def wg_import(self, *_):
            d = Gtk.FileChooserDialog(title="WireGuard .conf fájl kiválasztása", transient_for=self,
                                      action=Gtk.FileChooserAction.OPEN)
            d.add_buttons("Mégse", Gtk.ResponseType.CANCEL, "Megnyitás", Gtk.ResponseType.OK)
            f1 = Gtk.FileFilter()
            f1.set_name("WireGuard (*.conf)")
            f1.add_pattern("*.conf")
            d.add_filter(f1)
            f2 = Gtk.FileFilter()
            f2.set_name("Minden fájl")
            f2.add_pattern("*")
            d.add_filter(f2)
            path = d.get_filename() if d.run() == Gtk.ResponseType.OK else None
            d.destroy()
            if not path:
                return
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    iface, peers = wg_parse_text(fh.read(65536))
            except OSError as ex:
                self.say(1, f"A fájl nem olvasható: {ex}")
                return
            if not peers or "privatekey" not in iface:
                self.say(1, "Ez nem tűnik érvényes WireGuard konfigurációnak (hiányzik a PrivateKey vagy a [Peer]).")
                return
            fl, extra = wg_fields(iface, peers)
            self.wg_new()
            stem = re.sub(r"[^A-Za-z0-9_=+.-]", "", os.path.splitext(os.path.basename(path))[0])[:15] or "vpn"
            e = self.wg_e
            e["name"].set_text(stem)
            for k in ("private_key", "address", "dns", "server_pub", "psk", "endpoint", "allowed", "mtu"):
                e[k].set_text(fl[k])
            ka = fl["keepalive"]
            self.wg_sp.set_value(int(ka) if ka.isdigit() else 0)
            msg = "Beolvasva. Ellenőrizd az adatokat, majd Mentés."
            if extra:
                msg += " Biztonsági okból nem importált beállítások: " + ", ".join(extra) + "."
            self.say(0, msg)

        def wg_form_values(self):
            e = self.wg_e
            v = {k: e[k].get_text().strip() for k in
                 ("name", "private_key", "address", "dns", "server_pub", "psk", "endpoint", "allowed", "mtu")}
            v["keepalive"] = str(int(self.wg_sp.get_value()))
            v["psk_clear"] = self.wg_c_pskclear.get_active()
            return v

        def wg_save(self, *_):
            v = self.wg_form_values()
            edit = self.wg_editing is not None
            try:
                if not WG_NAME_RE.fullmatch(v["name"]):
                    raise RuntimeError("A profilnév 1–15 karakter lehet: betű, szám, _ = + . -")
                wg_validate(v, need_priv=not edit)
            except RuntimeError as ex:
                self.say(1, str(ex))
                return
            self.run_task([("wg_save", dict(v, edit=edit))], self.wg_saved)

        def wg_saved(self, rc, msg, data):
            self.wg_done(rc, msg, data)
            if rc == 0:
                if self.hv is None and not self.helper_injected and vpn_direct():
                    self.hv = Helper(["pkexec", VPN_HELPER])     # az első profil után már jelszó nélkül megy
                self.wg_cancel()

        def wg_cancel(self, *_):
            self.wg_editing = None
            self.wg_clear_form()
            self.wg_exp.set_expanded(False)

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
    if a[:1] == ["--vpn-user"]:
        if len(a) != 2:
            sys.exit(f"Használat: {APP_NAME} --vpn-user FELHASZNÁLÓ")
        sys.exit(vpn_user_main(a[1]) if os.geteuid() == 0 else run_elevated(["--vpn-user", a[1]]))
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
