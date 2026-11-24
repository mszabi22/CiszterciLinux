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
    "Categories=System;\nKeywords=admin;vezérlőpult;beállítások;bejelentkezés;tartomány;idő;megosztás;samba;\n")

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


PKG_WHITELIST = {"chrony", "nextcloud-desktop", "wireguard-tools", "samba", "cups", "system-config-printer",
                 "xfce4-settings"}


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


# ------------------------------------------------------- Mappamegosztás (Samba / SMB)
# A megosztásokat egy saját fájl (SHARE_CONF) tartalmazza, amit az smb.conf végéről húzunk be (include),
# így az smb.conf többi része érintetlen marad. A root segéd minden mezőt ellenőriz, mentés előtt
# testparm-mal kipróbálja a konfigurációt, hibánál visszaállítja az előzőt.
SMB_CONF = "/etc/samba/smb.conf"
SHARE_CONF = "/etc/samba/ciszterci-shares.conf"
SHARE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
SHARE_RESERVED = {"global", "homes", "printers", "print$", "ipc$"}
SHARE_ROOTS = ("/home", "/srv", "/mnt", "/media", "/opt", "/data", "/shares")
SHARE_MODES = ("users", "guest_ro", "guest_rw")
UNIX_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}")
SHARE_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f%]")


def share_path_ok(rp):
    """Csak a megengedett gyökerek alatti mappa osztható meg (maga a gyökér nem)."""
    return any(rp.startswith(r + "/") for r in SHARE_ROOTS)


def share_need():
    if not (have("smbd") and have("smbpasswd")):
        raise RuntimeError("A Samba nincs telepítve (samba csomag).")


def share_unix_user(name):
    """Rendes (nem rendszer-) felhasználó: uid 1000–59999."""
    if not isinstance(name, str) or not UNIX_NAME_RE.fullmatch(name):
        raise RuntimeError(f"Érvénytelen felhasználónév: {name}")
    try:
        u = pwd.getpwnam(name)
    except KeyError:
        raise RuntimeError(f"Nincs ilyen felhasználó: {name}")
    if not 1000 <= u.pw_uid < 60000:
        raise RuntimeError(f"Rendszerfelhasználó nem használható: {name}")
    return u


def share_principal(p):
    """Felhasználó vagy @csoport ellenőrzése a hozzáférési listához."""
    if isinstance(p, str) and p.startswith("@"):
        g = p[1:]
        if not UNIX_NAME_RE.fullmatch(g):
            raise RuntimeError(f"Érvénytelen csoportnév: {g}")
        try:
            gr = grp.getgrnam(g)
        except KeyError:
            raise RuntimeError(f"Nincs ilyen csoport: {g}")
        if gr.gr_gid == 0:
            raise RuntimeError("A root csoport nem használható.")
        return p
    share_unix_user(p)
    return p


def share_path(p):
    if not isinstance(p, str) or not p.startswith("/") or len(p) > 1000 or SHARE_BAD_CHARS.search(p):
        raise RuntimeError("Érvénytelen mappa-útvonal.")
    rp = os.path.realpath(p)
    if SHARE_BAD_CHARS.search(rp) or not os.path.isdir(rp):
        raise RuntimeError(f"A mappa nem létezik vagy nem használható: {p}")
    if not share_path_ok(rp):
        raise RuntimeError("Biztonsági okból csak a /home, /srv, /mnt, /media, /opt, /data és /shares "
                           "alatti mappa osztható meg (maga ez a könyvtár nem).")
    return rp


def share_main_names():
    """Az smb.conf saját szakaszainak nevei (hogy ne ütközzünk velük)."""
    try:
        with open(SMB_CONF, encoding="utf-8", errors="replace") as f:
            return {m.group(1).strip().lower() for m in re.finditer(r"^\s*\[([^\]]+)\]", f.read(), re.M)}
    except OSError:
        return set()


