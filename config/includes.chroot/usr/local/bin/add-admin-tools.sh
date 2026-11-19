#!bin/bash

echo -e "${yellow}Admin Tools telepítése...${white}"
	apt install gprename gparted netdiscover sshuttle grub-customizer remmina remmina-plugin-rdp remmina-plugin-vnc \
	net-tools dnsutils arping zenity chntpw hardinfo acpidump acpidump sysbench dislocker stress s-tui traceroute iputils-ping \
	wireshark tigervnc-viewer tigervnc-tools
	
	echo -e "${yellow}Winbox install...${white}"
	cd /opt
	mkdir winbox
	cd winbox
	wget https://download.mikrotik.com/routeros/winbox/4.0.1/WinBox_Linux.zip
	unzip WinBox_Linux.zip
	ln -s /opt/winbox/WinBox /usr/local/bin/winbox
	ln -s /opt/winbox/assets/img/winbox.png /usr/share/icons/winbox.png
	rm WinBox_Linux.zip
	chmod -R 777 /opt/winbox
	
echo "[Desktop Entry]
Name=Winbox
Exec=/usr/local/bin/winbox
Icon=/usr/share/icons/winbox.png
 
Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Application;Network;
Enabled=true" > /usr/share/applications/winbox.desktop
