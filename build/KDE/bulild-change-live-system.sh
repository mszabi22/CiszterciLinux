#!/bin/bash

sed -i 's/Live system/CiszterciLinux Live (KDE)/g' /DATA/LIVE/CiszterciLinux-KDE/binary/boot/grub/grub.cfg
rm /DATA/LIVE/CiszterciLinux-KDE/*.iso
rm /DATA/LIVE/CiszterciLinux-KDE/*.md5
rm /DATA/LIVE/CiszterciLinux-KDE/.build/binary_iso
cd /DATA/LIVE/CiszterciLinux-KDE
lb binary_iso
DATUM=`date +%y.%m`; mv CiszterciLinux-KDE-amd64.hybrid.iso CiszterciLinux-KDE-$DATUM-amd64.iso; md5sum CiszterciLinux-KDE-$DATUM-amd64.iso > CiszterciLinux-KDE-$DATUM-amd64.iso.md5; chown -R majorsza:majorsza CiszterciLinux-KDE-*

