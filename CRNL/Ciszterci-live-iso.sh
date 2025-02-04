#!/bin/bash
DATUM=`date +%Y.%m.%d`
mv CiszterciLinux-amd64.hybrid.iso CiszterciLinux-$DATUM-amd64.iso
md5sum CiszterciLinux-$DATUM-amd64.iso > CiszterciLinux-$DATUM-amd64.iso.md5
chown -R majorsza:majorsza CiszterciLinux-*
