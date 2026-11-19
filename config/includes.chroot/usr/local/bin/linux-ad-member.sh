
#!/bin/bash

# Root jogosultság ellenőrzése
if [[ $EUID -ne 0 ]]; then
    echo "Ezt a scriptet root jogosultsággal kell futtatni!"
    echo "Használat: sudo bash linux-ad-member.sh"
    exit 1
fi

echo "======================================"
echo " Linux AD tartományba léptetés"
echo "======================================"
echo

# Gépnév bekérése
read -rp "Új gépnév: " GEPNEV

if [[ -z "$GEPNEV" ]]; then
    echo "Hiba: A gépnév nem lehet üres!"
    exit 1
fi

# Tartománynév bekérése
read -rp "Tartomány neve (pl. samba.lan): " DOMAIN

if [[ -z "$DOMAIN" ]]; then
    echo "Hiba: A tartomány neve nem lehet üres!"
    exit 1
fi

# Tartományi felhasználónév bekérése
read -rp "Tartományi felhasználónév: " DOMAIN_USER

if [[ -z "$DOMAIN_USER" ]]; then
    echo "Hiba: A felhasználónév nem lehet üres!"
    exit 1
fi

echo
echo "======================================"
echo " Beállítások ellenőrzése"
echo "======================================"
echo "Gépnév:              $GEPNEV"
echo "Tartomány:           $DOMAIN"
echo "Tartományi user:     $DOMAIN_USER"
echo

read -rp "Folytatod a tartományba léptetést? (i/n): " VALASZ

if [[ "$VALASZ" != "i" && "$VALASZ" != "I" ]]; then
    echo "Művelet megszakítva."
    exit 0
fi

# Hostnév beállítása
echo
echo "[1/6] Gépnév beállítása..."
hostnamectl set-hostname "$GEPNEV" || exit 1

# Tartomány felderítése
echo
echo "[2/6] Tartomány felderítése..."
realm discover "$DOMAIN" || exit 1

# Tartományba léptetés
echo
echo "[3/6] Tartományba léptetés..."
realm join --user="$DOMAIN_USER" "$DOMAIN" || exit 1

# Felhasználó ellenőrzése
echo
echo "[4/6] Tartományi felhasználó ellenőrzése..."
id "$DOMAIN_USER@$DOMAIN"

# PAM home könyvtár automatikus létrehozása
echo
echo "[5/6] PAM beállítása..."
if ! grep -q "pam_mkhomedir.so" /etc/pam.d/common-session; then
    echo "session required pam_mkhomedir.so skel=/etc/skel/ umask=0022" >> /etc/pam.d/common-session
fi

# Sudo jogosultság beállítása
echo
echo "[6/6] Sudo jogosultság beállítása..."
echo "$DOMAIN_USER@$DOMAIN ALL=(ALL) ALL" > /etc/sudoers.d/domain_admins
chmod 440 /etc/sudoers.d/domain_admins

# Sudoers ellenőrzése
visudo -cf /etc/sudoers.d/domain_admins || exit 1

# SSSD konfiguráció
cat > /etc/sssd/sssd.conf <<EOF
[sssd]
domains = $DOMAIN
config_file_version = 2
services = nss, pam

[domain/$DOMAIN]
default_shell = /bin/bash
krb5_store_password_if_offline = True
cache_credentials = True
krb5_realm = ${DOMAIN^^}
realmd_tags = manages-system joined-with-adcli
id_provider = ad
ldap_id_mapping = True
fallback_homedir = /home/%d/%u
ad_domain = $DOMAIN
use_fully_qualified_names = False
access_provider = ad
ad_gpo_access_control = permissive
skel_dir = /etc/skel
EOF

chmod 600 /etc/sssd/sssd.conf

# SSSD újraindítása
systemctl restart sssd

echo
echo "======================================"
echo " Sikeres tartományba léptetés!"
echo "======================================"
echo "Gépnév: $GEPNEV"
echo "Tartomány: $DOMAIN"
echo "Felhasználó: $DOMAIN_USER"
echo
echo "A rendszer újraindítása ajánlott."
