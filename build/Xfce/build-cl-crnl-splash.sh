#!/bin/bash
set -e

WORKDIR="CiszterciLinux"
ISO_NAME="CiszterciLinux"

apt-get update
apt-get install -y live-build curl wget gnupg  shim-signed grub-efi-amd64-signed

rm -rf $WORKDIR
mkdir $WORKDIR
cd $WORKDIR

# GRUB splash – helyes, relatív útvonal:
mkdir -p config/bootloaders/grub-pc
cp /home/majorsza/forgejo/CiszterciLinux/design/ciszterci_linux_splash.png config/bootloaders/grub-pc/splash.png

lb clean

lb config noauto \
  --mode debian \
  --distribution trixie \
  --architectures amd64 \
  --linux-flavours amd64 \
  --binary-images iso-hybrid \
  --debian-installer none \
  --archive-areas "main contrib non-free non-free-firmware" \
  --debootstrap-options "--variant=minbase" \
  --bootappend-live "boot=live username=live persistence components quiet splash hostname=CiszterciLinux locales=hu_HU.UTF-8 keyboard-layouts=hu timezone=Europe/Budapest" \
  --image-name "$ISO_NAME" \
  --iso-application "$ISO_NAME" \
  --iso-publisher "Sleepy.hu" \
  --iso-volume "$ISO_NAME" \
  --memtest none \
  --interactive shell 

mkdir -p config/package-lists

cat > config/package-lists/desktop.list.chroot <<EOF
systemd-sysv
live-boot
live-config
live-config-systemd
adduser
passwd
login
sudo
task-xfce-desktop
lightdm
lightdm-gtk-greeter
xserver-xorg-core
network-manager

mc
nano
wget
curl
rsync
apt-utils
dialog
gparted

calamares
calamares-settings-debian

cups
printer-driver-cups-pdf
gvfs-fuse
gvfs-backends

firmware-iwlwifi
firmware-atheros
firmware-brcm80211

blueman
vlc
thunderbird
thunderbird-l10n-hu
gimp
simple-scan
eog
imagemagick
zstd

firefox-esr
firefox-esr-l10n-hu

mugshot
keepassxc
geany

ntpsec
zenity

gnupg

wireguard
wireguard-tools

libreoffice
libreoffice-l10n-hu

audacious

nfs-common

bash-completion
screen

samba
smbclient
cifs-utils

openssh-server
apt-transport-https
ttf-mscorefonts-installer
libpam-google-authenticator

gnome-system-tools
gnome-online-accounts
gnome-calendar

kleopatra
geogebra
birdtray

polkitd
pkexec
dbus-user-session
accountsservice
xfce4-session

htop

onionshare
fastfetch
git
deluge
syncthing
qrencode
qreator
ecryptfs-utils
ffmpeg

greybird-gtk-theme
elementary-xfce-icon-theme
adwaita-icon-theme
tango-icon-theme
xfwm4-theme-breeze

gocryptfs

plymouth
plymouth-themes
lightdm-gtk-greeter-settings
EOF

# autologin
mkdir -p config/includes.chroot/etc/lightdm/lightdm.conf.d
cat > config/includes.chroot/etc/lightdm/lightdm.conf.d/01-autologin.conf <<EOF
[Seat:*]
autologin-user=live
autologin-user-timeout=0
EOF

# Plymouth téma fájlok
mkdir -p config/includes.chroot/usr/share/plymouth/themes/ciszterci

cat > config/includes.chroot/usr/share/plymouth/themes/ciszterci/ciszterci.plymouth <<EOF
[Plymouth Theme]
Name=CiszterciLinux
Description=CiszterciLinux boot splash
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/ciszterci
ScriptFile=/usr/share/plymouth/themes/ciszterci/ciszterci.script
EOF

cat > config/includes.chroot/usr/share/plymouth/themes/ciszterci/ciszterci.script <<'EOF'
wallpaper_image = Image("desktop-grub.png");
screen_width = Window.GetWidth();
screen_height = Window.GetHeight();

scaled = wallpaper_image.Scale(screen_width, screen_height);
sprite = Sprite(scaled);
sprite.SetX(0);
sprite.SetY(0);
sprite.SetZ(-100);
EOF

# GRUB háttérkép config (chroot-beli, telepített rendszerhez)
mkdir -p config/includes.chroot/etc/default/grub.d
cat > config/includes.chroot/etc/default/grub.d/99-ciszterci.cfg <<EOF
GRUB_BACKGROUND="/boot/grub/ciszterci-grub.png"
GRUB_TIMEOUT=5
GRUB_DISTRIBUTOR="CiszterciLinux"
EOF


# CHROOT HOOK
mkdir -p config/hooks/normal

cat > config/hooks/normal/999-full.hook.chroot <<'EOF'
#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections

# repo
cat > /etc/apt/sources.list <<REPO
deb https://ftp.debian.org/debian trixie main contrib non-free non-free-firmware
deb https://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
deb https://ftp.debian.org/debian trixie-updates main contrib non-free non-free-firmware
deb https://ftp.debian.org/debian trixie-backports main contrib non-free non-free-firmware
REPO

apt update
apt -y upgrade

# SSH hardening
apt install -y openssh-server libpam-google-authenticator
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
cat > /etc/ssh/sshd_config <<SSH
Port 22
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication yes
UsePAM yes
ChallengeResponseAuthentication yes
X11Forwarding yes
Subsystem sftp /usr/lib/openssh/sftp-server
SSH

