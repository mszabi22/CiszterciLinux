#!/bin/bash
set -euo pipefail

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
WHITE='\033[0m'

echo -e "${YELLOW}Rendszergazdai eszközök eltávolítása...${WHITE}"

PACKAGES=(
    gprename gparted netdiscover sshuttle grub-customizer
    remmina remmina-plugin-rdp remmina-plugin-vnc
    net-tools dnsutils arping zenity chntpw hardinfo
    acpidump sysbench dislocker stress s-tui traceroute
    iputils-ping wireshark tigervnc-viewer tigervnc-tools
)

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Ezt a scriptet rendszergazdai jogosultsággal kell futtatni.${WHITE}" >&2
    exit 1
fi

echo "A telepítő által felrakott APT-csomagok eltávolítása..."
apt-get purge -y "${PACKAGES[@]}"

echo "A WinBox fájlok és parancsikonok eltávolítása..."

# Csak a WinBox saját, ismert útvonalait töröljük.
if [[ -L /usr/local/bin/winbox ]]; then
    rm -f /usr/local/bin/winbox
elif [[ -e /usr/local/bin/winbox ]]; then
    echo "Figyelem: /usr/local/bin/winbox létezik, de nem szimbolikus link; nem törlöm."
fi

if [[ -L /usr/share/icons/winbox.png ]]; then
    rm -f /usr/share/icons/winbox.png
elif [[ -e /usr/share/icons/winbox.png ]]; then
    echo "Figyelem: /usr/share/icons/winbox.png létezik, de nem szimbolikus link; nem törlöm."
fi

rm -f /usr/share/applications/winbox.desktop
rm -rf /opt/winbox

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

echo -e "${GREEN}A rendszergazdai eszközök eltávolítása befejeződött.${WHITE}"
echo "Megjegyzés: az APT automatikusan telepített függőségeit nem távolítottam el."
