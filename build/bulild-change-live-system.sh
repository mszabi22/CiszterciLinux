#!/bin/bash

sed -i 's/Live system/CiszterciLinux Live/g' /DATA/LIVE/CiszterciLinux/binary/boot/grub/grub.cfg
rm /DATA/LIVE/CiszterciLinux/.build/binary_iso
cd /DATA/LIVE/CiszterciLinux/
lb binary_iso