echo "auth required pam_google_authenticator.so" >> /etc/pam.d/sshd
ssh-keygen -A

# # #
# Brave
curl -fsSLo /usr/share/keyrings/brave.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/brave.gpg] https://brave-browser-apt-release.s3.brave.com stable main" > /etc/apt/sources.list.d/brave.list
apt update
apt install -y brave-browser

# # #
# Signal
wget -O- https://updates.signal.org/desktop/apt/keys.asc | gpg --dearmor > /usr/share/keyrings/signal.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/signal.gpg] https://updates.signal.org/desktop/apt xenial main" > /etc/apt/sources.list.d/signal.list
apt update
apt install -y signal-desktop

# # #
# TeamViewer
wget https://download.teamviewer.com/download/linux/teamviewer_amd64.deb
dpkg -i teamviewer_amd64.deb || apt -f install -y
rm teamviewer_amd64.deb

# # #
# AGE crypt
AGE_VER=1.3.1
curl -LO https://github.com/FiloSottile/age/releases/download/v${AGE_VER}/age-v${AGE_VER}-linux-amd64.tar.gz
tar xzf age-v${AGE_VER}-linux-amd64.tar.gz
sudo install -m 0755 age/age age/age-keygen /usr/local/bin/
rm age-v${AGE_VER}-linux-amd64.tar.gz

# # #
# VeraCrypt (Debian 13 = Trixie)
VERACRYPT_URL="https://launchpad.net/veracrypt/trunk/1.26.24/+download/veracrypt-1.26.24-Debian-13-amd64.deb"
VERACRYPT_DEB="veracrypt-1.26.24-Debian-13-amd64.deb"
if wget --tries=3 --timeout=30 -O "$VERACRYPT_DEB" "$VERACRYPT_URL"; then
  dpkg -i "$VERACRYPT_DEB" || apt -f install -y
  echo "%sudo ALL=(ALL) NOPASSWD:/usr/bin/veracrypt" > /etc/sudoers.d/veracrypt
  chmod 440 /etc/sudoers.d/veracrypt
  rm -f "$VERACRYPT_DEB"
else
  echo "FIGYELEM: VeraCrypt letöltése sikertelen, kihagyva."
fi

# # #
# Plymouth téma aktiválása + GRUB háttérkép (telepített rendszerhez)
if [ -f /usr/share/images/desktop-base/desktop-grub.png ]; then
  cp /usr/share/images/desktop-base/desktop-grub.png \
     /usr/share/plymouth/themes/ciszterci/desktop-grub.png
  mkdir -p /boot/grub
  cp /usr/share/images/desktop-base/desktop-grub.png \
     /boot/grub/ciszterci-grub.png
fi
# GRUB menüpont átnevezése Debian -> CiszterciLinux
if [ -f /boot/grub/grub.cfg ]; then
  sed -i 's/Debian GNU\/Linux/CiszterciLinux/g' /boot/grub/grub.cfg
  sed -i 's/Live system/CiszterciLinux Live/g' /boot/grub/grub.cfg
fi

# Régi kernelek eltávolítása, csak a legújabb marad
LATEST=$(ls /boot/vmlinuz-* | sed 's|/boot/vmlinuz-||' | sort -V | tail -n1)
for k in $(dpkg -l 'linux-image-[0-9]*' | awk '/^ii/{print $2}' | grep -v "linux-image-${LATEST}"); do
  apt-get -y purge "$k"
done
apt-get -y autoremove --purge

plymouth-set-default-theme ciszterci
update-initramfs -u -k all

# # #
echo "== FULL BUILD DONE =="
EOF
chmod +x config/hooks/normal/999-full.hook.chroot

echo
echo "================================================="
echo "INTERAKTÍV SHELL fog indulni."
echo "Szerkeszd az /etc/skel mappát."
echo "A képet másold be (Plymouth + GRUB live + GRUB telepített):"
echo "  SRC=/usr/share/images/desktop-base/desktop-grub.png"
echo "  cp \$SRC /usr/share/plymouth/themes/ciszterci/desktop-grub.png"
echo "  mkdir -p /boot/grub"
echo "  cp \$SRC /boot/grub/ciszterci-grub.png"
echo ""
echo "  -- és a live ISO GRUB háttérhez (chroot-on KÍVÜL, host-on):"
echo "    cp /home/majorsza/git/mszabi22/CiszterciLinux/build/configs/usr/share/images/desktop-base/desktop-grub.png /DATA/LIVE/CiszterciLinux/config/bootloaders/grub-pc/splash.png"
echo ""
echo "Kilépés: exit"
echo "================================================="
echo

lb build

echo
DATUM=`date +%y.%m`; mv CiszterciLinux-amd64.hybrid.iso CiszterciLinux-$DATUM-amd64.iso; md5sum CiszterciLinux-$DATUM-amd64.iso > CiszterciLinux-$DATUM-amd64.iso.md5; chown -R majorsza:majorsza CiszterciLinux-*
echo "ISO kész:"
ls -lh *.iso

### javítás: ###
#mount -t proc proc chroot/proc; mount -t sysfs sysfs chroot/sys; mount -o bind /dev chroot/dev; mount -o bind /dev/pts chroot/dev/pts; 

#sudo chroot chroot /bin/bash

#umount chroot/dev/pts; umount chroot/dev; umount chroot/proc; umount chroot/sys
#lb clean --binary
#rm /DATA/LIVE/CiszterciLinux/chroot/etc/debian_chroot*
#lb binary


# ha csak az ISO-t kell:
# rm .build/binary_iso
# lb binary_iso
