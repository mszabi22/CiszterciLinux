<p align="center">
  <img src="logo.png" alt="Ciszterci Linux logó" width="160">
</p>

<h1 align="center">Ciszterci Linux</h1>

<p align="center">
  <strong>Stabil. Egyszerű. Kezdőbarát.</strong><br>
  Debian 13 alapú, magyar nyelvű Linux Windows-szerű Xfce asztallal.
</p>

<p align="center">
  <a href="https://linux.crnl.hu/">Weboldal</a> ·
  <a href="https://linux.crnl.hu/letoltes.php">Letöltés</a> ·
  <a href="https://linux.crnl.hu/telepites.php">Telepítési útmutató</a> ·
  <a href="https://linux.crnl.hu/kapcsolat.php">Kapcsolat</a>
</p>

---

## Mi ez?

A Ciszterci Linux egy Debian 13 (trixie) alapú, magyar nyelvű, élő és telepíthető Linux-rendszer. A célja, hogy az első percben otthonos legyen mindenkinek, aki Windowsról érkezik: alul a tálca, balra a Start menü, magyar nyelv és billentyűzet alapból, a programok pedig egy grafikus szoftverközpontból, kattintásra telepíthetők.

A rendszer iskolai és oktatási környezetbe készült, de bárki használhatja, aki szeretne megismerkedni a Linuxszal, vagy szabad és adatvédelmi szempontból tudatos rendszert keres. A projekt hivatalos oldala: **<https://linux.crnl.hu/>**

## Főbb jellemzők

- **Debian-alapú stabilitás.** A stabil ágra épül, automatikus biztonsági frissítésekkel.
- **Visszaállíthatóság.** A Timeshift segítségével a rendszer bármikor visszaállítható egy korábbi állapotba.
- **Kezdőbarát.** Windows-szerű asztal, magyar nyelv és billentyűzet, egyszerű telepítő, grafikus szoftverközpont.
- **Adatvédelem.** Előtelepített titkosító és privát kommunikációs eszközök, alapból bekapcsolt tűzfal.
- **Kipróbálható telepítés nélkül.** Élő rendszerként vagy virtuális gépben (például VirtualBoxban) is futtatható.
- **Haladóknak is.** Bash, rendszergazdai feladatok, scriptelés: a mélységre mindig van lehetőség.
- **Szabad és ingyenes.** Nem kell hozzá licenc és regisztráció.

### Technológia

| Elem | Érték |
|---|---|
| Alap | Debian 13 (trixie) |
| Asztali környezet | Xfce |
| Csomagkezelés | apt, deb csomagok, Flatpak |
| Init rendszer | systemd |
| Shell | bash |

### Előtelepített programok

| Program | Forrás |
|---|---|
| [Brave](https://brave.com/) | a gyártó APT tárolója |
| [Signal](https://signal.org/hu/) | a gyártó APT tárolója |
| [LibreOffice](https://hu.libreoffice.org/) | `trixie-backports` (a legfrissebb kiadás) |
| [KeePassXC](https://keepassxc.org/) | Debian csomag |
| [Kleopatra](https://www.openpgp.org/software/kleopatra/) | Debian csomag |
| [Geany](https://www.geany.org/) | Debian csomag |
| [Nextcloud kliens](https://nextcloud.com/) | Debian csomag |
| [VeraCrypt](https://veracrypt.io/en/Home.html) | hivatalos Debian 13 csomag |
| [Tuta Mail](https://tuta.com/hu) | Flatpak |
| [LocalSend](https://localsend.org/) | Flatpak |

## Letöltés és telepítés

Az ISO-képfájl és a telepítési útmutató a projekt weboldalán érhető el:

- Letöltés: <https://linux.crnl.hu/letoltes.php>
- Telepítési útmutató: <https://linux.crnl.hu/telepites.php>

Az ISO-fájlt írhatod USB-meghajtóra, vagy indíthatod virtuális gépből. Telepítés nélkül, élő rendszerként is kipróbálható.

## Fordítás (build)

A rendszer a Debian live-build eszközrendszerére épül. Az ISO elkészítése:

```bash
sudo ./build.sh
```

A repó szerkezete:

| Mappa / fájl | Tartalom |
|---|---|
| `auto/` | a live-build automatizáló scriptjei |
| `config/` | a rendszer konfigurációja (csomaglisták, beállítások, hookok, bootloader képek) |
| `tools/` | segédeszközök, például az arculati képek generálója |
| `build.sh` | az ISO elkészítése |
| `build-update.sh` | frissítő build |
| `logo.png`, `plakat*.png` | logó és plakátok |

### Kipróbálás virtuális gépben (UEFI)

```bash
qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 \
  -bios /usr/share/ovmf/OVMF.fd -cdrom ciszterci-amd64.hybrid.iso
```

### Testreszabás

| Mit | Hol |
|---|---|
| Telepítendő csomagok | `config/package-lists/` |
| Beállítások, fájlok a rendszerbe | `config/includes.chroot/` |
| Build-hookok | `config/hooks/live/` |

## Arculat

- `tools/gen_assets.py` újragenerálja a képeket: Plymouth logó, GRUB háttér (1920×1080), syslinux háttér (640×480). Az előnézet a `tools/preview/` mappában található.
- Plymouth téma: `config/includes.chroot/usr/share/plymouth/themes/ciszterci/`
- GRUB (telepített rendszer): `config/includes.chroot/etc/default/grub.d/zz-ciszterci.cfg`
- Élő ISO menü: `config/bootloaders/{grub-pc,syslinux}/splash.png`
- Az arculati változtatások kipróbálásához indítsd el az ISO-t virtuális gépben.

## Asztal és alkalmazások

- **Elrendezés.** Windows-szerű: alul tálca, balra Start menü (Whisker menü, Super gomb), jobbra tálcaikonok, hangerő, akkumulátor, óra és az „asztal megjelenítése" gomb. `Win+E` a fájlkezelő. A beállítások helye: `config/includes.chroot/etc/skel/.config/xfce4/`
- **Háttér és bejelentkező képernyő.** Ugyanaz a kép, mint a GRUB-ban: `/usr/share/backgrounds/ciszterci/background.png`
- **Alkalmazások letöltése.** A `build.sh` és a `config/hooks/live/0050-apps.hook.chroot` tartalmazza a külső forrásból érkező programok telepítését.
- **LocalSend.** A tűzfal az 53317-es portot csak a helyi (privát) hálózatokról engedi (`kolibri-ufw.service`).
- **VeraCrypt.** A `.deb` csomag nem frissül magától: új verzióhoz új ISO kell, vagy kézi telepítés.

## Hozzájárulás

Hibát találtál, vagy van ötleted? Írj a projekt weboldalán található [kapcsolati oldalon](https://linux.crnl.hu/kapcsolat.php). Csomaglista-módosításokat és arculati javaslatokat is szívesen fogadunk.

## Licenc és jogi tudnivalók

<!-- Ide kerül a build scriptek és konfigurációk licence (pl. MIT vagy GPL-3.0). Add hozzá a LICENSE fájlt a repó gyökerébe, és írd ide a nevét. -->

A Ciszterci Linux a Debian GNU/Linux rendszerre épül, a benne található programok mindegyike a saját licence szerint használható. A Brave, a Signal és a további említett programok nevei a tulajdonosaik védjegyei, a projektnek nincs hivatalos kapcsolata velük.

## Szerző

© 2026 Major Szabolcs · <https://linux.crnl.hu/>
