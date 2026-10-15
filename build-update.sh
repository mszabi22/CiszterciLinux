#/bin/bash

### javítás: ###
mount -t proc proc chroot/proc; mount -t sysfs sysfs chroot/sys; mount -o bind /dev chroot/dev; mount -o bind /dev/pts chroot/dev/pts; 

sudo chroot chroot /bin/bash

umount chroot/dev/pts; umount chroot/dev; umount chroot/proc; umount chroot/sys
lb clean --binary
rm chroot/etc/debian_chroot*
lb binary

sed -i 's/Live system/Ciszterci Linux Live/g' binary/boot/grub/grub.cfg; rm *.iso; rm *.md5; rm .build/binary_iso
lb binary_iso
DATUM=`date +%y.%m`; mv ciszterci-amd64.hybrid.iso CiszterciLinux-$DATUM-amd64.iso; md5sum CiszterciLinux-$DATUM-amd64.iso > CiszterciLinux-$DATUM-amd64.iso.md5; chown -R majorsza:majorsza CiszterciLinux-*
