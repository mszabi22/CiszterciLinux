#!/bin/bash
# # # Run this second in chroot # # #
green='\e[0;32m'
blue='\e[0;34m'
yellow='\e[0;33m'
white='\e[0;37m'

echo -e "${yellow}Apps install...${white}"
apt install -y mc sudo ssh cups printer-driver-cups-pdf gvfs-fuse gvfs-backends apt-transport-https rsync curl wget \
    firmware-iwlwifi firmware-atheros firmware-brcm80211 blueman ttf-mscorefonts-installer vlc thunderbird thunderbird-l10n-hu \
    gimp simple-scan gnupg gnupg2 gnupg1 eog zstd imagemagick menulibre mugshot keepassxc geany ntpsec zenity\
    libpam-google-authenticator gnome-system-tools wireguard wireguard-tools libreoffice-l10n-hu gnome-online-accounts \
    audacious molly-guard kleopatra clamtk mpv geogebra krita krita-l10n nfs-common veyon-service bash-completion screen birdtray

echo -e "${yellow}SSH setting...${white}"
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
echo "Include /etc/ssh/sshd_config.d/*.conf
Port 22
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile	.ssh/authorized_keys .ssh/authorized_keys2
PasswordAuthentication no

KbdInteractiveAuthentication yes
UsePAM yes
ChallengeResponseAuthentication yes

X11Forwarding yes
PrintMotd no
AcceptEnv LANG LC_*
Subsystem	sftp	/usr/lib/openssh/sftp-server" > /etc/ssh/sshd_config
sudo apt install libpam-google-authenticator
/etc/init.d/ssh restart
########################################################################
echo -e "${yellow}Viber install...${white}"
cd /usr/local/bin
wget -O viber https://download.cdn.viber.com/desktop/Linux/viber.AppImage
chmod +x viber

cd /usr/share/icons
wget -O viber-logo.png https://www.freepnglogos.com/uploads/viber-png/viber-top-way-video-call-faster-full-tronzi-6.png

echo "[Desktop Entry]
Name=Viber
Exec=/usr/local/bin/viber
Icon=/usr/share/icons/viber-logo.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Network;
Enabled=true" > /usr/share/applications/viber.desktop
########################################################################
echo -e "${yellow}Standard Notes install...${white}"
cd /usr/share/icons
wget https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/standard-notes.png
cd /usr/local/bin
wget -O standard-notes https://github.com/standardnotes/app/releases/download/%40standardnotes/desktop%403.201.18/standard-notes-3.201.18-linux-x86_64.AppImage
chmod a+x standard-notes
echo "[Desktop Entry]
Name=Standard Notes
Exec=/usr/local/bin/standard-notes
Icon=/usr/share/icons/standard-notes.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Office;
Enabled=true" > /usr/share/applications/standard-notes.desktop
########################################################################
echo -e "${yellow}AEScrypt install...${white}"
cd
wget https://www.aescrypt.com/download/v4/linux/aescrypt_gui-4.5.0-Linux-x86_64.deb
dpkg -i aescrypt_gui-*.deb
rm aescrypt_gui-*.deb
########################################################################
echo -e "${yellow}XAMPP install...${white}"
wget -O xampp.run https://sourceforge.net/projects/xampp/files/XAMPP%20Linux/8.2.12/xampp-linux-x64-8.2.12-0-installer.run/download
chmod +x xampp.run
./xampp.run
rm -rf xampp.run
chmod +x /opt/lampp/manager-linux-x64.run

cd /usr/share/icons
wget -O xampp-logo.png https://cdn.freelogovectors.net/wp-content/uploads/2021/02/xampp-logo-freelogovectors.net_.png
echo "[Desktop Entry]
Name=XAMPP
Exec=sudo /opt/lampp/manager-linux-x64.run
Icon=/usr/share/icons/xampp-logo.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Network;
Enabled=true" > /usr/share/applications/xampp.desktop 	
echo "%sudo ALL = (ALL:ALL) NOPASSWD: /opt/lampp/manager-linux-x64.run" >> /etc/sudoers
echo "%diákok ALL = (ALL:ALL) NOPASSWD: /opt/lampp/manager-linux-x64.run" >> /etc/sudoers
echo "%tanárok ALL = (ALL:ALL) NOPASSWD: /opt/lampp/manager-linux-x64.run" >> /etc/sudoers

sudo groupadd smbshare
sudo chgrp -R smbshare /home/scan
sudo chmod 2775 /home/scan
sudo useradd -M -s /sbin/nologin scan
sudo usermod -aG smbshare scan
########################################################################
echo -e "${yellow}Scan user passwd...${white}"
sudo smbpasswd -a scan
sudo smbpasswd -e scan


echo -e "${yellow}root passwd...${white}"
echo "root:admin" | chpasswd

echo -e "${green}Background??${white}"
echo -e "${green}skel??${white}"
