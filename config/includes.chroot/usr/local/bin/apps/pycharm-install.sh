#!/bin/bash

cd /opt
sudo wget -O pycharm.tar.gz "https://download.jetbrains.com/python/pycharm-2025.1.tar.gz"
sudo tar -xzf pycharm.tar.gz -C /opt
sudo ln -s /opt/pycharm-2025.1/bin/pycharm.sh /usr/local/bin/pycharm

cd /usr/share/icons
sudo wget -O pycharm-logo.png https://www.liblogo.com/img-logo/py8871icf9-pycharm-logo-intellij-pycharm-alt-macos-icon-in-macos-big-sur.png

sudo echo "[Desktop Entry]
Name=pycharm
Exec=/usr/local/bin/pycharm
Icon=/usr/share/icons/pycharm-logo.png

Encoding=UTF-8
ExecutionMode=normal
Type=Application
Categories=Development;
Enabled=true" > /usr/share/applications/pycharm.desktop
