#!/usr/bin/env python3
"""Ciszterci tűzfal – grafikus iptables-kezelő (GTK3).

Első indításkor (python3 ciszterci-tuzfal.py) telepíti a függőségeket, beépül a rendszerbe
(/usr/local/bin/ciszterci-tuzfal, alkalmazásmenü: Rendszer › Ciszterci tűzfal), majd újraindul.
Eltávolítás:  ciszterci-tuzfal --uninstall   (a csomagokat és a mentett szabályokat nem törli)
"""
import sys, os, json, shlex, subprocess, re, socket, shutil, hashlib

ALLOWED = {"iptables", "ip6tables"}

LIBDIR = "/usr/local/lib/ciszterci-tuzfal"
INSTALL_PATH = LIBDIR + "/ciszterci-tuzfal.py"      # root tulajdonú példány, ezt futtatja a pkexec
BIN_PATH = "/usr/local/bin/ciszterci-tuzfal"
DESKTOP_PATH = "/usr/share/applications/ciszterci-tuzfal.desktop"
ICON_PATH = "/usr/share/icons/hicolor/scalable/apps/ciszterci-tuzfal.svg"
LOG = "/var/log/ciszterci-tuzfal-install.log"
REQUIRED = ["python3", "python3-gi", "gir1.2-gtk-3.0", "iptables", "iptables-persistent", "pkexec"]
POLKIT_AGENTS = ["policykit-1-gnome", "polkit-1-gnome", "xfce-polkit", "lxpolkit"]

