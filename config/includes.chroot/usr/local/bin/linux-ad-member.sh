#!/bin/bash
# =====================================================================
#  Linux gép tartományba léptetése (Samba AD / Active Directory)
#  Debian 12/13, Ubuntu – realmd + adcli + SSSD
#
#  Használat:  sudo bash linux-ad-member.sh
# =====================================================================

set -o pipefail

CONF="/etc/sssd/sssd.conf"

info() { echo -e "\n\e[1;34m==> $*\e[0m"; }
ok()   { echo -e "\e[1;32m[OK]\e[0m $*"; }
warn() { echo -e "\e[1;33m[!]\e[0m $*"; }
die()  { echo -e "\e[1;31m[HIBA]\e[0m $*" >&2; exit 1; }

# ---------------------------------------------------------------------
# 0. Előfeltételek
# ---------------------------------------------------------------------
[[ $EUID -eq 0 ]] || die "Root jogosultság kell. Használat: sudo bash $0"
command -v apt-get >/dev/null 2>&1 || die "Ez a script csak Debian/Ubuntu alapú rendszeren fut."

echo "======================================"
echo " Linux AD tartományba léptetés"
echo "======================================"
echo

# ---------------------------------------------------------------------
# 1. Adatok bekérése
# ---------------------------------------------------------------------
read -rp "Új gépnév (pl. pc-cl-01): " GEPNEV
GEPNEV="${GEPNEV,,}"
[[ -n "$GEPNEV" ]] || die "A gépnév nem lehet üres!"
[[ "$GEPNEV" =~ ^[a-z0-9]([a-z0-9-]{0,13}[a-z0-9])?$ ]] \
    || die "Érvénytelen gépnév (max. 15 karakter, csak a-z, 0-9 és kötőjel, nem kezdődhet/végződhet kötőjellel)."

read -rp "Tartomány neve (pl. samba.lan): " DOMAIN
DOMAIN="${DOMAIN,,}"
[[ -n "$DOMAIN" ]] || die "A tartomány neve nem lehet üres!"
REALM="${DOMAIN^^}"

read -rp "Tartományi felhasználónév (jogosult a gép felvételére): " DOMAIN_USER
DOMAIN_USER="${DOMAIN_USER%%@*}"     # ha véletlenül user@domain-t írnál
[[ -n "$DOMAIN_USER" ]] || die "A felhasználónév nem lehet üres!"

FQDN="${GEPNEV}.${DOMAIN}"

echo
echo "======================================"
echo " Beállítások ellenőrzése"
echo "======================================"
echo "Gépnév:           $GEPNEV"
echo "Teljes név (FQDN): $FQDN"
echo "Tartomány:        $DOMAIN"
echo "Kerberos realm:   $REALM"
echo "Tartományi user:  $DOMAIN_USER"
echo
read -rp "Folytatod a tartományba léptetést? (i/n): " VALASZ
[[ "$VALASZ" == "i" || "$VALASZ" == "I" ]] || { echo "Művelet megszakítva."; exit 0; }

# ---------------------------------------------------------------------
# 2. Csomagok telepítése
# ---------------------------------------------------------------------
info "[1/9] Szükséges csomagok telepítése..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || warn "Az apt update hibát jelzett, megpróbálom tovább."
apt-get install -y \
    realmd sssd sssd-ad sssd-tools libnss-sss libpam-sss \
    adcli samba-common-bin krb5-user libpam-modules sudo \
    || die "A csomagok telepítése nem sikerült."
ok "Csomagok rendben."

# ---------------------------------------------------------------------
# 3. Gépnév, /etc/hosts, idő
# ---------------------------------------------------------------------
info "[2/9] Gépnév és /etc/hosts beállítása..."
hostnamectl set-hostname "$FQDN" || die "A gépnév beállítása nem sikerült."
sed -i -E '/^127\.0\.1\.1[[:space:]]/d' /etc/hosts
echo "127.0.1.1 $FQDN $GEPNEV" >> /etc/hosts
ok "Gépnév: $(hostname -f 2>/dev/null || hostname)"

timedatectl set-ntp true >/dev/null 2>&1 || true
if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" != "yes" ]]; then
    warn "Az óra nincs NTP-vel szinkronban. A Kerberos max. 5 perc eltérést tűr a DC-hez képest!"
fi

