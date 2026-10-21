# Ciszterci Linux

Build:

    sudo ./build.sh

Kipróbálás VM-ben (UEFI):

    qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 \
      -bios /usr/share/ovmf/OVMF.fd -cdrom ciszterci-amd64.hybrid.iso

Testreszabás: csomagok a `config/package-lists/`, beállítások a `config/includes.chroot/`, build-hookok a `config/hooks/live/` alatt.

## Arculat

- `tools/gen_assets.py` újragenerálja a képeket (Plymouth logó, GRUB háttér 1920x1080, syslinux 640x480). Előnézet: `tools/preview/`.
- Plymouth téma: `config/includes.chroot/usr/share/plymouth/themes/ciszterci/`
- kipróbálás: az ISO-t VM-ben indítva
- GRUB (telepített rendszer): `config/includes.chroot/etc/default/grub.d/zz-ciszterci.cfg`
- Élő ISO menü: `config/bootloaders/{grub-pc,syslinux}/splash.png`

## Asztal és alkalmazások

- Windows-szerű elrendezés: alul tálca, balra Start menü (Whisker menu, Super gomb), jobbra tálca-ikonok, hangerő, akksi, óra, "asztal megjelenítése". Win+E = fájlkezelő.
  Beállítások: `config/includes.chroot/etc/skel/.config/xfce4/`
- Háttér és bejelentkező képernyő: ugyanaz a kép, mint a GRUB-ban (`/usr/share/backgrounds/ciszterci/background.png`).
- Alkalmazások: Debian csomagból KeePassXC, Geany, Kleopatra, Nextcloud kliens; a LibreOffice a `trixie-backports`-ból (legfrissebb);
  Brave és Signal a gyártó APT tárolójából; VeraCrypt a hivatalos Debian 13 csomagból; Tuta Mail és LocalSend Flatpakból.
- A letöltések a `build.sh`-ban és a `config/hooks/live/0050-apps.hook.chroot`-ban vannak.
- LocalSend: a tűzfal csak a helyi (privát) hálózatokról engedi a 53317-es portot (`kolibri-ufw.service`).
- A VeraCrypt .deb nem frissül magától: új verzióhoz új ISO kell, vagy kézi telepítés.