def share_read():
    """A kezelt megosztások beolvasása a SHARE_CONF-ból."""
    raw, cur = [], None
    try:
        with open(SHARE_CONF, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if not t or t[0] in "#;":
                    continue
                m = re.fullmatch(r"\[([^\]]+)\]", t)
                if m:
                    cur = {"name": m.group(1), "kv": {}}
                    raw.append(cur)
                elif cur is not None and "=" in t:
                    k, v = t.split("=", 1)
                    cur["kv"][k.strip().lower()] = v.strip()
    except OSError:
        return []

    def split(s):
        return [x for x in re.split(r"[,\s]+", s or "") if x]
    out = []
    for c in raw:
        kv = c["kv"]
        guest = kv.get("guest ok", "no").lower() == "yes"
        ro = kv.get("read only", "yes").lower() != "no"
        wl = split(kv.get("write list"))
        if guest and not ro:
            mode, users = "guest_rw", []
        elif guest:
            mode, users = "guest_ro", [{"name": u, "rw": True} for u in wl]
        else:
            mode, users = "users", [{"name": u, "rw": u in wl} for u in split(kv.get("valid users"))]
        out.append({"name": c["name"], "path": kv.get("path", ""), "comment": kv.get("comment", ""),
                    "mode": mode, "users": users, "force_user": kv.get("force user", ""),
                    "available": kv.get("available", "yes").lower() != "no"})
    return out


def share_render(shares):
    lines = ["# Ciszterci Admin – kezelt megosztások. Kézzel ne szerkeszd: a program felülírja.", ""]
    for s in shares:
        lines.append(f"[{s['name']}]")
        lines.append(f"   path = {s['path']}")
        if s.get("comment"):
            lines.append(f"   comment = {s['comment']}")
        lines.append("   browseable = yes")
        lines.append("   available = " + ("yes" if s.get("available", True) else "no"))
        writers = [u["name"] for u in s["users"] if u["rw"]]
        if s["mode"] == "guest_rw":
            lines += ["   guest ok = yes", "   read only = no"]
        elif s["mode"] == "guest_ro":
            lines += ["   guest ok = yes", "   read only = yes"]
            if writers:
                lines.append("   write list = " + ", ".join(writers))
        else:
            lines += ["   guest ok = no", "   read only = yes",
                      "   valid users = " + ", ".join(u["name"] for u in s["users"])]
            if writers:
                lines.append("   write list = " + ", ".join(writers))
        if s.get("force_user"):
            lines.append(f"   force user = {s['force_user']}")
        lines += ["   create mask = 0664", "   directory mask = 0775", ""]
    return "\n".join(lines)


def share_ensure_include():
    try:
        with open(SMB_CONF, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        raise RuntimeError(f"Nem található: {SMB_CONF}")
    if not os.path.exists(SHARE_CONF):
        put(SHARE_CONF, share_render([]), 0o644)
    if re.search(rf"^\s*include\s*=\s*{re.escape(SHARE_CONF)}\s*$", txt, re.M):
        return
    if not os.path.exists(SMB_CONF + ".ciszterci-orig"):
        shutil.copy2(SMB_CONF, SMB_CONF + ".ciszterci-orig")
    with open(SMB_CONF, "a", encoding="utf-8") as f:
        f.write(f"\n# Ciszterci Admin: kezelt megosztások\ninclude = {SHARE_CONF}\n")
    hlog("Az smb.conf kiegészítve a kezelt megosztások fájljával.")


def share_write(shares):
    """Beírja a listát, kipróbálja testparm-mal, újratölti a Sambát; hibánál visszaállítja az előzőt."""
    share_ensure_include()
    try:
        with open(SHARE_CONF, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        old = None
    put(SHARE_CONF, share_render(shares), 0o644)
    if have("testparm"):
        r = subprocess.run(["testparm", "-s", SMB_CONF], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, LC_ALL="C.UTF-8"))
        if r.returncode != 0:
            if old is None:
                os.remove(SHARE_CONF)
            else:
                put(SHARE_CONF, old, 0o644)
            tail = " ".join((r.stderr or r.stdout).strip().splitlines()[-3:])
            raise RuntimeError("A Samba nem fogadta el a beállítást, az előző állapot visszaállt. " + tail)
    if svc_active("smbd"):
        hrun(["smbcontrol", "smbd", "reload-config"], check=False)
    else:
        hrun(["systemctl", "enable", "--now", "smbd"], check=False)


def share_guest_warn():
    try:
        r = subprocess.run(["testparm", "-s", "--parameter-name=map to guest", SMB_CONF],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    v = r.stdout.strip().lower()
    if r.returncode == 0 and v and "bad user" not in v:
        return (" Figyelem: az smb.conf-ban a 'map to guest' nem 'Bad User', ezért egyes (pl. Windows) "
                "gépek nem fogják elérni a jelszó nélküli megosztást.")
    return ""


def share_collect():
    """A GUI-nak szóló teljes állapot: megosztások, felhasználók, Samba-jelszavak, csatlakozott gépek."""
    users = sorted(u.pw_name for u in pwd.getpwall() if 1000 <= u.pw_uid < 60000)
    groups = sorted(g.gr_name for g in grp.getgrall() if 1000 <= g.gr_gid < 60000)
    smb_users = []
    if have("pdbedit"):
        try:
            r = subprocess.run(["pdbedit", "-L"], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=15)
            if r.returncode == 0:
                smb_users = sorted(l.split(":", 1)[0] for l in r.stdout.splitlines() if ":" in l)
        except (OSError, subprocess.TimeoutExpired):
            pass
    shares = share_read()
    for s in shares:
        try:
            s["path_ok"] = os.path.isdir(s["path"])
            s["owner"] = pwd.getpwuid(os.stat(s["path"]).st_uid).pw_name
        except (OSError, KeyError):
            s["path_ok"], s["owner"] = False, ""
    sessions = ""
    if have("smbstatus"):
        try:
            r = subprocess.run(["smbstatus", "-b"], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=15)
            sessions = r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {"shares": shares, "users": users, "groups": groups, "smb_users": smb_users,
            "sessions": sessions, "running": svc_active("smbd")}


def share_find(name):
    if not isinstance(name, str) or not SHARE_NAME_RE.fullmatch(name):
        raise RuntimeError("Érvénytelen megosztásnév.")
    shares = share_read()
    cur = next((s for s in shares if s["name"].lower() == name.lower()), None)
    if cur is None:
        raise RuntimeError(f"Nincs ilyen megosztás: {name}")
    return shares, cur


def op_share_setup(r):
    share_need()
    share_ensure_include()
    hrun(["systemctl", "enable", "--now", "smbd"], check=False)
    hrun(["systemctl", "enable", "--now", "nmbd"], check=False)
    return "A Samba be van állítva.", share_collect()


def op_share_list(r):
    return "A lista frissítve.", share_collect()


def op_share_restart(r):
    share_need()
    hrun(["systemctl", "restart", "smbd"])
    hrun(["systemctl", "restart", "nmbd"], check=False)
    return "A Samba újraindítva.", share_collect()


def op_share_save(r):
    share_need()
    name = r.get("name", "")
    if not isinstance(name, str) or not SHARE_NAME_RE.fullmatch(name) or name.lower() in SHARE_RESERVED:
        raise RuntimeError("Érvénytelen megosztásnév (1–32 karakter: betű, szám, _ . -).")
    edit = bool(r.get("edit"))
    shares = share_read()
    cur = next((s for s in shares if s["name"].lower() == name.lower()), None)
    if edit and cur is None:
        raise RuntimeError(f"Nincs ilyen megosztás: {name}")
    if not edit:
        if cur is not None:
            raise RuntimeError(f"Már van ilyen nevű megosztás: {name}")
        if name.lower() in share_main_names():
            raise RuntimeError(f"Az smb.conf-ban már van ilyen nevű szakasz: {name}")
    rp = share_path(r.get("path"))
    mode = r.get("mode")
    if mode not in SHARE_MODES:
        raise RuntimeError("Ismeretlen hozzáférési mód.")
    comment = SHARE_BAD_CHARS.sub("", str(r.get("comment") or "")).strip()[:120]
    users, seen = [], set()
    for u in (r.get("users") or [])[:64]:
        n = share_principal(str(u.get("name", "")))
        if n not in seen:
            seen.add(n)
            users.append({"name": n, "rw": bool(u.get("rw"))})
    if mode == "users" and not users:
        raise RuntimeError("Adj meg legalább egy felhasználót, vagy válassz jelszó nélküli hozzáférést.")
    if mode == "guest_rw":
        users = []
    elif mode == "guest_ro":
        users = [u for u in users if u["rw"]]
    force = ""
    if r.get("force_owner"):
        try:
            own = pwd.getpwuid(os.stat(rp).st_uid)
        except KeyError:
            own = None
        if own is None or not 1000 <= own.pw_uid < 60000:
            raise RuntimeError("A mappa tulajdonosa nem rendes felhasználó (pl. root), ezért a „tulajdonos "
                               "nevében” opció nem használható: kapcsold ki, vagy add át a mappát egy felhasználónak.")
        force = own.pw_name
    entry = {"name": name if cur is None else cur["name"], "path": rp, "comment": comment, "mode": mode,
             "users": users, "force_user": force, "available": bool(r.get("available", True))}
    if cur is None:
        shares.append(entry)
    else:
        shares[shares.index(cur)] = entry
    share_write(shares)
    note = share_guest_warn() if mode != "users" else ""
    data = share_collect()
    miss = [u["name"] for u in users if not u["name"].startswith("@") and u["name"] not in data["smb_users"]]
    if miss:
        note += " Figyelem: nincs Samba-jelszavuk, ezért nem tudnak belépni: " + ", ".join(miss) + "."
    return f"Megosztás mentve: {name}." + note, data


def op_share_delete(r):
    share_need()
    shares, cur = share_find(r.get("name"))
    share_write([s for s in shares if s is not cur])
    hrun(["smbcontrol", "smbd", "close-share", cur["name"]], check=False)
    return f"A megosztás megszüntetve: {cur['name']}. A mappa és a fájlok érintetlenek.", share_collect()


def op_share_toggle(r):
    share_need()
    shares, cur = share_find(r.get("name"))
    cur["available"] = bool(r.get("available"))
    share_write(shares)
    if not cur["available"]:
        hrun(["smbcontrol", "smbd", "close-share", cur["name"]], check=False)
    return (f"Megosztás {'újra elérhető' if cur['available'] else 'szüneteltetve'}: {cur['name']}",
            share_collect())


def op_share_pw(r):
    share_need()
    u = share_unix_user(r.get("user"))
    pw = r.get("password")
    if not isinstance(pw, str) or not 6 <= len(pw) <= 128 or re.search(r"[\x00-\x1f\x7f]", pw):
        raise RuntimeError("A jelszó 6–128 karakter lehet, vezérlőkarakter nélkül.")
    hrun(["smbpasswd", "-s", "-a", u.pw_name], stdin_text=pw + "\n" + pw)
    return f"A(z) {u.pw_name} Samba-jelszava beállítva.", share_collect()


def op_share_pwdel(r):
    share_need()
    u = share_unix_user(r.get("user"))
    hrun(["smbpasswd", "-x", u.pw_name])
    return f"A(z) {u.pw_name} Samba-hozzáférése törölve (a megosztások listáin megmarad a neve).", share_collect()


# ------------------------------------------------------------ csomagkezelő (apt + Flatpak)
PM_APT_RE = re.compile(r"^[a-z0-9][a-z0-9+.\-]{0,127}$")
PM_FP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,200}$")           # tároló neve / alkalmazásazonosító
PM_FP_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*(\.[A-Za-z0-9_\-]+)+$")
PM_APT_OPTS = ["-y", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]
PM_HIDE_RE = re.compile(r"(-dev|-dbg|-dbgsym|-doc)$|^lib(?!reoffice)")
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
PM_APT_COLOR, PM_FP_COLOR = "#A80030", "#2E6DB4"


def pm_has_flatpak():
    return shutil.which("flatpak") is not None


def pm_fp_remote_add():
    hrun(["flatpak", "remote-add", "--system", "--if-not-exists", "flathub", FLATHUB_URL])


def op_pm_refresh(r):
    hrun(["apt-get", "update"])
    if pm_has_flatpak():
        hrun(["flatpak", "update", "--system", "--appstream"], check=False)
    return "A csomaglisták frissítve."


def op_pm_upgrade(r):
    hrun(["apt-get", "update"])
    hrun(["apt-get", "full-upgrade"] + PM_APT_OPTS)
    if pm_has_flatpak():
        hrun(["flatpak", "update", "--system", "-y", "--noninteractive"])
    return "A rendszer frissítve (apt és Flatpak)."


def op_pm_install(r):
    src, name = r.get("source"), str(r.get("id", ""))
    if src == "apt":
        if not PM_APT_RE.match(name):
            raise RuntimeError("Érvénytelen csomagnév.")
        hrun(["apt-get", "update"], check=False)
        hrun(["apt-get", "install"] + PM_APT_OPTS + [name])
        return f"Telepítve (apt): {name}"
    if src == "flatpak":
        remote = str(r.get("remote") or "flathub")
        if not (PM_FP_ID_RE.match(name) and PM_FP_RE.match(remote)):
            raise RuntimeError("Érvénytelen Flatpak-azonosító vagy tároló.")
        if not pm_has_flatpak():
            raise RuntimeError("A Flatpak nincs telepítve.")
        if remote == "flathub":
            pm_fp_remote_add()
        hrun(["flatpak", "install", "--system", "-y", "--noninteractive", remote, name])
        return f"Telepítve (Flatpak): {name}"
    raise RuntimeError("Ismeretlen forrás.")


def op_pm_remove(r):
    src, name = r.get("source"), str(r.get("id", ""))
    if src == "apt":
        if not PM_APT_RE.match(name):
            raise RuntimeError("Érvénytelen csomagnév.")
        rc = subprocess.run(["dpkg-query", "-W", "-f", "${Essential}", name], capture_output=True, text=True)
        if rc.stdout.strip() == "yes":
            raise RuntimeError("Ez a rendszer működéséhez nélkülözhetetlen csomag, nem távolítható el.")
        hrun(["apt-get", "remove", "-y", name])
        return f"Eltávolítva (apt): {name}"
    if src == "flatpak":
        if not PM_FP_ID_RE.match(name):
            raise RuntimeError("Érvénytelen Flatpak-azonosító.")
        hrun(["flatpak", "uninstall", "--system", "-y", "--noninteractive", name])
        return f"Eltávolítva (Flatpak): {name}"
    raise RuntimeError("Ismeretlen forrás.")


def op_pm_cleanup(r):
    what = r.get("what")
    if what not in ("autoremove", "clean", "both"):
        raise RuntimeError("Ismeretlen takarítási művelet.")
    if what in ("autoremove", "both"):
        hrun(["apt-get", "autoremove", "-y"])
        if pm_has_flatpak():
            hrun(["flatpak", "uninstall", "--system", "--unused", "-y", "--noninteractive"])
    if what in ("clean", "both"):
        hrun(["apt-get", "clean"])
    return "A takarítás kész."


def op_pm_flatpak_setup(r):
    if not pm_has_flatpak():
        hrun(["apt-get", "update"], check=False)
        hrun(["apt-get", "install", "-y", "flatpak"])
    pm_fp_remote_add()
    return ("A Flatpak és a Flathub tároló beállítva. A Flatpak programok az alkalmazásmenübe "
            "újrabejelentkezés után kerülnek be.")


# -- olvasó segédek (root nélkül, a GUI-ból)
def pm_run(cmd, env=None, timeout=90):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""
    return p.returncode, p.stdout


def pm_terms(term):
    return [w for w in (x.lstrip("-") for x in term.split()) if w]


def pm_apt_installed():
    rc, out = pm_run(["dpkg-query", "-W", "-f", "${Package}\t${db:Status-Abbrev}\t${Version}\t${binary:Summary}\n"])
    d = {}
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) >= 4 and p[1].startswith("ii"):
            d[p[0]] = (p[2], p[3])
    return d


def pm_apt_manual():
    rc, out = pm_run(["apt-mark", "showmanual"])
    return set(out.split())


def pm_apt_search(term):
    pats = [re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", w) for w in pm_terms(term)]
    rc, out = pm_run(["apt-cache", "search"] + pats)
    res = []
    for line in out.splitlines():
        name, _, desc = line.partition(" - ")
        if PM_APT_RE.match(name):
            res.append((name, desc))
    return res


def pm_fp_installed():
    if not pm_has_flatpak():
        return {}
    rc, out = pm_run(["flatpak", "list", "--system", "--app", "--columns=application,name,version,origin"])
    d = {}
    for line in out.splitlines():
        p = line.split("\t")
        if p and PM_FP_ID_RE.match(p[0]):
            d[p[0]] = (p[1] if len(p) > 1 and p[1] else p[0], p[2] if len(p) > 2 else "", p[3] if len(p) > 3 else "")
    return d


def pm_fp_search(term):
    if not pm_has_flatpak():
        return []
    rc, out = pm_run(["flatpak", "search", "--columns=application,name,description,remotes",
                      " ".join(pm_terms(term))], timeout=60)
    res = []
    for line in out.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and PM_FP_ID_RE.match(p[0]):
            res.append((p[0], p[1], p[2] if len(p) > 2 else "", p[3] if len(p) > 3 else ""))
    return res


def pm_apt_upgradable():
    rc, out = pm_run(["apt", "list", "--upgradable"], env=dict(os.environ, LC_ALL="C"))
    res = []
    for line in out.splitlines():
        m = re.match(r"^(\S+?)/\S+ (\S+) \S+ \[upgradable from: (\S+)\]", line)
        if m:
            res.append((m.group(1), m.group(3), m.group(2)))
    return res


def pm_fp_updates():
    if not pm_has_flatpak():
        return []
    rc, out = pm_run(["flatpak", "remote-ls", "--system", "--updates", "--app",
                      "--columns=application,name,version"], timeout=60)
    res = []
    for line in out.splitlines():
        p = line.split("\t")
        if p and PM_FP_ID_RE.match(p[0]):
            res.append((p[0], p[1] if len(p) > 1 and p[1] else p[0], p[2] if len(p) > 2 else ""))
    return res


def pm_apt_sim(action, name=None):
    """apt-get -s: mely csomagok települnének / törlődnének (szimuláció, root nélkül)."""
    cmd = ["apt-get", "-s", action] + ([name] if name else [])
    rc, out = pm_run(cmd, env=dict(os.environ, LC_ALL="C"))
    tag = "Inst" if action == "install" else "Remv"
    pk = []
    for line in out.splitlines():
        m = re.match(rf"^{tag} (\S+)", line)
        if m:
            pk.append(m.group(1))
    return rc, pk


def pm_score(name, term):
    n, t = name.lower(), term.lower().strip()
    if not t:
        return 3
    if n == t:
        return 0
    if n.startswith(t):
        return 1
    return 2 if t in n else 3


def pm_cache_size():
    tot = 0
    try:
        for e in os.scandir("/var/cache/apt/archives"):
            if e.is_file():
                tot += e.stat().st_size
    except OSError:
        pass
    return tot


def pm_hsize(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


# -- magyar ABC szerinti rendezés (az ikonok sorrendjéhez)
_HU_DI = ("dzs", "cs", "dz", "gy", "ly", "ny", "sz", "ty", "zs")
_HU_ORDER = "a b c cs d dz dzs e f g gy h i j k l ly m n ny o ö p q r s sz t ty u ü v w x y z zs".split()
_HU_BASE = str.maketrans("áéíóőúű", "aeioöuü")


def hu_key(s):
    t = s.lower().translate(_HU_BASE)
    out, i = [], 0
    while i < len(t):
        for d in _HU_DI:
            if t.startswith(d, i):
                out.append(_HU_ORDER.index(d) + 1)
                i += len(d)
                break
        else:
            ch = t[i]
            out.append(_HU_ORDER.index(ch) + 1 if ch in _HU_ORDER else 0)
            i += 1
    return (out, s.lower())


# ------------------------------------------------------------ felhasználók kezelése
US_NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")                 # új felhasználó neve
US_ANY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")      # meglévő név / csoportnév
US_UID_MIN, US_UID_MAX = 1000, 60000
US_ADMIN_GROUP = "sudo"


def us_shells():
    seen, out = set(), []
    try:
        with open("/etc/shells", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.startswith("/") and os.path.exists(s) and not s.endswith(("nologin", "/false")):
                    rp = os.path.realpath(s)
                    if rp not in seen:
                        seen.add(rp)
                        out.append(s)
    except OSError:
        pass
    return out or ["/bin/bash"]


def us_shadow_field(name):
    try:
        with open("/etc/shadow", encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split(":")
                if p[0] == name and len(p) > 1:
                    return p[1]
    except OSError:
        pass
    return None


def us_collect():
    groups = grp.getgrall()
    by_user = {}
    for g in groups:
        for m in g.gr_mem:
            by_user.setdefault(m, []).append(g.gr_name)
    gname = {g.gr_gid: g.gr_name for g in groups}
    users = []
    for u in pwd.getpwall():
        sh = us_shadow_field(u.pw_name)
        users.append({"name": u.pw_name, "uid": u.pw_uid, "gid": u.pw_gid, "group": gname.get(u.pw_gid, str(u.pw_gid)),
                      "full": u.pw_gecos.split(",")[0], "home": u.pw_dir, "shell": u.pw_shell,
                      "locked": bool(sh and sh.startswith("!")), "groups": sorted(by_user.get(u.pw_name, []))})
    return {"users": users,
            "groups": [{"name": g.gr_name, "gid": g.gr_gid, "members": list(g.gr_mem)} for g in groups],
            "shells": us_shells(), "admin_group": US_ADMIN_GROUP}


def us_target(r):
    name = r.get("name")
    if not isinstance(name, str) or not US_ANY_NAME_RE.match(name):
        raise RuntimeError("Érvénytelen felhasználónév.")
    try:
        u = pwd.getpwnam(name)
    except KeyError:
        raise RuntimeError("Nincs ilyen felhasználó.")
    if not US_UID_MIN <= u.pw_uid < US_UID_MAX:
        raise RuntimeError("A rendszerfiókok és a root itt nem módosíthatók.")
    return u


def us_password(pw):
    if not isinstance(pw, str) or not 6 <= len(pw) <= 128 or re.search(r"[\x00-\x1f\x7f]", pw):
        raise RuntimeError("A jelszó 6–128 karakter lehet, vezérlőkarakter nélkül.")
    return pw


def us_fullname(s):
    s = (s or "").strip() if isinstance(s, str) else ""
    if len(s) > 100 or re.search(r"[:,\x00-\x1f\x7f]", s):
        raise RuntimeError("A teljes név legfeljebb 100 karakter lehet, és nem tartalmazhat kettőspontot vagy vesszőt.")
    return s


def us_shell(sh):
    try:
        with open("/etc/shells", encoding="utf-8") as f:
            ok = {line.strip() for line in f if line.strip().startswith("/")}
    except OSError:
        ok = set()
    if not isinstance(sh, str) or sh not in ok:
        raise RuntimeError("Érvénytelen parancsértelmező (shell).")
    return sh


def us_groups(names):
    out = []
    for n in names or []:
        if not isinstance(n, str) or not US_ANY_NAME_RE.match(n):
            raise RuntimeError("Érvénytelen csoportnév.")
        try:
            grp.getgrnam(n)
        except KeyError:
            raise RuntimeError(f"Nincs ilyen csoport: {n}")
        out.append(n)
    return out


def us_admins_after(removed):
    try:
        mem = set(grp.getgrnam(US_ADMIN_GROUP).gr_mem)
    except KeyError:
        return None
    return mem - {removed}


def op_user_list(r):
    return "A felhasználók betöltve.", us_collect()


def op_user_add(r):
    name = r.get("name", "")
    if not isinstance(name, str) or not US_NAME_RE.match(name):
        raise RuntimeError("Érvénytelen felhasználónév: kisbetűvel vagy _ jellel kezdődjön, csak kisbetű, szám, _ és - lehet, "
                           "legfeljebb 32 karakter.")
    try:
        pwd.getpwnam(name)
        raise RuntimeError("Már van ilyen nevű felhasználó.")
    except KeyError:
        pass
    try:
        grp.getgrnam(name)
        raise RuntimeError("Már létezik ilyen nevű csoport.")
    except KeyError:
        pass
    full = us_fullname(r.get("fullname"))
    shell = us_shell(r.get("shell") or "/bin/bash")
    pw = us_password(r.get("password"))
    groups = us_groups(r.get("add_groups"))
    hrun(["useradd", "-m" if r.get("create_home", True) else "-M", "-s", shell, "-c", full, name])
    try:
        hrun(["chpasswd"], stdin_text=f"{name}:{pw}")
        if groups:
            hrun(["usermod", "-a", "-G", ",".join(groups), name])
        if r.get("force_change"):
            hrun(["chage", "-d", "0", name])
    except Exception:
        hrun(["userdel", "-r", name], check=False)       # félig kész fiók nem maradhat
        raise
    return f"A(z) {name} felhasználó létrehozva.", us_collect()


def op_user_edit(r):
    u = us_target(r)
    name = u.pw_name
    me = invoking_user()
    full = us_fullname(r.get("fullname"))
    if full != u.pw_gecos.split(",")[0]:
        hrun(["usermod", "-c", full, name])
    shell = r.get("shell")
    if shell and shell != u.pw_shell:
        hrun(["usermod", "-s", us_shell(shell), name])
    add, rm = us_groups(r.get("add_groups")), us_groups(r.get("rm_groups"))
    if US_ADMIN_GROUP in rm:
        if name == me:
            raise RuntimeError("Saját magadat nem veheted ki a(z) sudo csoportból.")
        left = us_admins_after(name)
        if left is not None and not left:
            raise RuntimeError("Az utolsó rendszergazdát nem lehet kivenni a(z) sudo csoportból.")
    pw = r.get("password")
    if pw:
        hrun(["chpasswd"], stdin_text=f"{name}:{us_password(pw)}")
    want_locked = bool(r.get("locked"))
    field = us_shadow_field(name) or ""
    now_locked = field.startswith("!")
    if want_locked and not now_locked:
        if name == me:
            raise RuntimeError("Saját fiókodat nem zárolhatod.")
        hrun(["usermod", "-L", name])
    elif not want_locked and now_locked:
        if field.lstrip("!*") == "":
            raise RuntimeError("A zárolás feloldásához új jelszót kell megadni (a fióknak most nincs jelszava).")
        hrun(["usermod", "-U", name])
    if r.get("force_change"):
        hrun(["chage", "-d", "0", name])
    if add:
        hrun(["usermod", "-a", "-G", ",".join(add), name])
    for g in rm:
        hrun(["gpasswd", "-d", name, g], check=False)
    return f"A(z) {name} felhasználó adatai mentve.", us_collect()


def op_user_delete(r):
    u = us_target(r)
    name = u.pw_name
    if name == invoking_user():
        raise RuntimeError("Saját magadat nem törölheted.")
    left = us_admins_after(name)
    if left is not None and not left and name in grp.getgrnam(US_ADMIN_GROUP).gr_mem:
        raise RuntimeError("Az utolsó rendszergazdát nem lehet törölni.")
    if subprocess.run(["pgrep", "-u", str(u.pw_uid)], capture_output=True).returncode == 0:
        raise RuntimeError("A felhasználó be van jelentkezve, vagy futnak a folyamatai: előbb jelentkeztesd ki.")
    hrun(["userdel"] + (["-r"] if r.get("remove_home") else []) + [name])
    return f"A(z) {name} felhasználó eltávolítva.", us_collect()


# ------------------------------------------------------------ önfrissítés (GitHub)
UPDATE_URL = "https://github.com/mszabi22/CiszterciLinux/blob/main/config/includes.chroot/usr/local/lib/ciszterci-admin/ciszterci-admin.py"
UPDATE_RAW = re.sub(r"^https://github\.com/([^/]+)/([^/]+)/blob/", r"https://raw.githubusercontent.com/\1/\2/", UPDATE_URL)
UPDATE_MAX = 8_000_000


def up_fetch(url=None):
    """A script letöltése (csak HTTPS, csak a raw.githubusercontent.com tárolóról)."""
    url = url or UPDATE_RAW
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != "raw.githubusercontent.com":
        raise RuntimeError("A frissítés csak a GitHub (raw.githubusercontent.com) HTTPS-címéről tölthető le.")
    req = urllib.request.Request(url, headers={"User-Agent": APP_NAME + "-updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(UPDATE_MAX + 1)
    if len(data) > UPDATE_MAX:
        raise RuntimeError("A letöltött fájl gyanúsan nagy, nem fogadom el.")
    return data


def up_validate(data):
    """Épségellenőrzés telepítés előtt: érvényes Python, és tényleg ennek a programnak a scriptje."""
    try:
        text = data.decode("utf-8")
        compile(text, "<frissítés>", "exec")
    except (UnicodeDecodeError, SyntaxError, ValueError) as e:
        raise RuntimeError(f"A letöltött fájl nem érvényes Python-script: {e}")
    m = re.search(r'^LIBDIR = "/usr/local/lib/([^"]+)"', text, re.M)
    if not m or m.group(1) != APP_NAME:
        raise RuntimeError(f"A letöltött fájl nem a(z) {APP_NAME} scriptje, ezért nem telepítem.")
    for marker in ("def helper_main", "def install_main", 'if __name__ == "__main__":'):
        if marker not in text:
            raise RuntimeError("A letöltött fájlból hiányzik egy alapvető rész, ezért nem telepítem.")
    return text


def up_diffstat(old, new):
    """(hozzáadott, törölt) sorok száma; old = None, ha nincs telepített példány."""
    if old is None:
        return None
    import difflib
    add = rem = 0
    for line in difflib.unified_diff(old.decode("utf-8", "replace").splitlines(),
                                     new.decode("utf-8", "replace").splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            add += 1
        elif line.startswith("-") and not line.startswith("---"):
            rem += 1
    return add, rem


def up_read_installed():
    try:
        with open(INSTALL_PATH, "rb") as f:
            return f.read()
    except OSError:
        return None


def up_install(data, keep_prev=True):
    """Az új script telepítése: a saját telepítője fut le, siker esetén ellenőrzés, hiba esetén visszaállítás."""
    import tempfile
    sha = hashlib.sha256(data).hexdigest()
    prev = INSTALL_PATH + ".prev"
    old = up_read_installed()
    tmpdir = tempfile.mkdtemp(prefix="admin-update-")
    try:
        os.chmod(tmpdir, 0o700)
        new = os.path.join(tmpdir, os.path.basename(INSTALL_PATH))
        with open(new, "wb") as f:
            f.write(data)
        os.chmod(new, 0o755)
        if keep_prev and old is not None:
            with open(prev + ".tmp", "wb") as f:
                f.write(old)
            os.replace(prev + ".tmp", prev)
        rc = hrun(["/usr/bin/python3", new, "--install", new], check=False)
        cur = up_read_installed()
        if rc != 0 or cur is None or hashlib.sha256(cur).hexdigest() != sha:
            if old is not None:
                with open(INSTALL_PATH + ".restore", "wb") as f:
                    f.write(old)
                os.chmod(INSTALL_PATH + ".restore", 0o755)
                os.replace(INSTALL_PATH + ".restore", INSTALL_PATH)
            raise RuntimeError("A telepítés nem sikerült, a korábbi verziót visszaállítottam (részletek a naplóban).")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return sha


def op_self_update(r):
    data = up_fetch()
    sha = hashlib.sha256(data).hexdigest()
    exp = r.get("sha256")
    if exp and exp != sha:
        raise RuntimeError("A GitHubon közben megváltozott a fájl: nem azt telepíteném, amit megerősítettél. "
                           "Keress újra frissítést.")
    up_validate(data)
    hlog(f"Letöltve: {len(data)} bájt, SHA-256: {sha}")
    up_install(data)
    return f"A(z) {APP_TITLE} frissítve (SHA-256: {sha[:12]}…). Az előző verzió mentve maradt."


def op_self_rollback(r):
    prev = INSTALL_PATH + ".prev"
    try:
        with open(prev, "rb") as f:
            data = f.read()
    except OSError:
        raise RuntimeError("Nincs mentett előző verzió.")
    up_validate(data)
    up_install(data, keep_prev=False)
    return "Az előző verzió visszaállítva."


OPS = {"login": op_login, "pkg": op_pkg, "deb": op_deb, "debremove": op_debremove,
       "chrony": op_chrony, "chrony_ctl": op_chrony_ctl, "time": op_time,
       "wg_list": op_wg_list, "wg_save": op_wg_save, "wg_up": op_wg_up, "wg_down": op_wg_down,
       "wg_delete": op_wg_delete, "wg_autostart": op_wg_autostart,
       "share_setup": op_share_setup, "share_list": op_share_list, "share_save": op_share_save,
       "share_delete": op_share_delete, "share_toggle": op_share_toggle, "share_pw": op_share_pw,
       "share_pwdel": op_share_pwdel, "share_restart": op_share_restart,
       "ad_join": op_ad_join, "ad_leave": op_ad_leave,
       "pm_refresh": op_pm_refresh, "pm_upgrade": op_pm_upgrade, "pm_install": op_pm_install,
       "pm_remove": op_pm_remove, "pm_cleanup": op_pm_cleanup, "pm_flatpak_setup": op_pm_flatpak_setup,
       "user_list": op_user_list, "user_add": op_user_add, "user_edit": op_user_edit,
       "user_delete": op_user_delete,
       "self_update": op_self_update, "self_rollback": op_self_rollback}


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
FRESH_AUTH_OPS = ("login", "self_update", "self_rollback")      # ezeknél a művelet mindig új hitelesítést kér (nem használja a már hitelesített segédet)


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

    def close(self):
        """A segédfolyamat leállítása: a következő hívás új hitelesítést kér."""
        p, self.p = self.p, None
        if p is not None and p.poll() is None:
            try:
                p.stdin.close()
            except OSError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.terminate()

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


KJ_TOOLS = ("xfce4-display-settings", "arandr", "lxrandr")


def kj_tool():
    for t in KJ_TOOLS:
        if shutil.which(t):
            return t
    return None


def kj_summary():
    """A csatlakoztatott kijelzők jelenlegi állapota (xrandr). None: nem olvasható."""
    try:
        p = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    res, cur = [], None
    for line in p.stdout.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)(?: (primary))?(?: (\d+x\d+)\+(-?\d+)\+(-?\d+))?", line)
        if m:
            cur = None
            if m.group(2) == "connected":
                cur = {"name": m.group(1), "primary": bool(m.group(3)), "mode": m.group(4), "rate": ""}
                res.append(cur)
            continue
        if cur and cur["mode"]:
            mm = re.match(r"^\s+(\d+x\d+)i?\s+(.*)$", line)
            if mm and mm.group(1) == cur["mode"]:
                r = re.search(r"([\d.]+)\*", mm.group(2))
                if r:
                    cur["rate"] = r.group(1)
    return res


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


# ------------------------------------------------------------- XP (Luna) kinézet
XP_DUPLA_KATTINTAS = False   # True: a kezdőlapon dupla kattintás nyit (mint az eredeti XP-ben)

_SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><defs>'
             '<linearGradient id="a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5b97f5"/>'
             '<stop offset="1" stop-color="#1a3fa8"/></linearGradient>'
             '<linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6f4ea"/>'
             '<stop offset="1" stop-color="#b3af9c"/></linearGradient>'
             '<linearGradient id="y" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff0a0"/>'
             '<stop offset="1" stop-color="#e5b53a"/></linearGradient>'
             '<linearGradient id="c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d6ecff"/>'
             '<stop offset="1" stop-color="#4a8fe6"/></linearGradient>'
             '<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7fdc6c"/>'
             '<stop offset="1" stop-color="#1f8f1f"/></linearGradient></defs>')

XP_SVG = {
    "login": '<rect x="3" y="5" width="42" height="30" rx="3" fill="url(#b)" stroke="#6e6a58"/>'
             '<rect x="7" y="9" width="34" height="22" fill="url(#a)" stroke="#0b2a7a"/>'
             '<circle cx="24" cy="17" r="5" fill="#fff"/><path d="M14 31 C14 23 34 23 34 31 Z" fill="#fff"/>'
             '<rect x="19" y="35" width="10" height="4" fill="#a8a493"/>'
             '<rect x="12" y="39" width="24" height="4" rx="2" fill="url(#b)" stroke="#6e6a58"/>',
    "remote": '<circle cx="24" cy="24" r="15" fill="none" stroke="#fff" stroke-width="8"/>'
              '<circle cx="24" cy="24" r="15" fill="none" stroke="#e03a2a" stroke-width="8" '
              'stroke-dasharray="11.78 11.78"/>'
              '<circle cx="24" cy="24" r="19" fill="none" stroke="#7a1a1a"/>'
              '<circle cx="24" cy="24" r="11" fill="none" stroke="#7a1a1a"/>',
    "cloud": '<g fill="#1d4fa0" stroke="#1d4fa0" stroke-width="2.4"><circle cx="15" cy="28" r="8"/>'
             '<circle cx="25" cy="21" r="10"/><circle cx="34" cy="28" r="8"/><rect x="15" y="28" width="19" height="8"/></g>'
             '<g fill="url(#c)"><circle cx="15" cy="28" r="8"/><circle cx="25" cy="21" r="10"/>'
             '<circle cx="34" cy="28" r="8"/><rect x="15" y="28" width="19" height="8"/></g>'
             '<path d="M24 34 V22 M19 27 L24 22 L29 27" stroke="#fff" stroke-width="3" fill="none" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
    "domain": '<path d="M24 18 V26 M12 26 H36 M12 26 V30 M36 26 V30" stroke="#5a5748" stroke-width="2" fill="none"/>'
              '<rect x="12" y="4" width="24" height="14" rx="2" fill="url(#b)" stroke="#6e6a58"/>'
              '<rect x="16" y="8" width="12" height="2" fill="#6e6a58"/><rect x="16" y="12" width="12" height="2" fill="#6e6a58"/>'
              '<circle cx="32" cy="11" r="2" fill="#3ccf3c"/>'
              '<rect x="3" y="30" width="18" height="12" rx="1.5" fill="url(#a)" stroke="#0b2a7a"/>'
              '<rect x="27" y="30" width="18" height="12" rx="1.5" fill="url(#a)" stroke="#0b2a7a"/>',
    "vpn": '<path d="M24 3 L41 9 V23 C41 34 33 41 24 45 C15 41 7 34 7 23 V9 Z" fill="url(#a)" stroke="#0b2a7a" stroke-width="1.5"/>'
           '<path d="M19 23 V20 A5 5 0 0 1 29 20 V23" stroke="#fff" stroke-width="3" fill="none"/>'
           '<rect x="16" y="23" width="16" height="12" rx="2" fill="#ffd451" stroke="#a77c00"/>',
    "share": '<path d="M4 10 H18 L21 14 H44 V40 H4 Z" fill="#e5b53a" stroke="#a77c00"/>'
             '<path d="M4 19 H44 V40 H4 Z" fill="url(#y)" stroke="#a77c00"/>'
             '<circle cx="36" cy="34" r="9" fill="url(#a)" stroke="#fff" stroke-width="1.5"/>'
             '<path d="M31 34 H40 M36 30 L40 34 L36 38" stroke="#fff" stroke-width="2.5" fill="none" '
             'stroke-linecap="round" stroke-linejoin="round"/>',
    "time": '<circle cx="24" cy="24" r="20" fill="url(#a)" stroke="#0b2a7a"/>'
            '<circle cx="24" cy="24" r="16" fill="#fff" stroke="#8a8a8a"/>'
            '<path d="M24 10 V13 M24 35 V38 M10 24 H13 M35 24 H38" stroke="#333" stroke-width="2"/>'
            '<path d="M24 24 V15" stroke="#222" stroke-width="2.5" stroke-linecap="round"/>'
            '<path d="M24 24 L32 28" stroke="#222" stroke-width="2" stroke-linecap="round"/>'
            '<path d="M24 24 L19 31" stroke="#d22" stroke-width="1.2"/><circle cx="24" cy="24" r="2" fill="#222"/>',
    "system": '<rect x="3" y="7" width="30" height="24" rx="2" fill="url(#b)" stroke="#6e6a58"/>'
              '<rect x="6" y="10" width="24" height="18" fill="url(#a)" stroke="#0b2a7a"/>'
              '<rect x="14" y="31" width="8" height="4" fill="#a8a493"/>'
              '<rect x="9" y="35" width="18" height="4" rx="2" fill="url(#b)" stroke="#6e6a58"/>'
              '<rect x="35" y="14" width="10" height="26" rx="1.5" fill="url(#b)" stroke="#6e6a58"/>'
              '<rect x="37" y="18" width="6" height="2" fill="#6e6a58"/><circle cx="40" cy="35" r="1.5" fill="#3ccf3c"/>'
              '<path d="M12 19 L17 24 L25 14" stroke="#fff" stroke-width="3" fill="none" '
              'stroke-linecap="round" stroke-linejoin="round"/>',
    "back": '<circle cx="24" cy="24" r="21" fill="url(#g)" stroke="#1d6f1d" stroke-width="2"/>'
            '<path d="M27 12 L15 24 L27 36 M15 24 H37" stroke="#fff" stroke-width="5" fill="none" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
    "fwd": '<circle cx="24" cy="24" r="21" fill="url(#g)" stroke="#1d6f1d" stroke-width="2"/>'
           '<path d="M21 12 L33 24 L21 36 M33 24 H11" stroke="#fff" stroke-width="5" fill="none" '
           'stroke-linecap="round" stroke-linejoin="round"/>',
    "up": '<circle cx="24" cy="24" r="21" fill="url(#g)" stroke="#1d6f1d" stroke-width="2"/>'
          '<path d="M12 27 L24 15 L36 27 M24 15 V37" stroke="#fff" stroke-width="5" fill="none" '
          'stroke-linecap="round" stroke-linejoin="round"/>',
}
XP_FALLBACK_ICON = {"login": "system-users", "remote": "help-browser", "cloud": "folder-remote",
                    "domain": "network-workgroup", "vpn": "network-vpn", "share": "folder-publicshare",
                    "time": "preferences-system-time", "system": "computer",
                    "back": "go-previous", "fwd": "go-next", "up": "go-up"}

XP_SVG["pkg"] = ('<path d="M6 16 L24 8 L42 16 L24 24 Z" fill="#ecd093" stroke="#8a5f1d"/>'
                 '<path d="M6 16 V34 L24 42 V24 Z" fill="#dcae60" stroke="#8a5f1d"/>'
                 '<path d="M42 16 V34 L24 42 V24 Z" fill="#c28f42" stroke="#8a5f1d"/>'
                 '<path d="M15 12 L33 20" stroke="#fff6dc" stroke-width="3"/>'
                 '<circle cx="35" cy="35" r="10" fill="url(#g)" stroke="#1d6f1d" stroke-width="1.5"/>'
                 '<path d="M35 30 V40 M31 36 L35 41 L39 36" stroke="#fff" stroke-width="2.8" fill="none" '
                 'stroke-linecap="round" stroke-linejoin="round"/>')
XP_FALLBACK_ICON["pkg"] = "system-software-install"
XP_SVG["users"] = ('<circle cx="32" cy="14" r="6" fill="#f5d6a8" stroke="#8a5f1d"/>'
                   '<path d="M21 36 C21 26 43 26 43 36 Z" fill="#8fbdf2" stroke="#0b2a7a"/>'
                   '<circle cx="17" cy="18" r="7" fill="#f5c27a" stroke="#8a5f1d"/>'
                   '<path d="M4 42 C4 29 30 29 30 42 Z" fill="url(#a)" stroke="#0b2a7a"/>')
XP_SVG["question"] = ('<circle cx="24" cy="24" r="20" fill="url(#a)" stroke="#0b2a7a" stroke-width="1.5"/>'
                      '<path d="M17 19 C17 10 31 10 31 19 C31 25 24 25 24 31" stroke="#fff" stroke-width="5" fill="none" '
                      'stroke-linecap="round"/><circle cx="24" cy="38" r="3" fill="#fff"/>')
XP_FALLBACK_ICON["users"] = "system-users"
XP_FALLBACK_ICON["question"] = "dialog-question"
XP_SVG["printer"] = ('<rect x="12" y="5" width="24" height="16" fill="#fff" stroke="#8a8a8a"/>'
                    '<path d="M17 10 H31 M17 14 H31" stroke="#aab" stroke-width="1.5"/>'
                    '<path d="M4 20 H44 V35 H4 Z" fill="url(#b)" stroke="#6e6a58" stroke-linejoin="round"/>'
                    '<rect x="11" y="30" width="26" height="13" fill="#fff" stroke="#8a8a8a"/>'
                    '<path d="M16 35 H32 M16 38.5 H27" stroke="#aab" stroke-width="1.5"/>'
                    '<circle cx="38" cy="25" r="2" fill="#3ccf3c"/>')
XP_FALLBACK_ICON["printer"] = "printer"
XP_SVG["display"] = ('<rect x="7" y="5" width="34" height="24" rx="2" fill="url(#b)" stroke="#6e6a58"/>'
                     '<rect x="10" y="8" width="28" height="18" fill="url(#a)" stroke="#0b2a7a"/>'
                     '<path d="M10 26 L19 15 L25 21 L30 17 L38 26 Z" fill="#7fd36a"/>'
                     '<circle cx="32" cy="13" r="2.5" fill="#ffe36a"/>'
                     '<rect x="20" y="29" width="8" height="5" fill="#a8a493"/>'
                     '<rect x="13" y="34" width="22" height="4" rx="2" fill="url(#b)" stroke="#6e6a58"/>')
XP_FALLBACK_ICON["display"] = "video-display"
XP_SVG["update"] = ('<circle cx="22" cy="22" r="18" fill="url(#a)" stroke="#0b2a7a"/>'
                    '<ellipse cx="22" cy="22" rx="7" ry="18" fill="none" stroke="#fff" stroke-width="1.5"/>'
                    '<path d="M4 22 H40 M7 13 H37 M7 31 H37" stroke="#fff" stroke-width="1.5" fill="none"/>'
                    '<circle cx="36" cy="36" r="10" fill="url(#g)" stroke="#1d6f1d" stroke-width="1.5"/>'
                    '<path d="M36 41 V31 M31 36 L36 31 L41 36" stroke="#fff" stroke-width="3" fill="none" '
                    'stroke-linecap="round" stroke-linejoin="round"/>')
XP_FALLBACK_ICON["update"] = "software-update-available"
XP_CSS = """
window.xp, window.xp.background, window.xp.dialog { background-color: #ECE9D8; background-image: none; color: #000000; }
.xp box, .xp grid, .xp buttonbox, .xp .dialog-vbox, .xp .dialog-action-area { background-color: transparent; background-image: none; }
.xp * { font-family: Tahoma, "DejaVu Sans", "Noto Sans", sans-serif; font-size: 9pt; }
.xp .monospace, .xp textview.monospace { font-family: monospace; }
.xp label, .xp checkbutton, .xp radiobutton { color: #000000; }
.xp label:disabled { color: #ACA899; }
.xp separator { background-color: #ACA899; min-height: 1px; min-width: 1px; }
.xp scrolledwindow.xp-scroll, .xp scrolledwindow.xp-scroll viewport { background-color: #ECE9D8; }
.xp textview text { background-color: #FFFFFF; color: #000000; }

.xp button { background-image: linear-gradient(to bottom, #FFFFFF, #ECEBE5 85%, #D6D0C5);
             background-color: #ECEBE5; border: 1px solid #003C74; border-radius: 3px;
             padding: 3px 12px; color: #000000; box-shadow: none; text-shadow: none; min-height: 0; }
.xp button:hover { box-shadow: inset 0 0 0 2px #FFC83C; }
.xp button:active { background-image: linear-gradient(to bottom, #CDCAC3, #E3E3DB); box-shadow: none; }
.xp button:disabled { color: #ACA899; border-color: #C9C7BA; background-image: none; background-color: #F4F2E8; }

.xp entry, .xp spinbutton { background-color: #FFFFFF; color: #000000; border: 1px solid #7F9DB9;
                            border-radius: 0; box-shadow: none; padding: 2px 3px; min-height: 0; }
.xp entry:focus { border-color: #316AC5; }
.xp frame > border { border: 1px solid #D0D0BF; border-radius: 3px; }

.xp progressbar trough { background-color: #FFFFFF; border: 1px solid #686868; border-radius: 3px; min-height: 12px; }
.xp progressbar progress { background-image: repeating-linear-gradient(to right, #37D237 0px, #37D237 7px, #FFFFFF 7px, #FFFFFF 9px);
                           border: none; border-radius: 0; min-height: 10px; }

.xp menubar { background-image: none; background-color: #ECE9D8; border-bottom: 1px solid #ACA899; }
.xp menubar > menuitem { padding: 3px 8px; }
.xp menubar > menuitem:hover { background-color: #316AC5; }
.xp menubar > menuitem:hover label { color: #FFFFFF; }

.xp .xp-toolbar { background-image: linear-gradient(to bottom, #F7F6EF, #ECE9D8); padding: 2px 4px;
                  border-bottom: 1px solid #ACA899; }
.xp button.xp-tool { background-image: none; background-color: transparent; border: 1px solid transparent;
                     border-radius: 3px; padding: 2px 6px; box-shadow: none; }
.xp button.xp-tool:hover { border-color: #ACA899; background-image: linear-gradient(to bottom, #FFFFFF, #E8E6DA); box-shadow: none; }
.xp button.xp-tool:disabled { background-image: none; background-color: transparent; border-color: transparent; opacity: 0.45; }
.xp .xp-addrrow { background-color: #ECE9D8; padding: 3px 6px; border-bottom: 1px solid #ACA899; }
.xp .xp-addr { background-color: #FFFFFF; border: 1px solid #7F9DB9; padding: 2px 4px; }

.xp .xp-left { background-image: linear-gradient(to bottom, #7BA2E7, #6375D6); padding: 12px 10px; }
.xp .xp-tb-head { background-image: linear-gradient(to right, #FFFFFF, #C6D3F7); border-radius: 6px 6px 0px 0px; padding: 4px 8px; }
.xp .xp-tb-head label { color: #215DC6; font-weight: bold; }
.xp .xp-tb-body { background-color: #D6DFF7; border-style: solid; border-color: #FFFFFF; border-width: 0px 1px 1px 1px; padding: 6px 8px; }
.xp label.xp-det-title { font-weight: bold; }
.xp button.xp-link { background-image: none; background-color: transparent; border: none; box-shadow: none; padding: 2px 0px; }
.xp button.xp-link:hover { background-image: none; background-color: transparent; box-shadow: none; }
.xp button.xp-link label { color: #215DC6; }
.xp button.xp-link:hover label { color: #428EFF; text-decoration: underline; }

.xp .xp-home, .xp .xp-home viewport, .xp .xp-home flowbox { background-color: #FFFFFF; }
.xp .xp-home flowboxchild:hover { background-color: #EAF1FB; }
.xp .xp-home flowboxchild:selected { background-color: #316AC5; }
.xp .xp-home flowboxchild:selected label { color: #FFFFFF; }

.xp .xp-pagehead { background-image: linear-gradient(to right, #FFFFFF, #CCD9F5); border-bottom: 1px solid #7F9DB9; padding: 10px 18px; }
.xp label.xp-pagetitle { font-size: 15pt; font-weight: bold; color: #1D3E8F; }
.xp label.xp-head { color: #0046D5; border-bottom: 1px solid #D0D0BF; padding-bottom: 2px; }
.xp .xp-status { background-color: #ECE9D8; border-top: 1px solid #ACA899; }
.xp treeview.view { background-color: #FFFFFF; color: #000000; }
.xp treeview.view:selected { background-color: #316AC5; color: #FFFFFF; }
.xp treeview header button { border-radius: 0px; padding: 2px 6px; border: 1px solid #ACA899;
                             background-image: linear-gradient(to bottom, #FFFFFF, #EBEADB); box-shadow: none; }
.xp treeview header button:hover { box-shadow: inset 0 -2px 0 0 #FFC83C; }
.xp scrolledwindow.xp-list { border: 1px solid #7F9DB9; }
.xp notebook > header { background-color: #ECE9D8; border: none; }
.xp notebook > header > tabs > tab { padding: 4px 14px; border: 1px solid #919B9C; border-radius: 3px 3px 0px 0px;
                                     background-image: linear-gradient(to bottom, #FFFFFF, #ECE9D8); color: #000000; }
.xp notebook > header > tabs > tab:checked { background-image: none; background-color: #FCFCFE; border-top: 2px solid #FFC83C; }
.xp notebook > stack { background-color: #FCFCFE; border: 1px solid #919B9C; }
"""


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

    def xp_image(kind, size):
        """XP-szerű ikon (beágyazott SVG); ha az SVG-betöltő hiányzik, a téma ikonja."""
        svg = _SVG_HEAD + XP_SVG.get(kind, "") + "</svg>"
        try:
            ld = GdkPixbuf.PixbufLoader.new_with_type("svg")
            ld.set_size(size, size)
            ld.write(svg.encode("utf-8"))
            ld.close()
            return Gtk.Image.new_from_pixbuf(ld.get_pixbuf())
        except Exception:
            return Gtk.Image.new_from_icon_name(XP_FALLBACK_ICON.get(kind, "image-missing"), Gtk.IconSize.DIALOG)

    def xp_apply_css():
        from gi.repository import Gdk
        try:   # sötét rendszertéma mellett is a világos változat (egységes megjelenés)
            Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", False)
        except Exception:
            pass
        prov = Gtk.CssProvider()
        try:
            prov.load_from_data(XP_CSS.encode("utf-8"))
        except GLib.Error as e:
            print("XP-stílus betöltési hiba:", e.message, file=sys.stderr)
            return
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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
            self.sh_data, self.sh_loaded, self.sh_editing = {}, False, None
            self.sh_users, self.sh_edit_avail = [], True

            self.get_style_context().add_class("xp")
            xp_apply_css()
            pages = [
                ("Bejelentkező ablak", self.page_login, "login",
                 "A bejelentkező képernyő (LightDM) megjelenésének és működésének beállítása."),
                ("Távoli segítség", self.page_remote, "remote",
                 "Programok, amelyekkel egy rendszergazda távolról segíthet."),
                ("Felhő tárhely", self.page_cloud, "cloud",
                 "Felhő tárhely kliens (Nextcloud) telepítése és eltávolítása."),
                ("Tartományba léptetés", self.page_domain, "domain",
                 "A gép felvétele a tartományba (Active Directory), illetve kivétele onnan."),
                ("WireGuard VPN", self.page_wg, "vpn",
                 "VPN-profilok importálása, kezelése, a VPN ki- és bekapcsolása."),
                ("Mappamegosztás", self.page_share, "share",
                 "Mappák megosztása a hálózaton (Samba), jogosultságokkal."),
                ("Rendszeridő", self.page_time, "time",
                 "Dátum, idő és az internetes időszinkron beállítása."),
                ("Rendszer", self.page_system, "system",
                 "Rendszergazdai eszközök, régi kernelek törlése és egyéb karbantartás."),
                ("Csomagkezelő", self.page_pkg, "pkg",
                 "Programok keresése, telepítése, eltávolítása, rendszerfrissítés és takarítás (apt és Flatpak)."),
                ("Kijelző", self.page_display, "display",
                 "A képernyő beállítása: felbontás, képfrissítés, tájolás, több monitor (kijelzőbeállító)."),
                ("Vezérlőpult frissítése", self.page_update, "update",
                 "A program legújabb verziójának letöltése a GitHubról és telepítése (visszaállítható)."),
                ("Nyomtatók", self.page_printers, "printer",
                 "Nyomtatók hozzáadása, eltávolítása és beállítása (system-config-printer)."),
                ("Felhasználók", self.page_users, "users",
                 "Helyi felhasználói fiókok: hozzáadás, eltávolítás, csoporttagságok és tulajdonságok szerkesztése.")]
            pages.sort(key=lambda p: hu_key(p[0]))      # az ikonok magyar ABC-sorrendben
            self.pages_meta = pages
            self.page_names = []
            self.wg_idx = [p[0] for p in pages].index("WireGuard VPN")
            self.sh_idx = [p[0] for p in pages].index("Mappamegosztás")
            self.pm_idx = [p[0] for p in pages].index("Csomagkezelő")
            self.us_idx = [p[0] for p in pages].index("Felhasználók")
            self.pm_loaded, self.pm_seq = False, 0
            self.nav_hist, self.nav_pos = [-1], 0

            outer = Gtk.Box(orientation=V)
            self.add(outer)
            outer.pack_start(self.xp_toolbar(), False, False, 0)
            body = Gtk.Box(orientation=H)
            outer.pack_start(body, True, True, 0)
            self.stack = Gtk.Stack()
            self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
            self.stack.add_named(self.home_view(), "home")
            for i, (title, builder, kind, _desc) in enumerate(pages):
                self._build_kind = kind
                sw = Gtk.ScrolledWindow()
                sw.get_style_context().add_class("xp-scroll")
                w = builder()
                sw.add(getattr(w, "xp_root", w))
                self.stack.add_named(sw, f"p{i}")
                self.page_names.append(f"p{i}")
            self._build_kind = None
            body.pack_start(self.stack, True, True, 0)

            bottom = Gtk.Box(orientation=V, spacing=4)
            bottom.set_border_width(6)
            bottom.get_style_context().add_class("xp-status")
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
            outer.pack_start(bottom, False, False, 0)
            self.show_all()
            self.progress.hide()
            self.go(-1, record=False)
            self.refresh_status()

        # ------------------------------------------------ XP-s keret: menü, eszköztár, navigáció
        def xp_toolbar(self):
            wrap = Gtk.Box(orientation=V)
            bar = Gtk.Box(spacing=2)
            bar.get_style_context().add_class("xp-toolbar")

            def tb(kind, text, cb):
                b = Gtk.Button()
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.get_style_context().add_class("xp-tool")
                box = Gtk.Box(spacing=5)
                box.pack_start(xp_image(kind, 24), False, False, 0)
                if text:
                    box.pack_start(Gtk.Label(label=text), False, False, 0)
                b.add(box)
                b.connect("clicked", cb)
                bar.pack_start(b, False, False, 0)
                return b
            self.b_back = tb("back", "Vissza", lambda *_: self.nav_step(-1))
            self.b_fwd = tb("fwd", "", lambda *_: self.nav_step(1))
            self.b_up = tb("up", "Fel", lambda *_: self.go(-1))
            wrap.pack_start(bar, False, False, 0)
            return wrap

        def home_view(self):
            sw = Gtk.ScrolledWindow()
            sw.get_style_context().add_class("xp-home")
            fb = Gtk.FlowBox()
            fb.set_valign(Gtk.Align.START)
            fb.set_homogeneous(True)
            fb.set_min_children_per_line(2)
            fb.set_max_children_per_line(6)
            fb.set_row_spacing(6)
            fb.set_column_spacing(6)
            fb.set_border_width(14)
            fb.set_selection_mode(Gtk.SelectionMode.SINGLE)
            fb.set_activate_on_single_click(not XP_DUPLA_KATTINTAS)
            for title, _b, kind, desc in self.pages_meta:
                it = Gtk.Box(orientation=V, spacing=4)
                it.set_border_width(8)
                it.pack_start(xp_image(kind, 48), False, False, 0)
                l = Gtk.Label(label=title)
                l.set_justify(Gtk.Justification.CENTER)
                l.set_line_wrap(True)
                l.set_max_width_chars(14)
                it.pack_start(l, False, False, 0)
                it.set_tooltip_text(desc)
                fb.add(it)
            fb.connect("child-activated", lambda _fb, ch: self.go(ch.get_index()))
            sw.add(fb)
            return sw

        def go(self, idx, record=True):
            if record and idx != self.nav_hist[self.nav_pos]:
                del self.nav_hist[self.nav_pos + 1:]
                self.nav_hist.append(idx)
                self.nav_pos += 1
            if idx < 0:
                self.stack.set_visible_child_name("home")
            else:
                self.stack.set_visible_child_name(self.page_names[idx])
                if idx == self.wg_idx and not self.wg_loaded and pkg_ok("wireguard-tools"):
                    self.wg_refresh()
                if idx == self.sh_idx and not self.sh_loaded and pkg_ok("samba"):
                    self.sh_refresh()
                if idx == self.pm_idx and not self.pm_loaded:
                    self.pm_on_show()
                if idx == self.us_idx and not self.us_loaded:
                    self.us_on_show()
            self.b_back.set_sensitive(self.nav_pos > 0)
            self.b_fwd.set_sensitive(self.nav_pos < len(self.nav_hist) - 1)
            self.b_up.set_sensitive(idx >= 0)

        def nav_step(self, d):
            p = self.nav_pos + d
            if 0 <= p < len(self.nav_hist):
                self.nav_pos = p
                self.go(self.nav_hist[p], record=False)

        # ---------------------------------------------------------- segédek
        def mk_page(self, title, sub=""):
            root = Gtk.Box(orientation=V)
            hd = Gtk.Box(spacing=12)
            hd.get_style_context().add_class("xp-pagehead")
            kind = getattr(self, "_build_kind", None)
            if kind:
                hd.pack_start(xp_image(kind, 40), False, False, 0)
            tx = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(label=title, xalign=0)
            t.get_style_context().add_class("xp-pagetitle")
            tx.pack_start(t, False, False, 0)
            if sub:
                tx.pack_start(self.lab(sub), False, False, 0)
            hd.pack_start(tx, True, True, 0)
            root.pack_start(hd, False, False, 0)
            box = Gtk.Box(orientation=V, spacing=8)
            box.set_border_width(18)
            root.pack_start(box, True, True, 0)
            box.xp_root = root
            return box

        def lab(self, text):
            l = Gtk.Label(label=text, xalign=0)
            l.set_line_wrap(True)
            return l

        def head(self, box, text):
            l = Gtk.Label(xalign=0)
            l.set_markup(f"<b>{text}</b>")
            l.get_style_context().add_class("xp-head")
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
            d, area = self.xp_dialog("Megerősítés", "question", "", "OK")
            l = Gtk.Label(label=text, xalign=0)
            l.set_line_wrap(True)
            l.set_max_width_chars(52)
            for m in ("top", "bottom", "start", "end"):
                getattr(l, f"set_margin_{m}")(18)
            area.pack_start(l, True, True, 0)
            d.show_all()
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
                    fresh = op in FRESH_AUTH_OPS and not self.helper_injected
                    h = Helper() if fresh else (self.hv if (self.hv and op in VPN_OPS) else self.h)
                    try:
                        rc, msg = h.call(dict(params, op=op), on_log=lambda m: GLib.idle_add(self.log, m))
                        data = h.data
                    finally:
                        if fresh:
                            h.close()
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
            if hasattr(self, "up_inst"):
                self.up_show_installed()
            if hasattr(self, "kj_btn"):
                tool = kj_tool()
                self.kj_btn.set_sensitive(bool(tool))
                self.kj_inst.set_sensitive(not tool)
                self.kj_hint.set_text(f"A megnyitandó program: {tool}." if tool else
                                      "⚠ Nincs kijelzőbeállító program telepítve: telepítsd az alábbi gombbal.")
            if hasattr(self, "pr_btn"):
                ok = pkg_ok("system-config-printer")
                self.pr_btn.set_sensitive(ok)
                if not ok:
                    hint = "⚠ A nyomtatókezelő nincs telepítve: előbb telepítsd fent."
                elif svc_active("cups"):
                    hint = "● A CUPS nyomtatószolgáltatás fut."
                else:
                    hint = ("○ A CUPS nyomtatószolgáltatás nem fut, ezért a nyomtatók nem érhetők el "
                            "(indítás: sudo systemctl enable --now cups).")
                self.pr_hint.set_text(hint)
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
            if hasattr(self, "sh_ctrls"):
                ok = pkg_ok("samba")
                for w in self.sh_ctrls:
                    w.set_sensitive(ok)
                if not ok:
                    hint = "⚠ A Samba nincs telepítve: előbb telepítsd fent."
                elif svc_active("smbd"):
                    hint = ("● A Samba fut. Ha a gépen tűzfal is van, a 445/tcp portot (és a névkereséshez a "
                            "139/tcp, 137–138/udp portot) engedélyezni kell. "
                            "Megosztás létrehozásához, módosításához és törléséhez rendszergazdai jelszó kell.")
                else:
                    hint = "○ A Samba szolgáltatás nem fut: próbáld a „Samba újraindítása” gombot."
                self.sh_hint.set_text(hint)
                if ok and not self.sh_loaded and self.stack.get_visible_child_name() == self.page_names[self.sh_idx]:
                    self.sh_refresh()

        # ------------------------------------------------ Csomagkezelő (apt + Flatpak)
        def pm_badge(self, src, remote=""):
            from xml.sax.saxutils import escape
            if src == "apt":
                return f'<span background="{PM_APT_COLOR}" foreground="#FFFFFF"><b> apt </b></span>'
            tail = f" · {escape(remote)}" if remote else ""
            return f'<span background="{PM_FP_COLOR}" foreground="#FFFFFF"><b> Flatpak{tail} </b></span>'

        def pm_src_text(self, src, remote=""):
            return "apt – Debian csomagtár" if src == "apt" else f"Flatpak – {remote or 'flathub'} tároló"

        def page_pkg(self):
            b = self.mk_page("Csomagkezelő",
                             "Programok keresése, telepítése és eltávolítása az apt (Debian-tárolók) és a Flatpak "
                             "(Flathub) közös felületén, rendszerfrissítés és takarítás.")
            legend = Gtk.Label(xalign=0)
            legend.set_use_markup(True)
            legend.set_markup(f'Forrás jelölése:  {self.pm_badge("apt")} Debian csomagtár     '
                              f'{self.pm_badge("flatpak", "flathub")} Flatpak-tároló (általában Flathub)')
            b.pack_start(legend, False, False, 0)
            nb = Gtk.Notebook()
            nb.append_page(self.pm_tab_search(), Gtk.Label(label="Keresés és telepítés"))
            nb.append_page(self.pm_tab_updates(), Gtk.Label(label="Frissítések"))
            nb.append_page(self.pm_tab_clean(), Gtk.Label(label="Karbantartás"))
            b.pack_start(nb, True, True, 0)
            return b

        def pm_list_view(self, store, columns):
            from gi.repository import Pango
            tv = Gtk.TreeView(model=store)
            for title, idx, markup, expand, sortcol in columns:
                r = Gtk.CellRendererText()
                if expand:
                    r.set_property("ellipsize", Pango.EllipsizeMode.END)
                col = Gtk.TreeViewColumn(title, r, **({"markup": idx} if markup else {"text": idx}))
                col.set_resizable(True)
                col.set_expand(expand)
                if sortcol is not None:
                    col.set_sort_column_id(sortcol)
                tv.append_column(col)
            sw = Gtk.ScrolledWindow()
            sw.get_style_context().add_class("xp-list")
            sw.set_min_content_height(300)
            sw.add(tv)
            return tv, sw

        def pm_tab_search(self):
            v = Gtk.Box(orientation=V, spacing=8)
            v.set_border_width(10)
            row = Gtk.Box(spacing=6)
            self.pm_entry = Gtk.Entry()
            self.pm_entry.set_placeholder_text("Program neve vagy leírása…")
            self.pm_entry.connect("activate", self.pm_do_search)
            self.pm_src = Gtk.ComboBoxText()
            for t in ("Minden forrás", "Csak apt", "Csak Flatpak"):
                self.pm_src.append_text(t)
            self.pm_src.set_active(0)
            self.pm_sbtn = self.btn("Keresés", self.pm_do_search)
            row.pack_start(self.pm_entry, True, True, 0)
            row.pack_start(self.pm_src, False, False, 0)
            row.pack_start(self.pm_sbtn, False, False, 0)
            v.pack_start(row, False, False, 0)
            opts = Gtk.Box(spacing=16)
            self.pm_chk_inst = Gtk.CheckButton(label="Csak a telepítettek")
            self.pm_chk_lib = Gtk.CheckButton(label="Könyvtárak és fejlesztői csomagok elrejtése")
            self.pm_chk_lib.set_active(True)
            opts.pack_start(self.pm_chk_inst, False, False, 0)
            opts.pack_start(self.pm_chk_lib, False, False, 0)
            v.pack_start(opts, False, False, 0)
            self.pm_fp_hint = self.lab("")
            self.pm_fp_btn = self.btn("Flatpak beállítása", self.pm_fp_setup)
            for w in (self.pm_fp_hint, self.pm_fp_btn):
                w.set_no_show_all(True)
                w.hide()
                v.pack_start(w, False, False, 0)
            self.pm_store = Gtk.ListStore(str, str, str, str, str, str, str, bool)
            self.pm_tv, sw = self.pm_list_view(self.pm_store, [
                ("Forrás", 1, True, False, 0), ("Név", 2, False, False, 2),
                ("Leírás", 3, False, True, None), ("Állapot", 4, False, False, 4)])
            self.pm_tv.get_selection().connect("changed", self.pm_on_sel)
            self.pm_tv.connect("row-activated", lambda *_: self.pm_primary())
            v.pack_start(sw, True, True, 0)
            self.pm_msg = self.lab("")
            v.pack_start(self.pm_msg, False, False, 0)
            self.pm_info = Gtk.Label(xalign=0)
            self.pm_info.set_use_markup(True)
            self.pm_info.set_line_wrap(True)
            self.pm_info.set_selectable(True)
            v.pack_start(self.pm_info, False, False, 0)
            bar = Gtk.Box(spacing=8)
            self.pm_b_inst = self.btn("Telepítés", self.pm_install)
            self.pm_b_rm = self.btn("Eltávolítás", self.pm_remove)
            for w in (self.pm_b_inst, self.pm_b_rm):
                w.set_sensitive(False)
                bar.pack_start(w, False, False, 0)
            v.pack_start(bar, False, False, 0)
            return v

        def pm_selected(self):
            model, it = self.pm_tv.get_selection().get_selected()
            return model[it] if it else None

        def pm_on_sel(self, *_):
            from xml.sax.saxutils import escape
            row = self.pm_selected()
            if not row:
                self.pm_info.set_text("")
                self.pm_b_inst.set_label("Telepítés")
                self.pm_b_rm.set_label("Eltávolítás")
                self.pm_b_inst.set_sensitive(False)
                self.pm_b_rm.set_sensitive(False)
                return
            src, badge, name, desc, state, pid, remote, inst = row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]
            tag = "apt" if src == "apt" else "Flatpak"
            self.pm_info.set_markup(f"<b>{escape(name)}</b>  {badge}\nForrás: <b>{escape(self.pm_src_text(src, remote))}</b>"
                                    + (f"   ·   azonosító: {escape(pid)}" if src != "apt" else ""))
            self.pm_b_inst.set_label(f"Telepítés ({tag})")
            self.pm_b_rm.set_label(f"Eltávolítás ({tag})")
            self.pm_b_inst.set_sensitive(not inst)
            self.pm_b_rm.set_sensitive(bool(inst))

        def pm_primary(self):
            row = self.pm_selected()
            if row:
                (self.pm_remove if row[7] else self.pm_install)()

        def pm_row(self, src, name, desc, pid, remote, inst):
            return [src, self.pm_badge(src, remote), name, desc, "✔ telepítve" if inst else "",
                    pid, remote, bool(inst)]

        def pm_do_search(self, *_):
            term = self.pm_entry.get_text().strip()
            only = self.pm_chk_inst.get_active()
            hide = self.pm_chk_lib.get_active()
            sel = self.pm_src.get_active()
            if not term and not only:
                self.pm_msg.set_text("Írd be a keresett program nevét vagy egy szót a leírásából.")
                return
            self.pm_seq += 1
            seq = self.pm_seq
            self.pm_sbtn.set_sensitive(False)
            self.pm_msg.set_text("Keresés…")
            fp_ok = pm_has_flatpak()

            def worker():
                rows, notes = [], []
                try:
                    words = [w.lower() for w in pm_terms(term)]
                    if sel in (0, 1):
                        inst = pm_apt_installed()
                        if only:
                            manual = pm_apt_manual() if not words else None
                            for n, (ver, summ) in inst.items():
                                if manual is not None and n not in manual:
                                    continue
                                if all(w in (n + " " + summ).lower() for w in words):
                                    if not (hide and PM_HIDE_RE.search(n)):
                                        rows.append(self.pm_row("apt", n, summ, n, "", True))
                        else:
                            for n, d in pm_apt_search(term):
                                if not (hide and PM_HIDE_RE.search(n)):
                                    rows.append(self.pm_row("apt", n, d, n, "", n in inst))
                    if sel in (0, 2):
                        if not fp_ok:
                            if sel == 2:
                                notes.append("A Flatpak nincs telepítve.")
                        else:
                            fi = pm_fp_installed()
                            if only:
                                for pid, (n, ver, orig) in fi.items():
                                    if all(w in (pid + " " + n).lower() for w in words):
                                        rows.append(self.pm_row("flatpak", n, f"{ver}  —  {pid}".strip(" —"),
                                                                pid, orig or "flathub", True))
                            else:
                                for pid, n, d, rem in pm_fp_search(term):
                                    rows.append(self.pm_row("flatpak", n, f"{d}  —  {pid}", pid,
                                                            (rem.split(",")[0].strip() if rem else "flathub"),
                                                            pid in fi))
                    rows.sort(key=lambda r: (pm_score(r[2], term), r[2].lower(), r[0]))
                    if len(rows) > 500:
                        rows = rows[:500]
                        notes.append("Csak az első 500 találat látszik, szűkítsd a keresést.")
                    na = sum(1 for r in rows if r[0] == "apt")
                    msg = f"{len(rows)} találat (apt: {na}, Flatpak: {len(rows) - na})."
                    if not rows:
                        msg = "Nincs találat."
                    msg = " ".join([msg] + notes)
                except Exception as e:  # noqa: BLE001
                    rows, msg = [], f"Hiba a keresés közben: {e}"
                GLib.idle_add(self.pm_show_results, seq, rows, msg)
            threading.Thread(target=worker, daemon=True).start()

        def pm_show_results(self, seq, rows, msg):
            if seq != self.pm_seq:
                return False
            self.pm_sbtn.set_sensitive(True)
            self.pm_store.clear()
            for r in rows:
                self.pm_store.append(r)
            self.pm_msg.set_text(msg)
            self.pm_on_sel()
            return False

        def pm_refresh_states(self):
            def worker():
                ai, fi = pm_apt_installed(), pm_fp_installed()
                GLib.idle_add(self.pm_apply_states, set(ai), set(fi))
            threading.Thread(target=worker, daemon=True).start()

        def pm_apply_states(self, ai, fi):
            for row in self.pm_store:
                inst = (row[5] in ai) if row[0] == "apt" else (row[5] in fi)
                row[7] = inst
                row[4] = "✔ telepítve" if inst else ""
            self.pm_on_sel()
            return False

        def pm_install(self, *_):
            row = self.pm_selected()
            if not row or row[7]:
                return
            src, name, pid, remote = row[0], row[2], row[5], row[6]
            if src == "apt":
                rc, pk = pm_apt_sim("install", pid)
                extra = [p for p in pk if p != pid]
                text = f"Telepítés\n\nProgram: {name}\nForrás: {self.pm_src_text('apt')}"
                if extra:
                    text += (f"\n\nA függőségek miatt további {len(extra)} csomag települ: "
                             + ", ".join(extra[:8]) + (" …" if len(extra) > 8 else ""))
                if rc != 0:
                    text += "\n\n⚠ Az előzetes ellenőrzés hibát jelzett, a telepítés valószínűleg nem sikerül."
                params = {"source": "apt", "id": pid}
            else:
                text = (f"Telepítés\n\nProgram: {name} ({pid})\nForrás: {self.pm_src_text('flatpak', remote)}\n\n"
                        "A Flatpak programok saját futtatókörnyezetet is letölthetnek (akár több száz MB).")
                params = {"source": "flatpak", "id": pid, "remote": remote or "flathub"}
            if self.confirm(text):
                self.run_task([("pm_install", params)], cb=lambda *_: self.pm_refresh_states())

        def pm_remove(self, *_):
            row = self.pm_selected()
            if not row or not row[7]:
                return
            src, name, pid, remote = row[0], row[2], row[5], row[6]
            text = f"Eltávolítás\n\nProgram: {name}\nForrás: {self.pm_src_text(src, remote)}"
            if src == "apt":
                rc, pk = pm_apt_sim("remove", pid)
                extra = [p for p in pk if p != pid]
                if extra:
                    text += (f"\n\nVele együtt további {len(extra)} csomag is eltávolításra kerül: "
                             + ", ".join(extra[:10]) + (" …" if len(extra) > 10 else ""))
                    if len(extra) >= 10:
                        text += "\n\n⚠ Ez sok csomag: ellenőrizd a listát, mielőtt folytatod!"
                params = {"source": "apt", "id": pid}
            else:
                params = {"source": "flatpak", "id": pid}
            if self.confirm(text):
                self.run_task([("pm_remove", params)], cb=lambda *_: self.pm_refresh_states())

        # --- Flatpak állapot és beállítás
        def pm_check_flatpak(self):
            def worker():
                have_fp = pm_has_flatpak()
                remotes = []
                if have_fp:
                    rc, out = pm_run(["flatpak", "remotes", "--system", "--columns=name"])
                    remotes = [x.strip() for x in out.splitlines() if x.strip()]
                GLib.idle_add(self.pm_fp_show, have_fp, remotes)
            threading.Thread(target=worker, daemon=True).start()

        def pm_fp_show(self, have_fp, remotes):
            if not have_fp:
                self.pm_fp_hint.set_text("⚠ A Flatpak nincs telepítve, ezért most csak az apt-programok között lehet keresni.")
                self.pm_fp_btn.set_label("Flatpak telepítése és a Flathub hozzáadása")
            elif not remotes:
                self.pm_fp_hint.set_text("⚠ Nincs beállított Flatpak-tároló, ezért a Flatpak-programok keresése nem ad találatot.")
                self.pm_fp_btn.set_label("Flathub tároló hozzáadása")
            else:
                self.pm_fp_hint.hide()
                self.pm_fp_btn.hide()
                return False
            self.pm_fp_hint.show()
            self.pm_fp_btn.show()
            return False

        def pm_fp_setup(self, *_):
            if self.confirm("Beállítom a Flatpak-ot: szükség esetén telepítem (apt-get install flatpak), "
                            "és hozzáadom a Flathub tárolót?"):
                self.run_task([("pm_flatpak_setup", {})], cb=lambda *_: self.pm_check_flatpak())

        # --- frissítések
        def pm_tab_updates(self):
            v = Gtk.Box(orientation=V, spacing=8)
            v.set_border_width(10)
            self.pm_ulbl = self.lab("")
            v.pack_start(self.pm_ulbl, False, False, 0)
            bar = Gtk.Box(spacing=8)
            bar.pack_start(self.btn("Frissítések keresése", self.pm_check_updates), False, False, 0)
            bar.pack_start(self.btn("Összes frissítése", self.pm_upgrade_all), False, False, 0)
            v.pack_start(bar, False, False, 0)
            self.pm_ustore = Gtk.ListStore(str, str, str, str)
            tv, sw = self.pm_list_view(self.pm_ustore, [
                ("Forrás", 0, True, False, None), ("Program", 1, False, True, 1),
                ("Jelenlegi verzió", 2, False, False, None), ("Új verzió", 3, False, False, None)])
            v.pack_start(sw, True, True, 0)
            self.pm_reboot = self.lab("")
            v.pack_start(self.pm_reboot, False, False, 0)
            return v

        def pm_load_updates(self):
            self.pm_ulbl.set_text("Frissítések keresése…")

            def worker():
                try:
                    a, f = pm_apt_upgradable(), pm_fp_updates()
                except Exception:  # noqa: BLE001
                    a, f = [], []
                GLib.idle_add(self.pm_show_updates, a, f)
            threading.Thread(target=worker, daemon=True).start()

        def pm_show_updates(self, apt_up, fp_up):
            self.pm_ustore.clear()
            for n, old, new in apt_up:
                self.pm_ustore.append([self.pm_badge("apt"), n, old, new])
            for pid, n, ver in fp_up:
                self.pm_ustore.append([self.pm_badge("flatpak", "flathub"), n, "", ver])
            tot = len(apt_up) + len(fp_up)
            if tot:
                self.pm_ulbl.set_text(f"{tot} frissítés érhető el (apt: {len(apt_up)}, Flatpak: {len(fp_up)}).")
            else:
                self.pm_ulbl.set_text("Nincs elérhető frissítés. (A lista a legutóbbi csomaglista-frissítés "
                                      "állapotát mutatja: a „Frissítések keresése” gomb újratölti.)")
            self.pm_reboot.set_text("⚠ A rendszer újraindítást kér a frissítések érvényesítéséhez."
                                    if os.path.exists("/run/reboot-required") else "")
            return False

        def pm_check_updates(self, *_):
            self.run_task([("pm_refresh", {})], cb=lambda *_: self.pm_load_updates())

        def pm_upgrade_all(self, *_):
            if self.confirm("Frissítsem a teljes rendszert?\n\nAz apt-csomagok (apt-get full-upgrade) és a "
                            "Flatpak-programok is frissülnek. Ez eltarthat egy ideig."):
                self.run_task([("pm_upgrade", {})],
                              cb=lambda *_: (self.pm_load_updates(), self.pm_refresh_states()))

        # --- karbantartás
        def pm_tab_clean(self):
            v = Gtk.Box(orientation=V, spacing=8)
            v.set_border_width(10)
            self.head(v, "Felesleges csomagok")
            v.pack_start(self.lab("Az apt-get autoremove törli azokat a csomagokat, amelyeket korábban "
                                  "függőségként telepített a rendszer, de már semmi sem igényli őket. "
                                  "A Flatpak nem használt futtatókörnyezeteit is eltávolítja."), False, False, 0)
            v.pack_start(self.btn("Felesleges csomagok eltávolítása", self.pm_do_autoremove), False, False, 0)
            self.head(v, "Letöltött csomagfájlok")
            self.pm_cache_lbl = self.lab("")
            v.pack_start(self.pm_cache_lbl, False, False, 0)
            v.pack_start(self.lab("Az apt-get clean törli a letöltött .deb fájlokat; a telepített programokat "
                                  "nem érinti."), False, False, 0)
            v.pack_start(self.btn("Letöltött csomagfájlok törlése", self.pm_do_clean), False, False, 0)
            self.head(v, "Teljes takarítás")
            v.pack_start(self.btn("Mindkettő egyszerre", self.pm_do_both), False, False, 0)
            return v

        def pm_update_cache_lbl(self, *_):
            self.pm_cache_lbl.set_text(f"A gyorsítótár jelenlegi mérete: {pm_hsize(pm_cache_size())}")

        def pm_do_autoremove(self, *_):
            self.pm_cleanup("autoremove")

        def pm_do_clean(self, *_):
            self.pm_cleanup("clean")

        def pm_do_both(self, *_):
            self.pm_cleanup("both")

        def pm_cleanup(self, what):
            text = ""
            if what in ("autoremove", "both"):
                rc, pk = pm_apt_sim("autoremove")
                if pk:
                    text += (f"Az apt-get autoremove a következő {len(pk)} csomagot törli: "
                             + ", ".join(pk[:15]) + (" …" if len(pk) > 15 else "") + "\n\n")
                else:
                    text += "Nincs felesleges apt-csomag.\n\n"
                text += "A Flatpak nem használt futtatókörnyezetei is törlődnek.\n\n"
            if what in ("clean", "both"):
                text += f"A letöltött csomagfájlok törlődnek ({pm_hsize(pm_cache_size())}).\n\n"
            if self.confirm(text + "Folytatod?"):
                self.run_task([("pm_cleanup", {"what": what})], cb=lambda *_: self.pm_update_cache_lbl())

        def pm_on_show(self):
            self.pm_loaded = True
            self.pm_check_flatpak()
            self.pm_load_updates()
            self.pm_update_cache_lbl()

        # ------------------------------------------------ XP-s párbeszédablakok
        def xp_banner(self, kind, title, sub=""):
            hd = Gtk.Box(spacing=12)
            hd.get_style_context().add_class("xp-pagehead")
            hd.pack_start(xp_image(kind, 40), False, False, 0)
            tx = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(label=title, xalign=0)
            t.set_line_wrap(True)
            t.get_style_context().add_class("xp-pagetitle")
            tx.pack_start(t, False, False, 0)
            if sub:
                s = Gtk.Label(label=sub, xalign=0)
                s.set_line_wrap(True)
                tx.pack_start(s, False, False, 0)
            hd.pack_start(tx, True, True, 0)
            return hd

        def xp_dialog(self, title, kind, sub, ok_label):
            d = Gtk.Dialog(title=title, transient_for=self, modal=True)
            d.get_style_context().add_class("xp")
            d.add_buttons("Mégse", Gtk.ResponseType.CANCEL, ok_label, Gtk.ResponseType.OK)
            d.set_default_response(Gtk.ResponseType.OK)
            d.get_action_area().set_border_width(8)
            area = d.get_content_area()
            area.set_spacing(0)
            area.pack_start(self.xp_banner(kind, title, sub), False, False, 0)
            return d, area

        # ------------------------------------------------ Felhasználók
        US_GROUP_INFO = {
            "sudo": "rendszergazdai jog (sudo)", "adm": "rendszernaplók olvasása", "audio": "hangeszközök",
            "video": "kamera, videó, grafika", "cdrom": "CD/DVD-meghajtó", "plugdev": "cserélhető eszközök",
            "netdev": "hálózati beállítások", "users": "általános felhasználói csoport", "dialout": "soros portok",
            "lpadmin": "nyomtatók kezelése", "scanner": "lapolvasók", "sambashare": "Samba-megosztások létrehozása",
            "vpn": "VPN jelszó nélküli kapcsolása", "docker": "Docker (gyakorlatilag rendszergazdai jog!)",
            "libvirt": "virtualizáció", "kvm": "virtualizáció", "bluetooth": "Bluetooth", "wireshark": "hálózatfigyelés",
            "systemd-journal": "rendszernapló (journal)", "input": "beviteli eszközök", "render": "grafikus gyorsítás",
            "floppy": "hajlékonylemez-meghajtó", "fuse": "FUSE-fájlrendszerek", "staff": "helyi programtelepítés"}
        US_DEFAULT_GROUPS = ("audio", "video", "cdrom", "plugdev", "netdev")

        def page_users(self):
            b = self.mk_page("Felhasználók",
                             "A helyi felhasználói fiókok kezelése: hozzáadás, eltávolítás, csoporttagságok (jogok) "
                             "és tulajdonságok szerkesztése. Rendszergazdai hitelesítés után használható.")
            self.us_data = {"users": [], "groups": [], "shells": []}
            self.us_loaded = False
            ar = Gtk.Box(spacing=10)
            self.us_hint = self.lab("A felhasználók kezeléséhez rendszergazdai hitelesítés szükséges.")
            self.us_auth = self.btn("Hitelesítés és a lista betöltése", self.us_refresh)
            ar.pack_start(self.us_hint, True, True, 0)
            ar.pack_start(self.us_auth, False, False, 0)
            b.pack_start(ar, False, False, 0)
            bar = Gtk.Box(spacing=8)
            self.us_b_new = self.btn("Új felhasználó…", self.us_new)
            self.us_b_edit = self.btn("Szerkesztés…", self.us_edit)
            self.us_b_del = self.btn("Eltávolítás…", self.us_delete)
            self.us_chk_sys = Gtk.CheckButton(label="Rendszerfiókok mutatása")
            self.us_chk_sys.connect("toggled", self.us_render)
            for w in (self.us_b_new, self.us_b_edit, self.us_b_del, self.us_chk_sys):
                bar.pack_start(w, False, False, 0)
            b.pack_start(bar, False, False, 0)
            self.us_store = Gtk.ListStore(str, str, str, str, str, str)
            self.us_tv, sw = self.pm_list_view(self.us_store, [
                ("Felhasználó", 0, False, False, 0), ("Teljes név", 1, False, True, 1),
                ("UID", 2, False, False, 2), ("Csoportok", 3, False, True, 3),
                ("Parancsértelmező", 4, False, False, 4), ("Állapot", 5, True, False, None)])
            self.us_tv.get_selection().connect("changed", self.us_set_sensitivity)
            self.us_tv.connect("row-activated", lambda *_: self.us_edit())
            b.pack_start(sw, True, True, 0)
            self.us_set_sensitivity()
            return b

        def us_me(self):
            try:
                return pwd.getpwuid(os.getuid()).pw_name
            except KeyError:
                return ""

        def us_selected(self):
            model, it = self.us_tv.get_selection().get_selected()
            if not it:
                return None
            for u in self.us_data["users"]:
                if u["name"] == model[it][0]:
                    return u
            return None

        def us_regular(self, u):
            return US_UID_MIN <= u["uid"] < US_UID_MAX

        def us_set_sensitivity(self, *_):
            ok = self.us_loaded
            self.us_b_new.set_sensitive(ok)
            self.us_chk_sys.set_sensitive(ok)
            u = self.us_selected() if ok else None
            self.us_b_edit.set_sensitive(bool(u and self.us_regular(u)))
            self.us_b_del.set_sensitive(bool(u and self.us_regular(u) and u["name"] != self.us_me()))

        def us_render(self, *_):
            sel = self.us_selected()
            self.us_store.clear()
            me = self.us_me()
            show_sys = self.us_chk_sys.get_active()
            for u in sorted(self.us_data["users"], key=lambda x: x["uid"]):
                regular = self.us_regular(u)
                if not (regular or show_sys):
                    continue
                if not regular:
                    state = "rendszerfiók"
                elif u["locked"]:
                    state = '<span foreground="#b45309">zárolva</span>'
                else:
                    state = "aktív"
                if u["name"] == me:
                    state += " (te)"
                self.us_store.append([u["name"], u["full"], str(u["uid"]), ", ".join([u["group"]] + u["groups"]),
                                      u["shell"], state])
            if sel:
                for row in self.us_store:
                    if row[0] == sel["name"]:
                        self.us_tv.get_selection().select_iter(row.iter)
            self.us_set_sensitivity()

        def us_refresh(self, *_):
            self.run_task([("user_list", {})], self.us_done)

        def us_done(self, rc, msg, data):
            if rc == 0 and isinstance(data, dict):
                self.us_data = data
                self.us_loaded = True
                self.us_hint.set_text("✔ Hitelesítve. A módosításokhoz a rendszer újabb jelszót nem kér ebben a munkamenetben.")
                self.us_auth.set_label("Lista frissítése")
                self.us_render()
            elif not self.us_loaded:
                self.us_hint.set_text("⚠ A hitelesítés nem sikerült, vagy a lista nem tölthető be. Próbáld újra.")
            self.us_set_sensitivity()

        def us_form(self, user=None):
            editing = user is not None
            title = f"Felhasználó szerkesztése: {user['name']}" if editing else "Új felhasználó"
            d, area = self.xp_dialog(title, "users",
                                     "A módosítások a mentés után azonnal érvénybe lépnek." if editing
                                     else "Add meg az új fiók adatait és jogait.",
                                     "Mentés" if editing else "Létrehozás")
            d.set_default_size(580, -1)
            g = Gtk.Grid(column_spacing=10, row_spacing=8)
            g.set_border_width(16)
            area.pack_start(g, True, True, 0)

            def row(r, text, w):
                g.attach(Gtk.Label(label=text, xalign=1), 0, r, 1, 1)
                w.set_hexpand(True)
                g.attach(w, 1, r, 1, 1)
            e_name = Gtk.Entry()
            e_name.set_placeholder_text("pl. kovacs.janos (kisbetű, szám, _ és -)")
            e_full = Gtk.Entry()
            e_full.set_placeholder_text("pl. Kovács János")
            e_pw, e_pw2 = Gtk.Entry(), Gtk.Entry()
            for e in (e_pw, e_pw2):
                e.set_visibility(False)
            e_pw.set_placeholder_text("(üresen hagyva nem változik)" if editing else "legalább 6 karakter")
            shells = list(self.us_data.get("shells") or ["/bin/bash"])
            cur_shell = user["shell"] if editing else "/bin/bash"
            if cur_shell not in shells:
                shells.append(cur_shell)
            cb_shell = Gtk.ComboBoxText()
            for sh in shells:
                cb_shell.append_text(sh)
            cb_shell.set_active(shells.index(cur_shell) if cur_shell in shells else 0)
            if editing:
                e_name.set_text(user["name"])
                e_name.set_sensitive(False)
                e_full.set_text(user["full"])
            row(0, "Felhasználónév:", e_name)
            row(1, "Teljes név:", e_full)
            row(2, "Jelszó:" if not editing else "Új jelszó:", e_pw)
            row(3, "Jelszó még egyszer:", e_pw2)
            row(4, "Parancsértelmező:", cb_shell)
            chk_lock = Gtk.CheckButton(label="Fiók zárolása (nem tud belépni)")
            chk_force = Gtk.CheckButton(label="Jelszócsere kötelező a következő belépéskor")
            chk_home = Gtk.CheckButton(label="Saját mappa létrehozása")
            chk_home.set_active(True)
            opts = Gtk.Box(orientation=V, spacing=4)
            if editing:
                chk_lock.set_active(user["locked"])
                opts.pack_start(chk_lock, False, False, 0)
            else:
                opts.pack_start(chk_home, False, False, 0)
            opts.pack_start(chk_force, False, False, 0)
            g.attach(opts, 1, 5, 1, 1)
            # --- csoporttagságok (jogok)
            hl = Gtk.Label(xalign=0)
            hl.set_markup("<b>Csoporttagságok (jogok)</b>")
            hl.get_style_context().add_class("xp-head")
            hl.set_margin_top(6)
            g.attach(hl, 0, 6, 2, 1)
            groups = [x for x in self.us_data.get("groups", []) if not (editing and x["name"] == user["group"])]
            initial = set(user["groups"]) if editing else set()
            state = {x["name"]: ((x["name"] in initial) if editing else (x["name"] in self.US_DEFAULT_GROUPS))
                     for x in groups}
            gstore = Gtk.ListStore(bool, str, str)
            gtv = Gtk.TreeView(model=gstore)
            tog = Gtk.CellRendererToggle()

            def on_tog(_c, path):
                r = gstore[path]
                r[0] = not r[0]
                state[r[1]] = r[0]
            tog.connect("toggled", on_tog)
            gtv.append_column(Gtk.TreeViewColumn("", tog, active=0))
            c1 = Gtk.TreeViewColumn("Csoport", Gtk.CellRendererText(), text=1)
            c1.set_sort_column_id(1)
            gtv.append_column(c1)
            gtv.append_column(Gtk.TreeViewColumn("Mire jogosít", Gtk.CellRendererText(), text=2))
            gsw = Gtk.ScrolledWindow()
            gsw.get_style_context().add_class("xp-list")
            gsw.set_min_content_height(190)
            gsw.add(gtv)
            g.attach(gsw, 0, 7, 2, 1)
            chk_all = Gtk.CheckButton(label="Az összes csoport mutatása (a rendszercsoportokat is)")
            g.attach(chk_all, 0, 8, 2, 1)

            def fill(*_):
                gstore.clear()
                for x in sorted(groups, key=lambda y: y["name"]):
                    n = x["name"]
                    if chk_all.get_active() or x["gid"] >= US_UID_MIN or n in self.US_GROUP_INFO or state.get(n):
                        gstore.append([state[n], n, self.US_GROUP_INFO.get(n, "")])
            chk_all.connect("toggled", fill)
            fill()
            err = Gtk.Label(xalign=0)
            err.set_line_wrap(True)
            err.set_margin_start(16)
            err.set_margin_end(16)
            area.pack_start(err, False, False, 4)
            d.show_all()
            while True:
                if d.run() != Gtk.ResponseType.OK:
                    d.destroy()
                    return None
                name, p1, p2 = e_name.get_text().strip(), e_pw.get_text(), e_pw2.get_text()
                msg = ""
                if not editing and not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", name):
                    msg = "Érvénytelen felhasználónév: kisbetűvel vagy _ jellel kezdődjön, csak kisbetű, szám, _ és - lehet."
                elif re.search(r"[:,]", e_full.get_text()):
                    msg = "A teljes név nem tartalmazhat kettőspontot vagy vesszőt."
                elif (not editing or p1 or p2) and p1 != p2:
                    msg = "A két jelszó nem egyezik."
                elif (not editing or p1) and not 6 <= len(p1) <= 128:
                    msg = "A jelszó legalább 6 karakter legyen."
                if msg:
                    err.set_markup(f'<span foreground="#b91c1c">⚠ {msg}</span>')
                    continue
                break
            chosen = {n for n, v in state.items() if v}
            res = {"name": name, "fullname": e_full.get_text().strip(), "shell": cb_shell.get_active_text(),
                   "password": p1, "force_change": chk_force.get_active(),
                   "add_groups": sorted(chosen - initial), "rm_groups": sorted(initial - chosen)}
            if editing:
                res["locked"] = chk_lock.get_active()
            else:
                res["create_home"] = chk_home.get_active()
            d.destroy()
            return res

        def us_new(self, *_):
            data = self.us_form()
            if data:
                self.run_task([("user_add", data)], self.us_done)

        def us_edit(self, *_):
            u = self.us_selected()
            if not u or not self.us_regular(u):
                return
            data = self.us_form(u)
            if data:
                self.run_task([("user_edit", data)], self.us_done)

        def us_delete(self, *_):
            u = self.us_selected()
            if not u or not self.us_regular(u) or u["name"] == self.us_me():
                return
            d, area = self.xp_dialog("Felhasználó eltávolítása", "users", "", "Eltávolítás")
            box = Gtk.Box(orientation=V, spacing=10)
            box.set_border_width(18)
            l = self.lab(f"Eltávolítod a(z) {u['name']} ({u['full'] or 'név nélkül'}) felhasználót?")
            chk = Gtk.CheckButton(label=f"A saját mappa ({u['home']}) és a levelek törlése is "
                                        "(nem vonható vissza)")
            box.pack_start(l, False, False, 0)
            box.pack_start(chk, False, False, 0)
            area.pack_start(box, True, True, 0)
            d.show_all()
            ok = d.run() == Gtk.ResponseType.OK
            rm = chk.get_active()
            d.destroy()
            if ok:
                self.run_task([("user_delete", {"name": u["name"], "remove_home": rm})], self.us_done)

        def us_on_show(self):
            # ha a segéd már hitelesítve fut (korábbi művelet), a lista jelszó nélkül betölthető
            p = getattr(self.h, "p", None)
            if not self.us_loaded and p is not None and p.poll() is None:
                self.us_refresh()

        # ------------------------------------------------ Nyomtatók (system-config-printer)
        def page_printers(self):
            b = self.mk_page("Nyomtatók",
                             "Nyomtatók hozzáadása, eltávolítása és beállítása a system-config-printer programmal.")
            self.pkg_row(b, "Nyomtatókezelő",
                         "A system-config-printer program és a CUPS nyomtatószolgáltatás a Debian-tárolóból.",
                         "system-config-printer",
                         [("pkg", {"action": "install", "pkgs": ["cups", "system-config-printer"]})],
                         [("pkg", {"action": "remove", "pkgs": ["system-config-printer"]})])
            self.head(b, "Nyomtatók kezelése")
            self.pr_hint = self.lab("")
            b.pack_start(self.pr_hint, False, False, 0)
            bar = Gtk.Box(spacing=8)
            self.pr_btn = self.btn("Nyomtatóbeállítások megnyitása", self.pr_open)
            bar.pack_start(self.pr_btn, False, False, 0)
            b.pack_start(bar, False, False, 0)
            return b

        def pr_open(self, *_):
            exe = shutil.which("system-config-printer")
            if not exe:
                self.say(1, "A system-config-printer nincs telepítve: előbb telepítsd.")
                return
            try:
                subprocess.Popen([exe], start_new_session=True)
            except OSError as e:
                self.say(1, f"A nyomtatókezelő nem indítható: {e}")
                return
            self.say(0, "A nyomtatókezelő megnyílt (a módosításokhoz a program maga kér jelszót).")

        # ------------------------------------------------ Kijelző (xfce4-display-settings)
        def page_display(self):
            b = self.mk_page("Kijelző",
                             "A képernyő beállítása: felbontás, képfrissítés, tájolás, több monitor elrendezése "
                             "a kijelzőkezelő programmal.")
            self.head(b, "Jelenlegi állapot")
            self.kj_lbl = self.lab("")
            b.pack_start(self.kj_lbl, False, False, 0)
            self.head(b, "Beállítás")
            self.kj_hint = self.lab("")
            b.pack_start(self.kj_hint, False, False, 0)
            bar = Gtk.Box(spacing=8)
            self.kj_btn = self.btn("Kijelzőbeállítások megnyitása", self.kj_open)
            self.kj_refresh = self.btn("Állapot frissítése", lambda *_: self.kj_update())
            self.kj_inst = self.btn("Kijelzőbeállító telepítése",
                                    lambda *_: self.run_task([("pkg", {"action": "install", "pkgs": ["xfce4-settings"]})]))
            for w in (self.kj_btn, self.kj_refresh, self.kj_inst):
                bar.pack_start(w, False, False, 0)
            b.pack_start(bar, False, False, 0)
            self.kj_update()
            return b

        def kj_update(self):
            info = kj_summary()
            if info is None:
                text = "A kijelzők adatai nem olvashatók (az xrandr hiányzik, vagy nincs grafikus munkamenet)."
            elif not info:
                text = "Nincs csatlakoztatott kijelző."
            else:
                lines = []
                for d in info:
                    st = (f"{d['mode']}" + (f", {d['rate']} Hz" if d["rate"] else "")) if d["mode"] else "kikapcsolva"
                    lines.append(f"{d['name']}{' (elsődleges)' if d['primary'] else ''}: {st}")
                text = "\n".join(lines)
            self.kj_lbl.set_text(text)

        def kj_open(self, *_):
            exe = kj_tool()
            if not exe:
                self.say(1, "Nincs kijelzőbeállító program telepítve: előbb telepítsd.")
                return
            try:
                subprocess.Popen([exe], start_new_session=True)
            except OSError as e:
                self.say(1, f"A kijelzőbeállító nem indítható: {e}")
                return
            self.say(0, "A kijelzőbeállító megnyílt. A módosítás után az „Állapot frissítése” gombbal ellenőrizheted.")

        # ------------------------------------------------ Vezérlőpult frissítése (GitHub)
        def page_update(self):
            from gi.repository import Pango
            b = self.mk_page("Vezérlőpult frissítése",
                             f"A(z) {APP_TITLE} legújabb verziójának letöltése a GitHubról és telepítése a rendszerbe.")
            self.head(b, "Telepített példány")
            self.up_inst = self.lab("")
            b.pack_start(self.up_inst, False, False, 0)
            self.head(b, "Forrás (GitHub)")
            src = Gtk.Label(label=UPDATE_URL, xalign=0)
            src.set_line_wrap(True)
            src.set_line_wrap_mode(Pango.WrapMode.CHAR)
            src.set_selectable(True)
            b.pack_start(src, False, False, 0)
            self.up_state = self.lab("")
            b.pack_start(self.up_state, False, False, 0)
            bar = Gtk.Box(spacing=8)
            self.up_b_check = self.btn("Frissítések keresése", self.up_check)
            self.up_b_go = self.btn("Frissítés és telepítés", self.up_go)
            self.up_b_rb = self.btn("Visszaállítás az előző verzióra", self.up_rollback)
            self.up_b_go.set_sensitive(False)
            for w in (self.up_b_check, self.up_b_go, self.up_b_rb):
                bar.pack_start(w, False, False, 0)
            b.pack_start(bar, False, False, 0)
            b.pack_start(self.lab("A telepítés és a visszaállítás mindig rendszergazdai hitelesítést kér. A telepítés "
                                  "előtt a program ellenőrzi, hogy a letöltött fájl érvényes, és ehhez az "
                                  "alkalmazáshoz tartozik. A korábbi verzió mentve marad."), False, False, 0)
            self.up_new = None
            self.up_show_installed()
            return b

        def up_show_installed(self):
            data = up_read_installed()
            if data is None:
                self.up_inst.set_text(f"A program nincs telepítve a rendszerbe ({INSTALL_PATH}).")
                self.up_b_rb.set_sensitive(False)
                return
            try:
                when = datetime.datetime.fromtimestamp(os.path.getmtime(INSTALL_PATH)).strftime("%Y.%m.%d. %H:%M")
            except OSError:
                when = "?"
            has_prev = os.path.exists(INSTALL_PATH + ".prev")
            self.up_inst.set_text(f"{INSTALL_PATH}\n{len(data) // 1024} kB, módosítva: {when}, "
                                  f"SHA-256: {hashlib.sha256(data).hexdigest()[:12]}…"
                                  + ("\nVan mentett előző verzió." if has_prev else ""))
            self.up_b_rb.set_sensitive(has_prev)

        def up_check(self, *_):
            self.up_state.set_text("Keresés a GitHubon…")
            self.up_b_check.set_sensitive(False)
            self.up_b_go.set_sensitive(False)

            def worker():
                try:
                    data = up_fetch()
                    up_validate(data)
                    res = (hashlib.sha256(data).hexdigest(), up_diffstat(up_read_installed(), data), len(data), None)
                except Exception as e:  # noqa: BLE001
                    res = (None, None, 0, str(e))
                GLib.idle_add(self.up_checked, res)
            threading.Thread(target=worker, daemon=True).start()

        def up_checked(self, res):
            sha, stat, size, err = res
            self.up_b_check.set_sensitive(True)
            self.up_new = None
            if err:
                self.up_state.set_text(f"⚠ A frissítés keresése nem sikerült: {err}")
                return False
            cur = up_read_installed()
            if cur is not None and hashlib.sha256(cur).hexdigest() == sha:
                self.up_state.set_text("✔ A telepített verzió megegyezik a GitHubon lévővel, naprakész.")
                return False
            self.up_new = sha
            extra = f" (+{stat[0]} / −{stat[1]} sor a telepítetthez képest)" if stat else ""
            self.up_state.set_text(f"⬆ Új verzió érhető el a GitHubon: {size // 1024} kB, "
                                   f"SHA-256: {sha[:12]}…{extra}")
            self.up_b_go.set_sensitive(True)
            return False

        def up_go(self, *_):
            if not self.up_new:
                return
            if self.confirm(f"Letöltöm és telepítem a(z) {APP_TITLE} új verzióját a GitHubról?\n\n"
                            f"Ellenőrző összeg (SHA-256): {self.up_new[:16]}…\n\n"
                            "A régi verzió mentve marad, így visszaállítható. A telepítés rendszergazdai "
                            "hitelesítést kér."):
                self.run_task([("self_update", {"sha256": self.up_new})], self.up_after)

        def up_rollback(self, *_):
            if self.confirm("Visszaállítod a program előző (mentett) verzióját?"):
                self.run_task([("self_rollback", {})], self.up_after)

        def up_after(self, rc, msg, data):
            self.up_show_installed()
            if rc != 0:
                return
            self.up_new = None
            self.up_b_go.set_sensitive(False)
            self.up_state.set_text("✔ " + msg)
            if self.confirm("A telepítés kész. Újraindítsam most a programot az új verzióval?"):
                GLib.idle_add(self.up_restart)

        def up_restart(self):
            for h in (self.h, self.hv):
                try:
                    if h:
                        h.close()
                except Exception:  # noqa: BLE001
                    pass
            try:
                os.execv(sys.executable, [sys.executable, INSTALL_PATH] + sys.argv[1:])
            except OSError as e:
                self.say(1, f"Az újraindítás nem sikerült: {e}")
            return False

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
            b.pack_start(self.lab("A módosítás alkalmazásához mindig rendszergazdai hitelesítés szükséges."),
                         False, False, 0)

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

        # ------------------------------------------------------------ Mappamegosztás
        def page_share(self):
            b = self.mk_page("Mappamegosztás",
                             "Mappa megosztása a hálózaton (Samba/SMB: Windows, Linux és Mac gépekről is elérhető). "
                             "Itt megszüntetheted vagy szüneteltetheted a megosztást, és beállíthatod, ki mit "
                             "érhet el rajta.")
            self.pkg_row(b, "Samba fájlszerver", "A samba csomag (smbd, nmbd) a Debian-tárolóból.", "samba",
                         [("pkg", {"action": "install", "pkgs": ["samba"]}), ("share_setup", {})],
                         [("pkg", {"action": "remove", "pkgs": ["samba"]})])
            self.head(b, "Megosztott mappák")
            bar = Gtk.Box(spacing=8)
            self.sh_ctrls = [self.btn("Új megosztás…", self.sh_new),
                             self.btn("Lista frissítése", self.sh_refresh),
                             self.btn("Samba újraindítása", self.sh_restart)]
            for w in self.sh_ctrls:
                bar.pack_start(w, False, False, 0)
            b.pack_start(bar, False, False, 0)
            self.sh_hint = self.lab("")
            b.pack_start(self.sh_hint, False, False, 0)
            self.sh_box = Gtk.Box(orientation=V, spacing=4)
            b.pack_start(self.sh_box, False, False, 4)

            # --- űrlap (új / szerkesztés)
            self.sh_exp = Gtk.Expander(label="Megosztás")
            g = Gtk.Grid(column_spacing=10, row_spacing=6)
            g.set_margin_start(12)
            g.set_margin_top(6)
            self.sh_e = {}

            def entry(key, label, row, width, ph=""):
                g.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
                e = Gtk.Entry()
                e.set_width_chars(min(width, 12))
                e.set_hexpand(True)
                e.set_placeholder_text(ph)
                g.attach(e, 1, row, 1, 1)
                self.sh_e[key] = e
                return e
            entry("name", "Megosztás neve:", 0, 24, "pl. kozos (betű, szám, _ . -)")
            entry("path", "Mappa:", 1, 44, "/home/felhasznalo/mappa")
            g.attach(self.btn("Tallózás…", self.sh_browse), 2, 1, 1, 1)
            entry("comment", "Megjegyzés (nem kötelező):", 2, 44)
            g.attach(Gtk.Label(label="Ki érheti el:", xalign=1, yalign=0), 0, 3, 1, 1)
            mb = Gtk.Box(orientation=V, spacing=2)
            r1 = Gtk.RadioButton.new_with_label_from_widget(None, "Csak a megadott felhasználók (jelszavas belépés)")
            r2 = Gtk.RadioButton.new_with_label_from_widget(
                r1, "Bárki a hálózaton jelszó nélkül, csak olvashat (a felsoroltak írhatnak is)")
            r3 = Gtk.RadioButton.new_with_label_from_widget(
                r1, "Bárki a hálózaton jelszó nélkül, olvashat és írhat is")
            self.sh_radios = {"users": r1, "guest_ro": r2, "guest_rw": r3}
            for r in (r1, r2, r3):
                r.get_child().set_line_wrap(True)
                mb.pack_start(r, False, False, 0)
                r.connect("toggled", self.sh_mode_changed)
            g.attach(mb, 1, 3, 2, 1)
            g.attach(Gtk.Label(label="Felhasználók és jogaik:", xalign=1, yalign=0), 0, 4, 1, 1)
            ub = Gtk.Box(orientation=V, spacing=4)
            self.sh_ubox = Gtk.Box(orientation=V, spacing=3)
            ub.pack_start(self.sh_ubox, False, False, 0)
            add = Gtk.Box(spacing=6)
            self.sh_combo = Gtk.ComboBoxText.new_with_entry()
            add.pack_start(self.sh_combo, True, True, 0)
            add.pack_start(self.btn("Hozzáadás", self.sh_user_add), False, False, 0)
            ub.pack_start(add, False, False, 0)
            ub.pack_start(self.lab("„Írhat” jelölés nélkül a felhasználó csak olvashat. Csoportot @csoportnév "
                                   "alakban adj meg. A jelszavas belépéshez a felhasználónak Samba-jelszó kell "
                                   "(lejjebb állítható)."), False, False, 0)
            self.sh_uwrap = ub
            g.attach(ub, 1, 4, 2, 1)
            self.sh_c_force = Gtk.CheckButton(label="A mappa tulajdonosa nevében érjék el a fájlokat (ajánlott)")
            self.sh_c_force.set_active(True)
            g.attach(self.sh_c_force, 1, 5, 2, 1)
            g.attach(self.lab("Így a hálózati felhasználóknak nem kell külön fájlrendszer-jog: a jogokat "
                              "itt, a megosztáson állítod be. Az új fájlok a tulajdonos nevén jönnek létre."),
                     1, 6, 2, 1)
            hb = Gtk.Box(spacing=8)
            hb.pack_start(self.btn("Mentés", self.sh_save), False, False, 0)
            hb.pack_start(self.btn("Mégse", self.sh_cancel), False, False, 0)
            g.attach(hb, 1, 7, 1, 1)
            self.sh_exp.add(g)
            b.pack_start(self.sh_exp, False, False, 6)

            self.head(b, "Hálózati jelszavak (Samba)")
            b.pack_start(self.lab("A jelszavas megosztásokhoz a felhasználónak külön Samba-jelszó kell; ez lehet "
                                  "más, mint a gépre belépés jelszava."), False, False, 0)
            self.sh_smbbox = Gtk.Box(orientation=V, spacing=2)
            b.pack_start(self.sh_smbbox, False, False, 4)
            self.head(b, "Most csatlakozott gépek")
            self.sh_sess = Gtk.Label(xalign=0)
            self.sh_sess.set_selectable(True)
            ssw = Gtk.ScrolledWindow()
            ssw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            ssw.set_propagate_natural_height(True)
            ssw.add(self.sh_sess)
            b.pack_start(ssw, False, False, 0)
            self.sh_render()
            self.sh_users_render()
            return b

        # --- lista
        def sh_render(self):
            d = self.sh_data
            shares = d.get("shares") or []
            for c in self.sh_box.get_children():
                self.sh_box.remove(c)
            if not shares:
                self.sh_box.pack_start(self.lab("(Nincs megosztott mappa.)"), False, False, 0)
            for s in shares:
                self.sh_box.pack_start(self.sh_row(s), False, False, 0)
            self.sh_box.show_all()
            self.sh_combo.remove_all()
            for u in d.get("users") or []:
                self.sh_combo.append_text(u)
            for gname in d.get("groups") or []:
                self.sh_combo.append_text("@" + gname)
            for c in self.sh_smbbox.get_children():
                self.sh_smbbox.remove(c)
            users = d.get("users") or []
            smb = set(d.get("smb_users") or [])
            if not users:
                self.sh_smbbox.pack_start(self.lab("(Nincs rendes felhasználó a gépen.)"), False, False, 0)
            for u in users:
                self.sh_smbbox.pack_start(self.sh_smb_row(u, u in smb), False, False, 0)
            self.sh_smbbox.show_all()
            sess = d.get("sessions") or ""
            if sess:
                self.sh_sess.set_markup("<tt>" + GLib.markup_escape_text(sess) + "</tt>")
            else:
                self.sh_sess.set_text("(Nincs adat, vagy senki sincs csatlakozva.)")

        def sh_row(self, s):
            name = s["name"]
            on = s.get("available", True)
            smb = set(self.sh_data.get("smb_users") or [])
            host = os.uname().nodename
            box = Gtk.Box(orientation=V, spacing=2)
            row = Gtk.Box(spacing=10)
            left = Gtk.Box(orientation=V, spacing=2)
            t = Gtk.Label(xalign=0)
            state = ('<span foreground="#15803d">● megosztva</span>' if on
                     else '<span foreground="#b45309">⏸ szünetel</span>')
            t.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>   {state}")
            left.pack_start(t, False, False, 0)
            owner = f"   (tulajdonos: {s['owner']})" if s.get("owner") else ""
            left.pack_start(self.lab("Mappa: " + s["path"] + owner), False, False, 0)
            if s["mode"] == "guest_rw":
                acc = "Bárki, jelszó nélkül: olvasás és írás"
            elif s["mode"] == "guest_ro":
                acc = "Bárki, jelszó nélkül: csak olvasás"
                if s["users"]:
                    acc += "; írhat: " + ", ".join(u["name"] for u in s["users"])
            else:
                acc = "Csak ők érhetik el: " + ", ".join(
                    u["name"] + (" (írás)" if u["rw"] else " (olvasás)") for u in s["users"])
            left.pack_start(self.lab(acc), False, False, 0)
            if s.get("comment"):
                left.pack_start(self.lab("Megjegyzés: " + s["comment"]), False, False, 0)
            unc = self.lab(f"Elérés: \\\\{host}\\{name}   vagy   smb://{host}/{name}")
            unc.set_selectable(True)
            left.pack_start(unc, False, False, 0)
            if not s.get("path_ok", True):
                left.pack_start(self.lab("⚠ A mappa nem létezik vagy nem érhető el."), False, False, 0)
            miss = [u["name"] for u in s["users"] if not u["name"].startswith("@") and u["name"] not in smb]
            if miss:
                left.pack_start(self.lab("⚠ Nincs Samba-jelszavuk, ezért nem tudnak belépni: " + ", ".join(miss)),
                                False, False, 0)
            sw = Gtk.Switch()
            sw.set_active(on)
            sw.set_valign(Gtk.Align.CENTER)
            sw.connect("state-set", self.on_sh_switch, name)
            be = self.btn("Szerkesztés", lambda *_: self.sh_edit(s))
            bd = self.btn("Megszüntetés", lambda *_: self.sh_delete(name))
            row.pack_start(left, True, True, 0)
            for w in (sw, be, bd):
                w.set_valign(Gtk.Align.CENTER)
                row.pack_start(w, False, False, 0)
            box.pack_start(row, False, False, 4)
            box.pack_start(Gtk.Separator(), False, False, 2)
            return box

        def sh_smb_row(self, user, has):
            row = Gtk.Box(spacing=10)
            nm = Gtk.Label(xalign=0)
            nm.set_markup(f"<b>{GLib.markup_escape_text(user)}</b>   " +
                          ('<span foreground="#15803d">● van Samba-jelszava</span>' if has
                           else '<span foreground="#6b7280">○ nincs Samba-jelszava</span>'))
            row.pack_start(nm, True, True, 0)
            row.pack_start(self.btn("Jelszó beállítása…" if not has else "Jelszó módosítása…",
                                    lambda *_: self.sh_setpw(user)), False, False, 0)
            if has:
                row.pack_start(self.btn("Hozzáférés törlése", lambda *_: self.sh_pwdel(user)), False, False, 0)
            return row

        def on_sh_switch(self, sw, state, name):
            if not self.busy:
                self.run_task([("share_toggle", {"name": name, "available": bool(state)})], self.sh_done)
            return True        # a kapcsoló állapotát a művelet után a lista újrarajzolása állítja be

        def sh_delete(self, name):
            if self.confirm(f"Megszünteted a(z) {name} megosztását? A mappa és a benne lévő fájlok megmaradnak, "
                            "de a hálózaton már nem lesz elérhető, a csatlakozott gépekről azonnal lekapcsolódik."):
                self.run_task([("share_delete", {"name": name})], self.sh_done)

        def sh_refresh(self, *_):
            if self.run_task([("share_list", {})], self.sh_done):
                self.sh_loaded = True
                return True
            return False

        def sh_restart(self, *_):
            self.run_task([("share_restart", {})], self.sh_done)

        def sh_done(self, rc, msg, data):
            if isinstance(data, dict):
                self.sh_data = data
                self.sh_render()

        # --- Samba-jelszavak
        def sh_setpw(self, user):
            d = Gtk.Dialog(title=f"Samba-jelszó: {user}", transient_for=self, modal=True)
            d.get_style_context().add_class("xp")
            d.add_buttons("Mégse", Gtk.ResponseType.CANCEL, "Beállítás", Gtk.ResponseType.OK)
            d.set_default_response(Gtk.ResponseType.OK)
            area = d.get_content_area()
            area.set_border_width(14)
            area.set_spacing(8)
            area.pack_start(self.lab("Ezzel a jelszóval lép be a felhasználó a hálózati megosztásokhoz "
                                     "(legalább 6 karakter)."), False, False, 0)
            e1, e2 = Gtk.Entry(), Gtk.Entry()
            for e, ph in ((e1, "Új jelszó"), (e2, "Jelszó még egyszer")):
                e.set_visibility(False)
                e.set_placeholder_text(ph)
                e.set_activates_default(True)
                area.pack_start(e, False, False, 0)
            d.show_all()
            resp = d.run()
            p1, p2 = e1.get_text(), e2.get_text()
            d.destroy()
            if resp != Gtk.ResponseType.OK:
                return
            if p1 != p2:
                self.say(1, "A két jelszó nem egyezik.")
                return
            if len(p1) < 6:
                self.say(1, "A jelszó legalább 6 karakter legyen.")
                return
            self.run_task([("share_pw", {"user": user, "password": p1})], self.sh_done)

        def sh_pwdel(self, user):
            if self.confirm(f"Törlöd {user} Samba-hozzáférését? A hálózaton nem tud majd belépni, "
                            "a gépre belépési jelszava nem változik."):
                self.run_task([("share_pwdel", {"user": user})], self.sh_done)

        # --- űrlap
        def sh_mode(self):
            return next((k for k, r in self.sh_radios.items() if r.get_active()), "users")

        def sh_mode_changed(self, *_):
            self.sh_uwrap.set_sensitive(self.sh_mode() != "guest_rw")

        def sh_users_render(self):
            for c in self.sh_ubox.get_children():
                self.sh_ubox.remove(c)
            if not self.sh_users:
                self.sh_ubox.pack_start(self.lab("(Még nincs felhasználó a listában.)"), False, False, 0)
            for u in self.sh_users:
                row = Gtk.Box(spacing=10)
                row.pack_start(Gtk.Label(label=u["name"], xalign=0), True, True, 0)
                cw = Gtk.CheckButton(label="Írhat")
                cw.set_active(u["rw"])
                cw.connect("toggled", lambda c, u=u: u.update(rw=c.get_active()))
                row.pack_start(cw, False, False, 0)
                row.pack_start(self.btn("Eltávolítás", lambda _b, u=u: self.sh_user_del(u)), False, False, 0)
                self.sh_ubox.pack_start(row, False, False, 0)
            self.sh_ubox.show_all()

        def sh_user_add(self, *_):
            n = (self.sh_combo.get_active_text() or "").strip()
            if not n:
                return
            if n in (self.sh_data.get("groups") or []) and n not in (self.sh_data.get("users") or []):
                n = "@" + n
            if not any(u["name"] == n for u in self.sh_users):
                self.sh_users.append({"name": n, "rw": False})
                self.sh_users_render()
            self.sh_combo.get_child().set_text("")

        def sh_user_del(self, u):
            self.sh_users = [x for x in self.sh_users if x is not u]
            self.sh_users_render()

        def sh_clear_form(self):
            for e in self.sh_e.values():
                e.set_text("")
                e.set_sensitive(True)
            self.sh_radios["users"].set_active(True)
            self.sh_users = []
            self.sh_users_render()
            self.sh_c_force.set_active(True)
            self.sh_edit_avail = True
            self.sh_mode_changed()

        def sh_new(self, *_):
            self.sh_editing = None
            self.sh_clear_form()
            self.sh_exp.set_label("Új megosztás")
            self.sh_exp.set_expanded(True)
            self.sh_e["name"].grab_focus()

        def sh_edit(self, s):
            self.sh_clear_form()
            self.sh_editing = s["name"]
            e = self.sh_e
            e["name"].set_text(s["name"])
            e["name"].set_sensitive(False)
            e["path"].set_text(s["path"])
            e["comment"].set_text(s.get("comment") or "")
            self.sh_radios[s["mode"]].set_active(True)
            self.sh_users = [dict(u) for u in s["users"]]
            self.sh_users_render()
            self.sh_c_force.set_active(bool(s.get("force_user")))
            self.sh_edit_avail = s.get("available", True)
            self.sh_exp.set_label(f"Megosztás szerkesztése: {s['name']}")
            self.sh_exp.set_expanded(True)

        def sh_browse(self, *_):
            d = Gtk.FileChooserDialog(title="Megosztandó mappa kiválasztása", transient_for=self,
                                      action=Gtk.FileChooserAction.SELECT_FOLDER)
            d.add_buttons("Mégse", Gtk.ResponseType.CANCEL, "Kiválasztás", Gtk.ResponseType.OK)
            cur = self.sh_e["path"].get_text().strip()
            d.set_current_folder(cur if cur.startswith("/") and os.path.isdir(cur) else os.path.expanduser("~"))
            path = d.get_filename() if d.run() == Gtk.ResponseType.OK else None
            d.destroy()
            if path:
                self.sh_e["path"].set_text(path)
                if not self.sh_e["name"].get_text().strip() and self.sh_editing is None:
                    stem = re.sub(r"[^A-Za-z0-9_.-]", "", os.path.basename(path.rstrip("/")))[:32]
                    self.sh_e["name"].set_text(stem)

        def sh_save(self, *_):
            e = self.sh_e
            name, path = e["name"].get_text().strip(), e["path"].get_text().strip()
            mode = self.sh_mode()
            edit = self.sh_editing is not None
            if not SHARE_NAME_RE.fullmatch(name) or name.lower() in SHARE_RESERVED:
                self.say(1, "A megosztás neve 1–32 karakter lehet: betű, szám, _ . -")
                return
            if not path.startswith("/") or not os.path.isdir(path):
                self.say(1, "Válaszd ki a megosztandó mappát.")
                return
            if not share_path_ok(os.path.realpath(path)):
                self.say(1, "Csak a /home, /srv, /mnt, /media, /opt, /data és /shares alatti mappa osztható meg.")
                return
            if mode == "users" and not self.sh_users:
                self.say(1, "Adj hozzá legalább egy felhasználót, vagy válassz jelszó nélküli hozzáférést.")
                return
            if mode == "guest_rw" and not self.confirm(
                    "Bárki, aki eléri ezt a gépet a hálózaton, jelszó nélkül módosíthatja és törölheti a mappa "
                    "tartalmát. Biztosan így állítod be?"):
                return
            self.run_task([("share_save", {"name": name, "path": path, "comment": e["comment"].get_text().strip(),
                                           "mode": mode, "users": self.sh_users,
                                           "force_owner": self.sh_c_force.get_active(),
                                           "available": self.sh_edit_avail if edit else True,
                                           "edit": edit})], self.sh_saved)

        def sh_saved(self, rc, msg, data):
            self.sh_done(rc, msg, data)
            if rc == 0:
                self.sh_cancel()

        def sh_cancel(self, *_):
            self.sh_editing = None
            self.sh_clear_form()
            self.sh_exp.set_expanded(False)

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