# ---------------------------------------------------------------------
# 4. DNS ellenőrzés és Kerberos alapbeállítás
# ---------------------------------------------------------------------
info "[3/9] DNS ellenőrzése és Kerberos beállítása..."
if ! getent hosts "$DOMAIN" >/dev/null 2>&1; then
    die "A(z) $DOMAIN nem oldható fel. A gép DNS-szervere a Samba DC legyen (resolvectl status / /etc/resolv.conf)."
fi
ok "A(z) $DOMAIN feloldható."

[[ -f /etc/krb5.conf ]] && cp -n /etc/krb5.conf /etc/krb5.conf.bak-ad
cat > /etc/krb5.conf <<EOF
[libdefaults]
    default_realm = $REALM
    dns_lookup_realm = false
    dns_lookup_kdc = true
    rdns = false
    forwardable = true
    ticket_lifetime = 24h
    renew_lifetime = 7d
EOF
ok "/etc/krb5.conf kész (eredeti: /etc/krb5.conf.bak-ad)."

# ---------------------------------------------------------------------
# 5. Tartomány felderítése és belépés
# ---------------------------------------------------------------------
info "[4/9] Tartomány felderítése..."
realm discover "$REALM" || die "A tartomány nem található. Ellenőrizd a DNS-t (SRV rekordok: _ldap._tcp.$DOMAIN)."

if realm list 2>/dev/null | grep -q "configured"; then
    warn "A gép már tagja egy tartománynak:"
    realm list
    read -rp "Kilépjek belőle és újralépjek tiszta lappal? (i/n): " LEAVE
    if [[ "$LEAVE" == "i" || "$LEAVE" == "I" ]]; then
        realm leave || warn "A realm leave hibát jelzett, folytatom."
    else
        die "Megszakítva: előbb lépj ki a tartományból (realm leave)."
    fi
fi

info "[5/9] Tartományba léptetés (a(z) $DOMAIN_USER jelszavát kéri)..."
realm join --verbose \
    --membership-software=adcli \
    --client-software=sssd \
    --user="$DOMAIN_USER" \
    "$REALM" \
    || die "A tartományba léptetés nem sikerült (jelszó, jogosultság, DNS vagy idő hiba lehet)."
ok "A gép bekerült a tartományba."

realm permit --all || warn "A realm permit nem sikerült."

# ---------------------------------------------------------------------
# 6. SSSD finomhangolás (a realmd által generált konfig módosítása)
# ---------------------------------------------------------------------
info "[6/9] SSSD beállítása..."
[[ -f "$CONF" ]] || die "Nincs $CONF – a join nem hozta létre."
SSSD_DOM="$(grep -m1 -oP '^\[domain/\K[^\]]+' "$CONF")"
[[ -n "$SSSD_DOM" ]] || die "Nem találom a domain szekciót a $CONF fájlban."

set_sssd_opt() {   # set_sssd_opt kulcs érték
    local key="$1" val="$2" esc
    esc="$(printf '%s' "$SSSD_DOM" | sed 's/[.[\*^$/]/\\&/g')"
    sed -i -E "/^\[domain\/${esc}\]/,/^\[/{/^[[:space:]]*${key}[[:space:]]*=/d}" "$CONF"
    sed -i "/^\[domain\/${esc}\]/a ${key} = ${val}" "$CONF"
}

set_sssd_opt use_fully_qualified_names False
set_sssd_opt fallback_homedir "/home/%d/%u"
set_sssd_opt default_shell /bin/bash
set_sssd_opt ad_gpo_access_control permissive
set_sssd_opt krb5_ccname_template "FILE:%d/krb5cc_%U_XXXXXX"
set_sssd_opt ad_hostname "$FQDN"
set_sssd_opt cache_credentials True
set_sssd_opt krb5_store_password_if_offline True

chown root:root "$CONF"
chmod 600 "$CONF"
ok "$CONF módosítva (domain: $SSSD_DOM)."

# ---------------------------------------------------------------------
# 7. NSS + PAM (home könyvtár automatikus létrehozása)
# ---------------------------------------------------------------------
info "[7/9] NSS és PAM beállítása..."

# winbind eltávolítása az nsswitch passwd/group soraiból (SSSD mellett nem kell)
sed -i -E '/^(passwd|group):/ s/[[:space:]]+winbind//g' /etc/nsswitch.conf
for db in passwd group; do
    grep -Eq "^${db}:.*\bsss\b" /etc/nsswitch.conf || sed -i -E "s/^(${db}:.*)$/\1 sss/" /etc/nsswitch.conf
