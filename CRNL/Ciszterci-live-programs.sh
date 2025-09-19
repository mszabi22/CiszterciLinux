#!/bin/bash
# # # Run this second in chroot # # #
green='\e[0;32m'
blue='\e[0;34m'
yellow='\e[0;33m'
white='\e[0;37m'

# # #
echo -e "${yellow}rc-local setting...${white}"
echo '[Unit]
Description=/etc/rc.local
ConditionPathExists=/etc/rc.local
 
[Service]
Type=forking
ExecStart=/etc/rc.local start
TimeoutSec=0
StandardOutput=tty
RemainAfterExit=yes
SysVStartPriority=99

[Install]
WantedBy=multi-user.target' > /etc/systemd/system/rc-local.service

echo '#!/bin/sh -e
exit 0
' > /etc/rc.local

chmod +x /etc/rc.local
systemctl enable rc-local

echo -e "${yellow}Repository setting...${white}"
echo "deb https://ftp.debian.org/debian/ trixie contrib main non-free non-free-firmware contrib
deb https://ftp.debian.org/debian/ trixie-updates contrib main non-free non-free-firmware contrib
deb https://ftp.debian.org/debian/ trixie-proposed-updates contrib main non-free non-free-firmware contrib
deb https://ftp.debian.org/debian/ trixie-backports contrib main non-free non-free-firmware contrib
deb https://security.debian.org/debian-security/ trixie-security contrib main non-free non-free-firmware contrib" > /etc/apt/sources.list
apt update
apt upgrade -y

echo -e "${yellow}Apps install...${white}"
apt install -y mc sudo ssh cups printer-driver-cups-pdf gvfs-fuse gvfs-backends apt-transport-https rsync curl wget \
    firmware-iwlwifi firmware-atheros firmware-brcm80211 blueman ttf-mscorefonts-installer vlc thunderbird thunderbird-l10n-hu \
    gimp simple-scan gnupg gnupg2 gnupg1 eog zstd imagemagick menulibre mugshot keepassxc geany ntpsec zenity\
    libpam-google-authenticator gnome-system-tools wireguard wireguard-tools libreoffice-l10n-hu gnome-online-accounts \
    audacious molly-guard kleopatra clamtk mpv geogebra krita krita-l10n nfs-common veyon-service 

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
cp /etc/pam.d/sshd /root/pam.d_sshd.bak
echo "
# two-factor authentication via Google Authenticator
auth   required   pam_google_authenticator.so" >> /etc/pam.d/sshd
/etc/init.d/ssh restart

echo -e "${yellow}Brave install...${white}"    
apt install curl
curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main"| tee /etc/apt/sources.list.d/brave-browser-release.list
apt update
apt install brave-browser -y
echo "[Desktop Entry]
Version=1.0
Name=Brave Webböngésző
Exec=/usr/bin/brave-browser-stable %U
StartupNotify=true
Terminal=false
Icon=brave-browser
Type=Application
Categories=Network;WebBrowser;
MimeType=application/pdf;application/rdf+xml;application/rss+xml;application/xhtml+xml;application/xhtml_xml;application/xml;image/gif;image/jpeg;image/png;image/webp;text/html;text/xml;x-scheme-handler/http;x-scheme-handler/https;x-scheme-handler/ipfs;x-scheme-handler/ipns;
Actions=new-window;new-private-window;

[Desktop Action new-window]
Name=Új ablak
Exec=/usr/bin/brave-browser-stable

[Desktop Action new-private-window]
Name=Inkognitó mód
Exec=/usr/bin/brave-browser-stable --incognito
" > /usr/share/applications/brave-browser.desktop

echo -e "${yellow}Signal install...${white}"
cd
wget -O- https://updates.signal.org/desktop/apt/keys.asc | gpg --dearmor > signal-desktop-keyring.gpg
cat signal-desktop-keyring.gpg | tee /usr/share/keyrings/signal-desktop-keyring.gpg > /dev/null
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/signal-desktop-keyring.gpg] https://updates.signal.org/desktop/apt xenial main' | tee /etc/apt/sources.list.d/signal-xenial.list
apt update && sudo apt install signal-desktop

echo -e "${yellow}TeamViewer install...${white}"
cd
wget https://download.teamviewer.com/download/linux/teamviewer_amd64.deb
dpkg -i teamviewer_amd64.deb
apt-get -f install -y
rm teamviewer_amd64.deb

########################################################################
echo -e "${yellow}AEScrypt install...${white}"
wget https://www.aescrypt.com/download/v4/linux/aescrypt_gui-4.3.1-Linux-x86_64.deb
dpkg -i aescrypt_gui-*.deb
########################################################################
echo -e "${yellow}VeraCrypt install...${white}"
cd
wget https://launchpad.net/veracrypt/trunk/1.26.24/+download/veracrypt-1.26.24-Debian-12-amd64.deb
dpkg -i veracrypt-*.deb
apt-get -f install -y
rm veracrypt-*.deb
echo "[Desktop Entry]
Type=Application
Name=VeraCrypt
GenericName=VeraCrypt volume manager
Comment=Create and mount VeraCrypt encrypted volumes
Icon=veracrypt
Exec=/usr/bin/veracrypt %f
Categories=Office;
Keywords=encryption,filesystem
Terminal=false
MimeType=application/x-veracrypt-volume;application/x-truecrypt-volume;" > /usr/share/applications/veracrypt.desktop
echo "%sudo  ALL = (ALL:ALL) NOPASSWD: /usr/bin/veracrypt" >> /etc/sudoers
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

echo -e "${yellow}Samba Share...${white}"
apt install samba smbclient cifs-utils
mkdir /home/scan
chmod -R 777 /home/scan
echo "[scan]
   comment = Scan Folder
   path = /home/scan
   writable = yes
   guest ok = yes
   guest only = yes
   force create mode = 775
   force directory mode = 775" >> /etc/samba/smb.conf
sudo groupadd smbshare
sudo chgrp -R smbshare /home/scan
sudo chmod 2775 /home/scan
sudo useradd -M -s /sbin/nologin scan
sudo usermod -aG smbshare scan

echo -e "${yellow}Scan user passwd...${white}"
sudo smbpasswd -a scan
sudo smbpasswd -e scan

echo -e "${yellow}Create user...${white}"
adduser user

echo -e "${yellow}root passwd...${white}"
passwd

echo -e "${green}DONE.${white}"
