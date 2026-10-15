#!/bin/bash

if [ $# != 1 ] ; then
    echo "Használat: bash linux-ad-member.sh <gepneve>"
    echo "pl.: linux-ad-member.sh linux-dc-1"
    exit 1
fi


hostnamectl set-hostname $1

#echo "Install..."
#apt -y install realmd sssd sssd-tools libnss-sss libpam-sss adcli samba-common-bin oddjob oddjob-mkhomedir packagekit 


realm discover samba.crnl.lan
realm join --user=mszabi samba.crnl.lan
id mszabi@samba.crnl.lan
echo "session required pam_mkhomedir.so skel=/etc/skel/ umask=0022" | sudo tee -a /etc/pam.d/common-session
echo "mszabi@samba.crnl.lan ALL=(ALL) ALL" | sudo tee -a /etc/sudoers.d/domain_admins
echo "[sssd]
domains = samba.crnl.lan
config_file_version = 2
services = nss, pam

[domain/samba.crnl.lan]
default_shell = /bin/bash
krb5_store_password_if_offline = True
cache_credentials = True
krb5_realm = samba.crnl.lan
realmd_tags = manages-system joined-with-adcli 
id_provider = ad
fallback_homedir = /home/%d/%u
ad_domain = samba.crnl.lan
use_fully_qualified_names = False
ldap_id_mapping = True
access_provider = ad
ad_gpo_access_control = permissive
skel_dir = /etc/skel" > /etc/sssd/sssd.conf
systemctl restart sssd 
#realm leave --user=mszabi samba.crnl.lan


