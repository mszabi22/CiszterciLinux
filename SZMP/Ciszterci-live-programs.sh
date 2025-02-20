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

echo -e "${yellow}Timezone setting...${white}"
apt install chrony -y
timedatectl set-timezone Europe/Budapest
timedatectl set-ntp on

echo -e "${yellow}Repository setting...${white}"
echo "deb https://ftp.debian.org/debian/ bookworm contrib main non-free non-free-firmware contrib
deb https://ftp.debian.org/debian/ bookworm-updates contrib main non-free non-free-firmware contrib
deb https://ftp.debian.org/debian/ bookworm-proposed-updates contrib main non-free non-free-firmware contrib
deb https://ftp.debian.org/debian/ bookworm-backports contrib main non-free non-free-firmware contrib
deb https://security.debian.org/debian-security/ bookworm-security contrib main non-free non-free-firmware contrib" > /etc/apt/sources.list
apt update
apt upgrade -y

echo -e "${yellow}Apps install...${white}"
apt install -y mc sudo ssh cups printer-driver-cups-pdf gvfs-fuse gvfs-backends apt-transport-https rsync curl wget \
    firmware-iwlwifi firmware-atheros firmware-brcm80211 blueman ttf-mscorefonts-installer vlc thunderbird thunderbird-l10n-hu \
    gimp simple-scan gnupg gnupg2 gnupg1 eog zstd imagemagick menulibre mugshot keepassxc geany ntpsec zenity\
    libpam-google-authenticator gnome-system-tools wireguard wireguard-tools libreoffice-l10n-hu gnome-online-accounts \
    audacious molly-guard kleopatra clamtk mpv smplayer ntpdate firewalld firewall-config firewall-applet

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

echo -e "${yellow}Session Messenger install...${white}"
cd /usr/local/bin
wget -O session-desktop https://getsession.org/linux
chmod +x session-desktop 

cd /usr/share/icons
wget https://getsession.org/apple-touch-icon.png -O session-logo.png

echo "[Desktop Entry]
Name=Session Messenger
Exec=/usr/local/bin/session-desktop
Icon=/usr/share/icons/session-logo.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Network;
Enabled=true" > /usr/share/applications/session-desktop.desktop  

echo -e "${yellow}Viber install...${white}"
cd /usr/local/bin
wget https://download.cdn.viber.com/desktop/Linux/viber.AppImage
mv viber.AppImage viber
chmod +x viber
cd /usr/share/icons
wget -O viber-logo.png https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Fzh.wizcase.com%2Fwp-content%2Fuploads%2F2020%2F02%2FVIBER-LOGO-1.png&f=1&nofb=1&ipt=95f0c86d8e9533c00e85b8621237d03bae171b5e9a253152513eb3bb4fa223e1&ipo=images
echo "[Desktop Entry]
Name=Viber
Exec=/usr/local/bin/viber
Icon=/usr/share/icons/viber-logo.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Network;
Enabled=true" > /usr/share/applications/viber.desktop  

echo -e "${yellow}VeraCrypt install...${white}"
cd
wget https://launchpad.net/veracrypt/trunk/1.26.20/+download/veracrypt-1.26.20-Debian-12-amd64.deb
dpkg -i veracrypt-1.26.20-Debian-12-amd64.deb
rm veracrypt-1.26.20-Debian-12-amd64.deb
apt-get -f install -y
echo "[Desktop Entry]
Type=Application
Name=VeraCrypt
GenericName=VeraCrypt volume manager
Comment=Create and mount VeraCrypt encrypted volumes
Icon=veracrypt
Exec=sudo /usr/bin/veracrypt %f
Categories=Office;
Keywords=encryption,filesystem
Terminal=false
MimeType=application/x-veracrypt-volume;application/x-truecrypt-volume;" > /usr/share/applications/veracrypt.desktop
"%sudo  ALL = (ALL:ALL) NOPASSWD: /usr/bin/veracrypt" >> /etc/sudoers

echo -e "${yellow}RustDesk install...${white}"
cd /usr/local/bin
wget https://github.com/rustdesk/rustdesk/releases/download/1.3.1/rustdesk-1.3.1-x86_64.AppImage
mv rustdesk-1.3.1-x86_64.AppImage rustdesk
chmod +x rustdesk
cd /usr/share/icons
wget -q -O rustdesk-logo.png https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Fwww.myqnap.org%2Fwp-content%2Fuploads%2Frustdesk-logo.png&f=1&nofb=1&ipt=31c1fd688cfe78d356d7f6339be7858c1972b3270cb2c2ebdbbdeb72fccedc0f&ipo=images
	
echo "[Desktop Entry]
Name=RustDesk
Exec=/usr/local/bin/rustdesk
Icon=/usr/share/icons/rustdesk-logo.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Network;
Enabled=true" > /usr/share/applications/rustdesk.desktop 	


echo -e "${yellow}TeamViewer install...${white}"
cd
wget https://download.teamviewer.com/download/linux/teamviewer_amd64.deb
dpkg -i teamviewer_amd64.deb
apt-get -f install -y
rm teamviewer_amd64.deb

adduser user

echo -e "${green}DONE.${white}"