DESKTOP_FILE = (
    "[Desktop Entry]\nVersion=1.0\nType=Application\n"
    "Name=Ciszterci tűzfal\nName[hu]=Ciszterci tűzfal\nGenericName=Tűzfal\n"
    "Comment=Az iptables tűzfal egyszerű, grafikus kezelése\n"
    "Exec=/usr/local/bin/ciszterci-tuzfal\nIcon=ciszterci-tuzfal\nTerminal=false\n"
    "Categories=System;Security;\nKeywords=tűzfal;firewall;iptables;nat;hálózat;\n")

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#2dd4bf"/><stop offset="1" stop-color="#0f766e"/></linearGradient></defs>
<path d="M64 8 L112 26 V62 C112 92 92 112 64 122 C36 112 16 92 16 62 V26 Z" fill="url(#g)"/>
<ellipse cx="62" cy="70" rx="27" ry="13" transform="rotate(-22 62 70)" fill="#fff"/>
<circle cx="84" cy="56" r="10" fill="#fff"/>
<path d="M91 53 L114 42 L92 59 Z" fill="#fff"/>
<path d="M50 66 C40 38 64 28 82 34 C72 46 62 57 50 66 Z" fill="#ccfbf1"/>
<path d="M38 80 L18 94 L46 84 Z" fill="#fff"/>
<circle cx="86" cy="54" r="2.6" fill="#0f766e"/>
</svg>
"""

# Gyakori portok -> a megjegyzés rovatba kerülő rövid név
SERVICES = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 67: "dhcp-szerver", 68: "dhcp",
    69: "tftp", 80: "web", 110: "pop3", 123: "ntp", 137: "netbios", 138: "netbios", 139: "netbios", 143: "imap", 389: "ldap",
    443: "https", 445: "samba", 465: "smtps", 514: "syslog", 548: "afp", 587: "smtp", 631: "nyomtatás",
    636: "ldaps", 873: "rsync", 993: "imaps", 995: "pop3s", 1194: "openvpn", 1883: "mqtt",
    1900: "upnp", 2049: "nfs", 3306: "mysql", 3389: "rdp", 5060: "sip", 5353: "mdns",
    5432: "postgres", 5900: "vnc", 6379: "redis", 8006: "proxmox", 8008: "matrix",
    8080: "web (alt)", 8096: "jellyfin", 8443: "https (alt)", 8448: "matrix (fed)",
    9090: "cockpit", 9100: "nyomtató", 11100: "veyon", 11400: "veyon-demo",
    25565: "minecraft", 32400: "plex", 51820: "wireguard", 53317: "localsend",
}


def service_comment(proto, port):
    port = str(port)
    if ":" in port:
        return "port-tartomány"
    try:
        n = int(port)
    except ValueError:
        return "egyéb"
    if n in SERVICES:
        return SERVICES[n]
    try:
        return socket.getservbyport(n, proto)
    except OSError:
        return "egyéb"


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
    return all(have(c) for c in (
        "iptables", "ip6tables", "iptables-save", "ip6tables-save", "iptables-restore",
        "ip6tables-restore", "pkexec", "netfilter-persistent"))


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
        subprocess.run(["notify-send", "Ciszterci tűzfal", msg], check=False)


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


def log(msg):
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
    r = subprocess.run(["dpkg-query", "-W", "-f=${Status}", p], capture_output=True, text=True)
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
    log("== Ciszterci tűzfal telepítése ==")
    need = [p for p in REQUIRED if not pkg_ok(p)]
    if need:
        log("Hiányzó csomagok telepítése: " + ", ".join(need))
        if "iptables-persistent" in need:
            subprocess.run(["debconf-set-selections"], text=True, input=(
                "iptables-persistent iptables-persistent/autosave_v4 boolean false\n"
                "iptables-persistent iptables-persistent/autosave_v6 boolean false\n"))
        sh(["apt-get", "update"])
        if sh(["apt-get", "install", "-y"] + need) != 0:
            log(f"HIBA: a csomagtelepítés nem sikerült (részletek: {LOG}).")
            return 1
    agent = subprocess.run(["pgrep", "-f", "polkit.*agent|polkit-gnome|xfce-polkit|lxpolkit|polkit-kde"],
                           capture_output=True).returncode == 0
    if not agent:
        for c in POLKIT_AGENTS:
            if sh(["apt-cache", "show", c]) == 0:
                log(f"Polkit hitelesítő ügynök telepítése: {c} (kijelentkezés/belépés után él)")
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
    sh(["systemctl", "enable", "netfilter-persistent"])
    refresh_caches()
    log("Kész: Alkalmazásmenü › Rendszer › Ciszterci tűzfal (parancs: ciszterci-tuzfal)")
    return 0


def uninstall_main():
    for p in (BIN_PATH, DESKTOP_PATH, ICON_PATH):
        try:
            os.remove(p)
        except OSError:
            pass
    shutil.rmtree(LIBDIR, ignore_errors=True)
    refresh_caches()
    print("Eltávolítva. A csomagokat és a mentett szabályokat nem töröltem.")
    return 0


# ---------------------------------------------------------------- root segéd
def helper_main():
    for line in sys.stdin:
        try:
            req = json.loads(line)
            if "restore" in req:
                tool = "ip6tables-restore" if req.get("v") == "v6" else "iptables-restore"
                p = subprocess.run([tool], input=req["restore"], capture_output=True, encoding="utf-8")
                res = {"rc": p.returncode, "out": "", "err": p.stderr}
            elif "forward" in req:
                on = "1" if req["forward"] else "0"
                with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
                    f.write(on)
                os.makedirs("/etc/sysctl.d", exist_ok=True)
                with open("/etc/sysctl.d/99-ciszterci-tuzfal.conf", "w") as f:
                    f.write(f"net.ipv4.ip_forward = {on}\n")
                res = {"rc": 0, "out": "", "err": ""}
            elif "save" in req:
                v = "v6" if req["save"] == "v6" else "v4"
                tool = "ip6tables-save" if v == "v6" else "iptables-save"
                p = subprocess.run([tool], capture_output=True, encoding="utf-8")
                if p.returncode == 0:
                    os.makedirs("/etc/iptables", exist_ok=True)
                    with open(f"/etc/iptables/rules.{v}", "w", encoding="utf-8") as f:
                        f.write(p.stdout)
                res = {"rc": p.returncode, "out": f"Mentve: /etc/iptables/rules.{v}",
                       "err": p.stderr}
            else:
                argv = req["argv"]
                if argv[0] not in ALLOWED:
                    raise ValueError("nem engedélyezett parancs")
                p = subprocess.run(argv, capture_output=True, encoding="utf-8")
                res = {"rc": p.returncode, "out": p.stdout, "err": p.stderr}
        except Exception as e:
            res = {"rc": 1, "out": "", "err": str(e)}
        print(json.dumps(res), flush=True)


class Helper:
    def __init__(self):
        self.p = None

    def _start(self):
        if self.p is None or self.p.poll() is not None:
            self.p = subprocess.Popen(
                ["pkexec", "/usr/bin/python3", INSTALL_PATH, "--helper"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8")

    def call(self, req):
        self._start()
        try:
            self.p.stdin.write(json.dumps(req) + "\n")
            self.p.stdin.flush()
            line = self.p.stdout.readline()
            if not line:
                return 126, "", "A hitelesítés megszakadt vagy a segéd leállt."
            r = json.loads(line)
            return r["rc"], r["out"], r["err"]
        except (BrokenPipeError, OSError):
            return 126, "", "A segédfolyamat nem érhető el."

    def run(self, argv):
        return self.call({"argv": argv})

    def save(self, v):
        return self.call({"save": v})

    def restore(self, v, text):
        return self.call({"restore": text, "v": v})

    def forward(self, on):
        return self.call({"forward": bool(on)})


# ---------------------------------------------------------------------- GUI
def parse_ports(s):
    out = []
    for p in s.replace(" ", "").split(","):
        if not p:
            continue
        if not re.fullmatch(r"\d{1,5}(:\d{1,5})?", p):
            return None
        n = [int(x) for x in p.split(":")]
        if any(x < 1 or x > 65535 for x in n) or (len(n) == 2 and n[0] >= n[1]):
            return None
        out.append(p)
    return out


def desktop_template(v6, ssh, tcp, udp, samba=False, dom=False, net=""):
    def c(text):
        return f'-m comment --comment "{text}"'
    r = [":INPUT DROP [0:0]", ":FORWARD DROP [0:0]", ":OUTPUT ACCEPT [0:0]",
         f"-A INPUT -i lo {c('loopback')} -j ACCEPT",
         f"-A INPUT -m conntrack --ctstate INVALID {c('érvénytelen')} -j DROP",
         f"-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED {c('válaszforgalom')} -j ACCEPT"]
    if v6:
        r += [f"-A INPUT -p ipv6-icmp {c('icmpv6')} -j ACCEPT",
              f"-A INPUT -d fe80::/10 -p udp --dport 546 {c('dhcpv6')} -j ACCEPT"]
    else:
        r += [f"-A INPUT -p icmp --icmp-type echo-request -m limit --limit 5/second "
              f"{c('ping')} -j ACCEPT",
              f"-A INPUT -p udp --sport 67 --dport 68 {c('dhcp')} -j ACCEPT"]
    if ssh:
        r.append(f"-A INPUT -p tcp --dport 22 -m conntrack --ctstate NEW "
                 f"{c(service_comment('tcp', '22'))} -j ACCEPT")
    if samba and (not v6 or not net):      # korlátozott hálózat esetén csak IPv4-en (IPv6-on nem nyitunk)
        src = f"-s {net} " if (net and not v6) else ""
        r += [f"-A INPUT {src}-p tcp --dport {p} {c(service_comment('tcp', p))} -j ACCEPT"
              for p in ("445", "139")]
        r += [f"-A INPUT {src}-p udp --dport {p} {c(service_comment('udp', p))} -j ACCEPT"
              for p in ("137", "138")]
    if dom and not v6:
        r.append(f"-A INPUT -p udp --sport 137 --dport 137 {c('netbios-válasz')} -j ACCEPT")
    r += [f"-A INPUT -p tcp --dport {p} {c(service_comment('tcp', p))} -j ACCEPT" for p in tcp]
    r += [f"-A INPUT -p udp --dport {p} {c(service_comment('udp', p))} -j ACCEPT" for p in udp]
    return "*filter\n" + "\n".join(r) + "\nCOMMIT\n"


def empty_ruleset():
    def tbl(name, chains):
        return f"*{name}\n" + "".join(f":{c} ACCEPT [0:0]\n" for c in chains) + "COMMIT\n"
    return (tbl("filter", ("INPUT", "FORWARD", "OUTPUT"))
            + tbl("nat", ("PREROUTING", "INPUT", "OUTPUT", "POSTROUTING"))
            + tbl("mangle", ("PREROUTING", "INPUT", "FORWARD", "OUTPUT", "POSTROUTING"))
            + tbl("raw", ("PREROUTING", "OUTPUT")))


def gui_main():
    import ipaddress
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    GLib.set_prgname("ciszterci-tuzfal")
    GLib.set_application_name("Ciszterci tűzfal")
    Gtk.Window.set_default_icon_name("ciszterci-tuzfal")

    class App(Gtk.Window):
        def __init__(self):
            super().__init__(title="Ciszterci tűzfal")
            self.set_default_size(680, 580)
            self.connect("destroy", Gtk.main_quit)
            self.h = Helper()
            self.rules, self.policy = {}, {}

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            root.set_border_width(8)
            self.stack = Gtk.Stack()
            self.stack.add_named(self.build_simple(), "egyszeru")
            self.stack.add_named(root, "halado")
            self.add(self.stack)

            # felső sor
            top = Gtk.Box(spacing=6)
            root.pack_start(top, False, False, 0)
            self.fam = Gtk.ComboBoxText()
            for f in ("IPv4", "IPv6"):
                self.fam.append_text(f)
            self.fam.set_active(0)
            self.tab = Gtk.ComboBoxText()
            for t in ("filter", "nat", "mangle", "raw"):
                self.tab.append_text(t)
            self.tab.set_active(0)
            for w in (Gtk.Label(label="Család:"), self.fam,
                      Gtk.Label(label="Tábla:"), self.tab):
                top.pack_start(w, False, False, 0)
            self.fam.connect("changed", lambda *_: self.refresh())
            self.tab.connect("changed", lambda *_: self.refresh())
            for text, cb in (("Frissítés", lambda *_: self.refresh()),
                             ("Mentés lemezre (perzisztens)", self.on_save),
                             ("← Egyszerű nézet", lambda *_: self.show_mode(False))):
                b = Gtk.Button(label=text)
                b.connect("clicked", cb)
                top.pack_start(b, False, False, 0)

            row2 = Gtk.Box(spacing=6)
            row2.pack_start(Gtk.Label(label="Gyorsműveletek:"), False, False, 0)
            for text, cb in (("Alapértelmezett desktop sablon", self.on_template),
                             ("NAT: internetmegosztás", self.on_nat_masq),
                             ("NAT: port továbbítás", self.on_nat_dnat),
                             ("NAT: SNAT", self.on_nat_snat),
                             ("Összes szabály törlése", self.on_wipe)):
                b = Gtk.Button(label=text)
                b.connect("clicked", cb)
                row2.pack_start(b, False, False, 0)
            root.pack_start(row2, False, False, 0)

            # közép
            paned = Gtk.Paned()
            root.pack_start(paned, True, True, 0)

            # bal: láncok
            left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.cstore = Gtk.ListStore(str, str)
            self.cview = Gtk.TreeView(model=self.cstore)
            for i, t in enumerate(("Lánc", "Policy")):
                self.cview.append_column(
                    Gtk.TreeViewColumn(t, Gtk.CellRendererText(), text=i))
            self.cview.get_selection().connect("changed", lambda *_: self.show_rules())
            sw = Gtk.ScrolledWindow()
            sw.add(self.cview)
            left.pack_start(sw, True, True, 0)
            for text, cb in (("Új lánc", self.on_new_chain),
                             ("Lánc törlése", self.on_del_chain),
                             ("Lánc ürítése", self.on_flush),
                             ("Policy váltása", self.on_policy)):
                b = Gtk.Button(label=text)
                b.connect("clicked", cb)
                left.pack_start(b, False, False, 0)
            paned.pack1(left, False, False)

            # jobb: szabályok
            right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.rstore = Gtk.ListStore(int, str)
            self.rview = Gtk.TreeView(model=self.rstore)
            self.rview.append_column(
                Gtk.TreeViewColumn("#", Gtk.CellRendererText(), text=0))
            self.rview.append_column(
                Gtk.TreeViewColumn("Szabály", Gtk.CellRendererText(), text=1))
            sw2 = Gtk.ScrolledWindow()
            sw2.add(self.rview)
            right.pack_start(sw2, True, True, 0)
            btns = Gtk.Box(spacing=6)
            for text, cb in (("Új szabály", self.on_add),
                             ("Szerkesztés (nyers)", self.on_edit),
                             ("Feljebb", lambda *_: self.on_move(-1)),
                             ("Lejjebb", lambda *_: self.on_move(1)),
                             ("Törlés", self.on_del)):
                b = Gtk.Button(label=text)
                b.connect("clicked", cb)
                btns.pack_start(b, False, False, 0)
            right.pack_start(btns, False, False, 0)
            paned.pack2(right, True, False)
            paned.set_position(240)

            # nyers parancs
            raw = Gtk.Box(spacing=6)
            self.raw = Gtk.Entry()
            self.raw.set_placeholder_text(
                "Nyers iptables argumentumok, pl.: -t nat -A POSTROUTING -o eth0 -j MASQUERADE")
            self.raw.connect("activate", self.on_raw)
            rb = Gtk.Button(label="Futtat")
            rb.connect("clicked", self.on_raw)
            raw.pack_start(self.raw, True, True, 0)
            raw.pack_start(rb, False, False, 0)
            root.pack_start(raw, False, False, 0)

            self.status = Gtk.Label(xalign=0)
            self.status.set_line_wrap(True)
            root.pack_start(self.status, False, False, 0)

            self.show_all()
            self.stack.set_visible_child_name("egyszeru")
            self.refresh()
            self.refresh_simple()

        # -------- segédek
        def tool(self):
            return "ip6tables" if self.fam.get_active_text() == "IPv6" else "iptables"

        def ipt(self, *args, table=True):
            argv = [self.tool(), "-w"]
            if table:
                argv += ["-t", self.tab.get_active_text()]
            rc, out, err = self.h.run(argv + list(args))
            self.say(rc, err.strip() or "OK")
            return rc, out, err

        def say(self, rc, msg):
            t = ("✔ " if rc == 0 else "✖ ") + msg
            self.status.set_text(t)
            self.sstatus.set_text(t)

        def confirm(self, text):
            d = Gtk.MessageDialog(transient_for=self, modal=True,
                                  message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.OK_CANCEL, text=text)
            ok = d.run() == Gtk.ResponseType.OK
            d.destroy()
            return ok

        def ask(self, title, fields):
            """fields: [(felirat, alapérték | [opciók])]. Visszatér: [értékek] vagy None."""
            d = Gtk.Dialog(title=title, transient_for=self, modal=True)
            d.add_buttons("Mégse", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
            g = Gtk.Grid(column_spacing=8, row_spacing=6)
            g.set_border_width(10)
            d.get_content_area().add(g)
            widgets = []
            for i, (label, val) in enumerate(fields):
                g.attach(Gtk.Label(label=label, xalign=1), 0, i, 1, 1)
                if isinstance(val, bool):
                    w = e = Gtk.CheckButton()
                    w.set_active(val)
                elif isinstance(val, list):
                    w = Gtk.ComboBoxText.new_with_entry()
                    for o in val:
                        w.append_text(o)
                    w.set_active(0)
                    e = w.get_child()
                else:
                    w = e = Gtk.Entry()
                    e.set_text(val)
                    e.set_width_chars(40)
                if not isinstance(e, Gtk.CheckButton):
                    e.set_activates_default(True)
                g.attach(w, 1, i, 1, 1)
                widgets.append(e)
            d.set_default_response(Gtk.ResponseType.OK)
            d.show_all()
            ok = d.run() == Gtk.ResponseType.OK
            vals = [("1" if w.get_active() else "0") if isinstance(w, Gtk.CheckButton)
                    else w.get_text().strip() for w in widgets]
            d.destroy()
            return vals if ok else None

        def cur_chain(self):
            m, it = self.cview.get_selection().get_selected()
            return m[it][0] if it else None

        def cur_rule(self):
            m, it = self.rview.get_selection().get_selected()
            return (m[it][0], m[it][1]) if it else (None, None)

        # -------- adatok
        def refresh(self):
            keep = self.cur_chain()
            rc, out, _ = self.ipt("-S")
            self.rules, self.policy = {}, {}
            if rc == 0:
                for line in out.splitlines():
                    try:
                        p = shlex.split(line)
                    except ValueError:
                        continue
                    if p[0] == "-P":
                        self.policy[p[1]] = p[2]
                        self.rules.setdefault(p[1], [])
                    elif p[0] == "-N":
                        self.policy[p[1]] = "-"
                        self.rules.setdefault(p[1], [])
                    elif p[0] == "-A":
                        self.rules.setdefault(p[1], []).append(line)
            self.cstore.clear()
            sel = None
            for c in self.rules:
                it = self.cstore.append([c, self.policy.get(c, "-")])
                if c == keep:
                    sel = it
            if sel is None and len(self.cstore):
                sel = self.cstore.get_iter_first()
            if sel:
                self.cview.get_selection().select_iter(sel)
            self.show_rules()

        def show_rules(self):
            self.rstore.clear()
            c = self.cur_chain()
            for i, line in enumerate(self.rules.get(c, []), 1):
                self.rstore.append([i, line.split(" ", 2)[2] if line.count(" ") >= 2 else ""])

        # -------- szabályok
        def on_add(self, *_):
            c = self.cur_chain() or "INPUT"
            v = self.ask("Új szabály", [
                ("Lánc", c),
                ("Hova", ["Végére (-A)", "Elejére (-I)"]),
                ("Protokoll", ["tcp", "udp", "icmp", "all"]),
                ("Forrás (-s)", ""), ("Cél (-d)", ""),
                ("Forrásport", ""), ("Célport (vesszővel több)", ""),
                ("Bejövő interfész (-i)", ""), ("Kimenő interfész (-o)", ""),
                ("Állapot (conntrack)", ["", "NEW", "ESTABLISHED,RELATED", "NEW,ESTABLISHED,RELATED"]),
                ("Cél (-j)", ["ACCEPT", "DROP", "REJECT", "LOG", "MASQUERADE", "RETURN", "SNAT", "DNAT"]),
                ("Megjegyzés", ""), ("Egyéb paraméterek", ""),
            ])
            if not v:
                return
            chain, where, proto, src, dst, sp, dp, i, o, st, tgt, cm, extra = v
            a = ["-I" if where.startswith("Elejére") else "-A", chain]
            if proto and proto != "all":
                a += ["-p", proto]
            for flag, val in (("-s", src), ("-d", dst), ("-i", i), ("-o", o)):
                if val:
                    a += [flag, val]
            for flag, val in (("--sport", sp), ("--dport", dp)):
                if val:
                    a += (["-m", "multiport", flag.replace("--", "--") + "s", val]
                          if "," in val else [flag, val])
            if st:
                a += ["-m", "conntrack", "--ctstate", st]
            if cm:
                a += ["-m", "comment", "--comment", cm]
            if extra:
                a += shlex.split(extra)
            if tgt:
                a += ["-j", tgt]
            self.ipt(*a)
            self.refresh()

        def on_edit(self, *_):
            n, text = self.cur_rule()
            c = self.cur_chain()
            if n is None:
                return
            v = self.ask("Szabály szerkesztése (nyers argumentumok)", [("Szabály", text)])
            if v and v[0]:
                self.ipt("-R", c, str(n), *shlex.split(v[0]))
                self.refresh()

        def on_del(self, *_):
            n, text = self.cur_rule()
            if n is not None and self.confirm(f"Törlöd a(z) {n}. szabályt?\n{text}"):
                self.ipt("-D", self.cur_chain(), str(n))
                self.refresh()

        def on_move(self, delta):
            n, _t = self.cur_rule()
            c = self.cur_chain()
            if n is None:
                self.say(1, "Előbb jelölj ki egy szabályt.")
                return
            rules = self.rules.get(c, [])
            m = n + delta
            if m < 1 or m > len(rules):
                return
            args = shlex.split(rules[n - 1])[2:]
            # Biztonságos sorrend: előbb beszúrjuk a másolatot, csak utána töröljük az eredetit,
            # így a szabály egy pillanatra sem hiányzik (nem zárod ki magad).
            if delta < 0:
                rc, _, err = self.ipt("-I", c, str(m), *args)
                if rc == 0:
                    rc, _, err = self.ipt("-D", c, str(n + 1))
            else:
                rc, _, err = self.ipt("-I", c, str(m + 1), *args)
                if rc == 0:
                    rc, _, err = self.ipt("-D", c, str(n))
            self.refresh()
            if rc == 0:
                self.rview.get_selection().select_path(Gtk.TreePath(m - 1))
            self.say(rc, "Szabály áthelyezve." if rc == 0 else err.strip())

        # -------- láncok
        def on_new_chain(self, *_):
            v = self.ask("Új lánc", [("Név", "")])
            if v and v[0]:
                self.ipt("-N", v[0])
                self.refresh()

        def on_del_chain(self, *_):
            c = self.cur_chain()
            if c and self.confirm(f"Törlöd a(z) {c} láncot? (csak üres, nem beépített lánc törölhető)"):
                self.ipt("-X", c)
                self.refresh()

        def on_flush(self, *_):
            c = self.cur_chain()
            if c and self.confirm(f"Kiüríted a(z) {c} lánc összes szabályát?"):
                self.ipt("-F", c)
                self.refresh()

        def on_policy(self, *_):
            c = self.cur_chain()
            if not c or self.policy.get(c, "-") == "-":
                self.say(1, "Csak beépített láncnak van policyja.")
                return
            new = "DROP" if self.policy[c] == "ACCEPT" else "ACCEPT"
            if self.confirm(f"{c} policy: {self.policy[c]} → {new}?"):
                self.ipt("-P", c, new)
                self.refresh()

        # -------- sablon és NAT
        def on_template(self, *_):
            v = self.ask("Alapértelmezett desktop sablon", [
                ("SSH engedése (22)", False),
                ("Veyon szolgáltatás engedése (11100)", False),
                ("Veyon bemutató mód engedése (11400, tanári gép)", False),
                ("Webszerver engedése (80, 443)", False),
                ("LocalSend engedése (53317 tcp+udp)", False),
                ("Samba fájlmegosztás engedése (445, 139, 137-138/udp)", False),
                ("Samba tartományi kliens (NetBIOS-válaszok, 137/udp)", False),
                ("Samba csak ebből a hálózatból (pl. 10.0.0.0/24; üres = mindenhonnan)", ""),
                ("További bejövő TCP portok (vesszővel)", ""),
                ("További bejövő UDP portok (vesszővel)", "")])
            if not v:
                return
            net = ""
            if v[7]:
                if not self.ok_net(v[7]):
                    self.say(1, "Hibás hálózat (pl. 10.0.0.0/24).")
                    return
                net = str(ipaddress.IPv4Network(v[7], strict=False))
            extra_tcp, udp = parse_ports(v[8]), parse_ports(v[9])
            if extra_tcp is None or udp is None:
                self.say(1, "Hibás portlista (pl.: 80,443,8000:8010).")
                return
            if v[4] == "1" and "53317" not in udp:
                udp.append("53317")      # LocalSend felfedezés (multicast) UDP-n megy
            tcp = []
            for on, ports in ((v[1] == "1", ["11100"]), (v[2] == "1", ["11400"]),
                              (v[3] == "1", ["80", "443"]), (v[4] == "1", ["53317"]),
                              (True, extra_tcp)):
                for pt in (ports if on else []):
                    if pt not in tcp:
                        tcp.append(pt)
            if not self.confirm(
                    "Ez LECSERÉLI a teljes filter táblát (IPv4 és IPv6): a meglévő szabályok és "
                    "egyedi láncok (pl. Docker) törlődnek.\n\nPolicy: INPUT/FORWARD DROP, "
                    "OUTPUT ACCEPT; engedett: loopback, felépült kapcsolatok, ping, DHCP, "
                    "ICMPv6. Folytatod?"):
                return
            for ver in ("v4", "v6"):
                text = desktop_template(ver == "v6", v[0] == "1", tcp, udp,
                                        samba=v[5] == "1", dom=v[6] == "1", net=net)
                rc, _, err = self.h.restore(ver, text)
                if rc != 0:
                    self.refresh()
                    self.say(rc, f"{ver}: {err.strip()}")
                    return
            self.refresh()
            self.say(0, "Sablon betöltve (a futó rendszerbe). Tartós mentés: „Mentés lemezre”, "
                        "külön IPv4-re és IPv6-ra.")

        def ifaces(self):
            try:
                l = [i for i in sorted(os.listdir("/sys/class/net")) if i != "lo"]
            except OSError:
                l = []
            return l or [""]

        def ensure(self, table, chain, args, tool="iptables", insert=False):
            base = [tool, "-w", "-t", table]
            rc, _, _ = self.h.run(base + ["-C", chain] + args)
            if rc == 0:
                return 0, "már létezik"
            rc, _, err = self.h.run(base + ["-I" if insert else "-A", chain] + args)
            return rc, err.strip()

        def run_nat(self, steps):
            rc, _, err = self.h.forward(True)
            if rc != 0:
                self.say(rc, err.strip() or "A továbbítás bekapcsolása nem sikerült.")
                return
            for table, chain, args in steps:
                rc, msg = self.ensure(table, chain, args)
                if rc != 0:
                    self.refresh()
                    self.say(rc, msg or "hiba")
                    return
            self.fam.set_active(0)
            self.tab.set_active(1)
            self.refresh()
            self.say(0, "NAT-szabályok felvéve (IPv4), továbbítás bekapcsolva.")

        @staticmethod
        def ok_if(s):
            return bool(re.fullmatch(r"[A-Za-z0-9_.@-]{1,15}", s))

        @staticmethod
        def ok_net(s):
            try:
                ipaddress.IPv4Network(s, strict=False)
                return True
            except ValueError:
                return False

        @staticmethod
        def ok_ip(s):
            try:
                ipaddress.IPv4Address(s)
                return True
            except ValueError:
                return False

        @staticmethod
        def ok_port(s):
            return s.isdigit() and 1 <= int(s) <= 65535

        EST = ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED",
               "-m", "comment", "--comment", "nat válasz", "-j", "ACCEPT"]

        @staticmethod
        def cm(t):
            return ["-m", "comment", "--comment", t]

        def on_nat_masq(self, *_):
            ifs = self.ifaces()
            v = self.ask("NAT: internetmegosztás (maszkolás)", [
                ("Külső (WAN) interfész", ifs),
                ("Belső (LAN) interfész", ifs[::-1]),
                ("Belső hálózat (opcionális, pl. 192.168.1.0/24)", "")])
            if not v:
                return
            wan, lan, net = v
            if not (self.ok_if(wan) and self.ok_if(lan) and wan != lan):
                self.say(1, "Adj meg két különböző, érvényes interfészt.")
                return
            if net and not self.ok_net(net):
                self.say(1, "Hibás hálózat (pl. 192.168.1.0/24).")
                return
            self.run_nat([
                ("nat", "POSTROUTING", ["-o", wan] + (["-s", net] if net else [])
                 + self.cm("internetmegosztás") + ["-j", "MASQUERADE"]),
                ("filter", "FORWARD", ["-i", lan, "-o", wan] + self.cm("internetmegosztás")
                 + ["-j", "ACCEPT"]),
                ("filter", "FORWARD", ["-i", wan, "-o", lan] + self.EST)])

        def on_nat_dnat(self, *_):
            v = self.ask("NAT: port továbbítás (DNAT)", [
                ("Külső (WAN) interfész", self.ifaces()),
                ("Protokoll", ["tcp", "udp"]),
                ("Külső port", ""),
                ("Belső gép IP-címe", ""),
                ("Belső port (üres = ugyanaz)", "")])
            if not v:
                return
            wan, proto, ext, ip, inp = v
            inp = inp or ext
            if not (self.ok_if(wan) and proto in ("tcp", "udp") and self.ok_port(ext)
                    and self.ok_ip(ip) and self.ok_port(inp)):
                self.say(1, "Hibás adat (interfész, protokoll, port vagy IP).")
                return
            self.run_nat([
                ("nat", "PREROUTING", ["-i", wan, "-p", proto, "--dport", ext]
                 + self.cm(f"átirányítás {proto}/{ext}")
                 + ["-j", "DNAT", "--to-destination", f"{ip}:{inp}"]),
                ("filter", "FORWARD", ["-i", wan, "-d", ip, "-p", proto, "--dport", inp,
                                       "-m", "conntrack", "--ctstate", "NEW"]
                 + self.cm(f"átirányítás {proto}/{inp}") + ["-j", "ACCEPT"]),
                ("filter", "FORWARD", self.EST)])

        def on_nat_snat(self, *_):
            v = self.ask("NAT: SNAT (fix forráscím)", [
                ("Külső (WAN) interfész", self.ifaces()),
                ("Forrás hálózat (pl. 192.168.1.0/24)", ""),
                ("Átírt forráscím (a WAN-IP)", "")])
            if not v:
                return
            wan, net, ip = v
            if not (self.ok_if(wan) and self.ok_net(net) and self.ok_ip(ip)):
                self.say(1, "Hibás adat (interfész, hálózat vagy IP).")
                return
            self.run_nat([
                ("nat", "POSTROUTING", ["-o", wan, "-s", net] + self.cm("snat")
                 + ["-j", "SNAT", "--to-source", ip]),
                ("filter", "FORWARD", ["-s", net, "-o", wan] + self.cm("snat")
                 + ["-j", "ACCEPT"]),
                ("filter", "FORWARD", self.EST)])

        # -------- egyszerű nézet
        def then(self, f):
            return lambda *_: (f(), self.refresh_simple())

        def build_simple(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.set_border_width(16)
            self.state = Gtk.Label(xalign=0)
            self.state.set_use_markup(True)
            self.state.set_line_wrap(True)
            box.pack_start(self.state, False, False, 0)
            box.pack_start(Gtk.Label(label="Megnyitott bejövő portok:", xalign=0), False, False, 0)
            self.pstore = Gtk.ListStore(str, str, str, str)
            self.pview = Gtk.TreeView(model=self.pstore)
            for i, t in enumerate(("Protokoll", "Port", "Megjegyzés")):
                self.pview.append_column(
                    Gtk.TreeViewColumn(t, Gtk.CellRendererText(), text=i))
            sw = Gtk.ScrolledWindow()
            sw.set_min_content_height(150)
            sw.add(self.pview)
            box.pack_start(sw, True, True, 0)
            prow = Gtk.Box(spacing=6)
            for text, cb in (("Port megnyitása", self.on_open_port),
                             ("Kijelölt port lezárása", self.on_close_port)):
                b = Gtk.Button(label=text)
                b.connect("clicked", self.then(cb))
                prow.pack_start(b, False, False, 0)
            box.pack_start(prow, False, False, 0)
            box.pack_start(Gtk.Separator(), False, False, 4)
            for text, cb in (("Védelem bekapcsolása (ajánlott alapbeállítás)", self.on_template),
                             ("Internetmegosztás más gépeknek (NAT)", self.on_nat_masq),
                             ("Összes szabály törlése (tűzfal kikapcsolása)", self.on_wipe),
                             ("Mentés (újraindítás után is megmarad)", self.on_save_both)):
                b = Gtk.Button(label=text)
                b.connect("clicked", self.then(cb))
                box.pack_start(b, False, False, 0)
            adv = Gtk.Button(label="Haladó beállítások…")
            adv.connect("clicked", lambda *_: self.show_mode(True))
            box.pack_start(adv, False, False, 0)
            self.sstatus = Gtk.Label(xalign=0)
            self.sstatus.set_line_wrap(True)
            box.pack_start(self.sstatus, False, False, 0)
            return box

        def show_mode(self, advanced):
            if advanced:
                self.refresh()
                self.stack.set_visible_child_name("halado")
                self.resize(1050, 620)
            else:
                self.refresh_simple()
                self.stack.set_visible_child_name("egyszeru")
                self.resize(680, 580)

        def refresh_simple(self):
            prot, ports, ok = {}, [], True
            for name, tool in (("IPv4", "iptables"), ("IPv6", "ip6tables")):
                rc, out, _ = self.h.run([tool, "-w", "-t", "filter", "-S", "INPUT"])
                if rc != 0:
                    ok = False
                    continue
                pol, last = "ACCEPT", None
                for line in out.splitlines():
                    try:
                        p = shlex.split(line)
                    except ValueError:
                        continue
                    if p[:2] == ["-P", "INPUT"]:
                        pol = p[2]
                    elif p[:2] == ["-A", "INPUT"]:
                        last = p
                        try:
                            if (name == "IPv4" and "-p" in p and "--dport" in p
                                    and p[p.index("-j") + 1] == "ACCEPT"
                                    and not (("-i" in p) and p[p.index("-i") + 1] == "lo")):
                                pr, pt = p[p.index("-p") + 1], p[p.index("--dport") + 1]
                                c = (p[p.index("--comment") + 1] if "--comment" in p
                                     else service_comment(pr, pt))
                                ports.append([pr, pt, c, shlex.join(p[2:])])
                        except (ValueError, IndexError):
                            pass
                prot[name] = (pol in ("DROP", "REJECT")
                              or (last is not None and len(last) == 4 and last[2] == "-j"
                                  and last[3] in ("DROP", "REJECT")))
            self.pstore.clear()
            for r in ports:
                self.pstore.append(r)
            if not ok:
                txt = "<b>Nem sikerült lekérdezni a tűzfal állapotát.</b> (Megszakadt a hitelesítés?)"
            elif all(prot.values()):
                txt = ("<b>Tűzfal: védett.</b> A bejövő forgalom alapból tiltott, "
                       "kivéve az alább felsorolt engedélyeket.")
            elif not any(prot.values()):
                txt = "<b>Tűzfal: nincs védelem.</b> Minden bejövő forgalom engedett."
            else:
                txt = ("<b>Részleges védelem.</b> " + ", ".join(
                    f"{k}: {'védett' if v else 'nyitott'}" for k, v in prot.items()))
            self.state.set_markup(txt)

        def on_open_port(self, *_):
            v = self.ask("Port megnyitása (bejövő)", [
                ("Protokoll", ["tcp", "udp"]),
                ("Port (vesszővel több, tartomány: 8000:8010)", ""),
                ("Megjegyzés (üresen: automatikus, pl. ssh, web)", "")])
            if not v:
                return
            proto, port, cm = v
            lst = parse_ports(port)
            if proto not in ("tcp", "udp") or not lst:
                self.say(1, "Hibás protokoll vagy port.")
                return
            for pt in lst:
                args = ["-p", proto, "--dport", pt, "-m", "comment", "--comment",
                        cm or service_comment(proto, pt), "-j", "ACCEPT"]
                for tool in ("iptables", "ip6tables"):
                    rc, msg = self.ensure("filter", "INPUT", args, tool=tool, insert=True)
                    if rc != 0:
                        self.say(rc, f"{tool}: {msg}")
                        return
            self.refresh()
            self.say(0, "Port megnyitva (IPv4 és IPv6). Tartóssá a „Mentés” teszi.")

        def on_close_port(self, *_):
            m, it = self.pview.get_selection().get_selected()
            if not it:
                self.say(1, "Előbb jelölj ki egy portot a listában.")
                return
            proto, port, _c, rule = m[it]
            if not self.confirm(f"Lezárod a bejövő {proto}/{port} portot?"):
                return
            args = shlex.split(rule)
            rc4, _, err = self.h.run(["iptables", "-w", "-t", "filter", "-D", "INPUT"] + args)
            self.h.run(["ip6tables", "-w", "-t", "filter", "-D", "INPUT"] + args)
            self.refresh()
            self.say(rc4, "Port lezárva." if rc4 == 0 else err.strip())

        def on_wipe(self, *_):
            if not self.confirm(
                    "Összes tűzfalszabály és egyedi lánc törlése (IPv4 és IPv6, minden tábla: "
                    "filter, nat, mangle, raw)?\n\nUtána minden forgalom engedett lesz, "
                    "vagyis nem lesz tűzfalvédelem."):
                return
            text = empty_ruleset()
            for ver in ("v4", "v6"):
                rc, _, err = self.h.restore(ver, text)
                if rc != 0:
                    self.refresh()
                    self.say(rc, f"{ver}: {err.strip()}")
                    return
            self.refresh()
            msg = "Minden szabály törölve, a tűzfal ki van kapcsolva."
            if self.confirm("Elmentsem az üres állapotot is, hogy újraindítás után is így maradjon?"):
                self.on_save_both()
                return
            self.say(0, msg + " Újraindítás után a korábban mentett szabályok visszatölthetnek.")

        def on_save_both(self, *_):
            for v in ("v4", "v6"):
                rc, out, err = self.h.save(v)
                if rc != 0:
                    self.say(rc, f"{v}: {err.strip()}")
                    return
            self.say(0, "Elmentve (IPv4 és IPv6): újraindítás után is megmarad.")

        # -------- egyéb
        def on_raw(self, *_):
            try:
                args = shlex.split(self.raw.get_text())
            except ValueError as e:
                self.say(1, str(e))
                return
            if args:
                rc, out, err = self.ipt(*args, table=False)
                if out.strip():
                    self.status.set_text(out.strip()[:2000])
                self.refresh()

        def on_save(self, *_):
            v = "v6" if self.tool() == "ip6tables" else "v4"
            rc, out, err = self.h.save(v)
            self.say(rc, out if rc == 0 else err)

    App()
    Gtk.main()


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
        print("Kész. Normál felhasználóként indítsd: ciszterci-tuzfal (vagy az alkalmazásmenüből).")
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
