#!/bin/bash
# # # Run this second in chroot # # #
green='\e[0;32m'
blue='\e[0;34m'
yellow='\e[0;33m'
white='\e[0;37m'

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
echo -e "${yellow}Scan user passwd...${white}"
sudo smbpasswd -a scan
sudo smbpasswd -e scan

echo -e "${yellow}root passwd...${white}"
echo "root:admin" | chpasswd

#echo -e "${yellow}LIVE user sync...${white}"
#rsync -avz --delete /etc/skel/ /home/live/
#chown -R live:live /home/live/