done
grep -Eq '^shadow:.*\bsss\b' /etc/nsswitch.conf || sed -i -E 's/^(shadow:.*)$/\1 sss/' /etc/nsswitch.conf

# mkhomedir PAM-profil (pam-auth-update-tel, nem kézi fájlpiszkálással)
cat > /usr/share/pam-configs/mkhomedir <<'EOF'
Name: Create home directory on login
Default: yes
Priority: 900
Session-Type: Additional
Session:
	required	pam_mkhomedir.so umask=0077 skel=/etc/skel
EOF
# korábbi kézi sor eltávolítása, hogy ne duplázódjon
sed -i '/pam_mkhomedir\.so/d' /etc/pam.d/common-session
pam-auth-update --enable sss mkhomedir --force >/dev/null 2>&1 \
    || warn "A pam-auth-update hibát jelzett – ellenőrizd: grep -E 'sss|mkhomedir' /etc/pam.d/common-*"
ok "NSS és PAM kész."

# ---------------------------------------------------------------------
# 8. Sudo jogosultság
# ---------------------------------------------------------------------
info "[8/9] Sudo jogosultság beállítása..."
rm -f /etc/sudoers.d/domain_admins
TMP_SUDO="$(mktemp)"
cat > "$TMP_SUDO" <<EOF
%domain\ admins ALL=(ALL:ALL) ALL
%Domain\ Admins ALL=(ALL:ALL) ALL
${DOMAIN_USER} ALL=(ALL:ALL) ALL
EOF
if visudo -cf "$TMP_SUDO" >/dev/null; then
    install -m 440 -o root -g root "$TMP_SUDO" /etc/sudoers.d/ad-admins
    ok "Sudo: Domain Admins csoport és $DOMAIN_USER."
else
    warn "A sudoers szintaxis hibás, nem telepítettem."
fi
rm -f "$TMP_SUDO"

# ---------------------------------------------------------------------
# 9. SSSD újraindítás tiszta cache-sel és ellenőrzés
# ---------------------------------------------------------------------
info "[9/9] SSSD újraindítása és ellenőrzés..."
systemctl stop sssd
rm -f /var/lib/sss/db/* /var/lib/sss/mc/* 2>/dev/null
systemctl enable sssd >/dev/null 2>&1
systemctl start sssd || die "Az SSSD nem indult el: journalctl -u sssd -n 50"
sleep 3

echo
echo "--- id $DOMAIN_USER ---"
id "$DOMAIN_USER" || warn "A felhasználó nem található!"
echo
echo "--- sssctl domain-status $SSSD_DOM ---"
sssctl domain-status "$SSSD_DOM" 2>&1 | head -n 12

echo
echo "======================================"
echo " Bejelentkezési (jelszavas) teszt"
echo "======================================"
echo "Most a(z) $DOMAIN_USER jelszavát kéri a PAM-on keresztül."
sssctl user-checks -a auth -s sshd "$DOMAIN_USER"
echo
read -rp "Sikeres volt a hitelesítés? (i/n): " AUTH_OK

if [[ "$AUTH_OK" != "i" && "$AUTH_OK" != "I" ]]; then
    warn "Hibakeresési naplózás bekapcsolása..."
    set_sssd_opt debug_level 7
    systemctl restart sssd
    sleep 3
    : > /var/log/sssd/krb5_child.log 2>/dev/null
    echo "Újabb próba (írd be újra a jelszót):"
    sssctl user-checks -a auth -s sshd "$DOMAIN_USER"
    echo
    echo "--- /var/log/sssd/krb5_child.log (utolsó 40 sor) ---"
    tail -n 40 /var/log/sssd/krb5_child.log 2>/dev/null
    echo
    die "A hitelesítés nem működik. Küldd el a fenti krb5_child.log kimenetet. A debug_level = 7 bent maradt a $CONF fájlban, később vedd ki."
fi

echo
echo "======================================"
echo " Sikeres tartományba léptetés!"
echo "======================================"
echo "Gépnév:      $FQDN"
echo "Tartomány:   $DOMAIN ($REALM)"
echo "Home:        /home/<felhasználó> (első belépéskor jön létre)"
echo "Bejelentkezés: felhasználónév a tartomány nélkül (pl. $DOMAIN_USER)"
echo
echo "A rendszer újraindítása ajánlott: reboot"
