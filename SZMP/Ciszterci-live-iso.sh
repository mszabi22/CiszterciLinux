#!/bin/bash
ls -1
DATUM=`date +%Y.%m.%d`
mv SZMP-Linux-amd64.hybrid.iso SZMP-Linux-$DATUM-amd64.iso
md5sum SZMP-Linux-$DATUM-amd64.iso > SZMP-Linux-$DATUM-amd64.iso.md5
chown -R majorsza:majorsza SZMP-Linux-*
