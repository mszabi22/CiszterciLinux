#!/bin/bash
# Futtatás: sudo ./build.sh   (Debian/Ubuntu gazdán, root jogosultsággal, internettel)
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" -eq 0 ] || { echo "Root kell: sudo ./build.sh"; exit 1; }

apt-get install -y live-build debootstrap squashfs-tools xorriso curl gnupg jq

INC=config/includes.chroot
mkdir -p "$INC/usr/share/keyrings" "$INC/opt/kolibri-debs"

echo ">> Brave tároló kulcsa"
curl -fsSL https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
     -o "$INC/usr/share/keyrings/brave-browser-archive-keyring.gpg"

echo ">> Signal tároló kulcsa"
curl -fsSL https://updates.signal.org/desktop/apt/keys.asc | gpg --dearmor \
     > "$INC/usr/share/keyrings/signal-desktop-keyring.gpg"

echo ">> VeraCrypt (hivatalos Debian 13 csomag, GitHub legfrissebb kiadás)"
url=$(curl -fsSL https://api.github.com/repos/veracrypt/VeraCrypt/releases/latest \
      | jq -r '[.assets[].browser_download_url | select(test("/veracrypt-[0-9.]+-Debian-13-amd64\\.deb$"))][0]')
if [ -z "$url" ] || [ "$url" = "null" ]; then
    echo "HIBA: nem találtam Debian 13 VeraCrypt csomagot a legfrissebb kiadásban."
    echo "Töltsd le kézzel a veracrypt.fr oldalról ide: $INC/opt/kolibri-debs/"
    exit 1
fi
rm -f "$INC"/opt/kolibri-debs/veracrypt-*.deb
curl -fsSL "$url" -o "$INC/opt/kolibri-debs/$(basename "$url")"

lb clean --purge || true
lb config
lb build 2>&1 | tee build.log
ls -lh ./*.iso

DATUM=`date +%y.%m`; mv ciszterci-amd64.hybrid.iso CiszterciLinux-$DATUM-amd64.iso; md5sum CiszterciLinux-$DATUM-amd64.iso > CiszterciLinux-$DATUM-amd64.iso.md5; chown -R majorsza:majorsza CiszterciLinux-*