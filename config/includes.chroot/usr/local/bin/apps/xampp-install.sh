#!/bin/bash

cd 
wget https://sourceforge.net/projects/xampp/files/XAMPP%20Linux/8.2.12/xampp-linux-x64-8.2.12-0-installer.run
chmod +x xampp-linux-x64-8.2.12-0-installer.run
sudo ./xampp-linux-x64-8.2.12-0-installer.run
rm xampp-linux-x64-8.2.12-0-installer.run

cd /usr/share/icons
sudo wget -O xampp-logo.svg https://www.apachefriends.org/images/xampp-logo-ac950edf.svg

sudo echo "[Desktop Entry]
Name=XAMPP
Exec=sudo /opt/lampp/manager-linux-x64.run
Icon=/usr/share/icons/xampp-logo.svg

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Development;
Enabled=true" > /usr/share/applications/xampp.desktop

echo "%sudo  ALL = (ALL:ALL) NOPASSWD: /opt/lampp/manager-linux-x64.run" >> /etc/sudoers
echo "%diak  ALL = (ALL:ALL) NOPASSWD: /opt/lampp/manager-linux-x64.run" >> /etc/sudoers
echo "%tanar  ALL = (ALL:ALL) NOPASSWD: /opt/lampp/manager-linux-x64.run" >> /etc/sudoers
