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

cp /usr/share/images/desktop-base/desktop-grub.png /usr/share/plymouth/themes/ciszterci/desktop-grub.png
cp /usr/share/images/desktop-base/desktop-grub.png /boot/grub/ciszterci-grub.png
rm /etc/debian_chroot
rm /root/add-programs.sh
history -c

