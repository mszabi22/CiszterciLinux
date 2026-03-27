#!/bin/bash

sed -i 's/Live system/CiszterciLinux Live/g' /DATA/LIVE/CiszterciLinux/binary/boot/grub/grub.cfg
rm /DATA/LIVE/CiszterciLinux/*.iso
rm /DATA/LIVE/CiszterciLinux/*.md5
rm /DATA/LIVE/CiszterciLinux/.build/binary_iso
cd /DATA/LIVE/CiszterciLinux/
lb binary_iso
DATUM=`date +%y.%m`; mv CiszterciLinux-amd64.hybrid.iso CiszterciLinux-$DATUM-amd64.iso; md5sum CiszterciLinux-$DATUM-amd64.iso > CiszterciLinux-$DATUM-amd64.iso.md5; chown -R majorsza:majorsza CiszterciLinux-*

