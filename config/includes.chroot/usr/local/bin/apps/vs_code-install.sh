#!/bin/bash

cd
wget -O vscode_amd64.deb "https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64"
sudo dpkg -i vscode_amd64.deb
rm vscode_amd64.deb

