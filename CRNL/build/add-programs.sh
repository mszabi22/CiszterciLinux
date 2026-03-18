#!/bin/bash
# # # Run this second in chroot # # #
green='\e[0;32m'
blue='\e[0;34m'
yellow='\e[0;33m'
white='\e[0;37m'
########################################################################
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
########################################################################
echo -e "${yellow}LocalSend install...${white}"
wget https://github.com/localsend/localsend/releases/download/v1.17.0/LocalSend-1.17.0-linux-x86-64.deb
dpkg -i LocalSend-1.17.0-linux-x86-64.deb || apt-get -f install -y
rm LocalSend-1.17.0-linux-x86-64.deb        
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

########################################################################
# # #
# Samba share
mkdir -p /home/scan
chmod 2775 /home/scan
groupadd -f smbshare
chgrp smbshare /home/scan
chgrp -R smbshare /home/scan
chmod 2775 /home/scan
useradd -M -s /usr/sbin/nologin -u 1100 scan
usermod -aG smbshare scan
cat >> /etc/samba/smb.conf <<SAMBA

[scan]
   path = /home/scan
   writable = yes
   guest ok = yes
   force create mode = 775
   force directory mode = 775
SAMBA

echo -e "${yellow}Scan user passwd...${white}"
sudo smbpasswd -a scan
sudo smbpasswd -e scan

echo -e "${yellow}root passwd...${white}"
echo "root:admin" | chpasswd

#echo -e "${yellow}LIVE user sync...${white}"
#rsync -avz --delete /etc/skel/ /home/live/
#chown -R live:live /home/live/

rm /etc/debian_chroot
