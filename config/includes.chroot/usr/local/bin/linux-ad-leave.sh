#!/bin/bash
set -Eeuo pipefail

DOMAIN="samba.crnl.lan"
DOMAIN_USER="mszabi"
PAM_FILE="/etc/pam.d/common-session"
PAM_LINE="session required pam_mkhomedir.so skel=/etc/skel/ umask=0022"
SUDOERS_FILE="/etc/sudoers.d/domain_admins"
SSSD_CONF="/etc/sssd/sssd.conf"
BACKUP_DIR="/var/backups/kolibri-admin"

log() { echo "[INFO] $*"; }
warn() { echo "[FIGYELEM] $*" >&2; }
die() { echo "[HIBA] $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Ezt a scriptet rendszergazdai jogosultsággal kell futtatni."

command -v realm >/dev/null 2>&1 || die "A realmd (realm parancs) nincs telepítve."

if ! realm list 2>/dev/null | grep -Fqi "$DOMAIN"; then
    log "A gép a(z) $DOMAIN tartományban jelenleg nem szerepel a realm listában."
    log "Ellenőrzöm, hogy maradtak-e a beléptető script által létrehozott helyi beállítások."
else
    log "Kiléptetés a(z) $DOMAIN tartományból..."
    realm leave --user="$DOMAIN_USER" "$DOMAIN" || die "A realm leave sikertelen. A helyi beállításokat nem módosítottam."
fi

install -d -m 700 "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

# A beléptető script pontosan ezt az egy sort fűzte a PAM konfigurációhoz.
if [[ -f "$PAM_FILE" ]] && grep -Fqx "$PAM_LINE" "$PAM_FILE"; then
    cp -a "$PAM_FILE" "$BACKUP_DIR/common-session.$STAMP.bak"
    tmp="$(mktemp)"
    grep -Fvx "$PAM_LINE" "$PAM_FILE" > "$tmp" || true
    cat "$tmp" > "$PAM_FILE"
    rm -f "$tmp"
    log "A tartománybelépéskor hozzáadott PAM-sort eltávolítottam."
fi

# Ezt a sudoers fájlt a beléptető script hozta létre.
if [[ -f "$SUDOERS_FILE" ]]; then
    cp -a "$SUDOERS_FILE" "$BACKUP_DIR/domain_admins.$STAMP.bak"
    rm -f "$SUDOERS_FILE"
    log "A tartományi rendszergazdai sudo-szabályt eltávolítottam."
fi

# A beléptető script teljes egészében ezt az egy tartományt írta az sssd.conf-ba.
# Csak akkor archiváljuk és távolítjuk el, ha valóban ezt a konfigurációt tartalmazza.
if [[ -f "$SSSD_CONF" ]] && grep -Eiq '^[[:space:]]*domains[[:space:]]*=[[:space:]]*samba\.crnl\.lan[[:space:]]*$' "$SSSD_CONF" \
   && grep -Eiq '^[[:space:]]*ad_domain[[:space:]]*=[[:space:]]*samba\.crnl\.lan[[:space:]]*$' "$SSSD_CONF"; then
    cp -a "$SSSD_CONF" "$BACKUP_DIR/sssd.conf.$STAMP.bak"
    rm -f "$SSSD_CONF"
    log "A Kolibri beléptető script által létrehozott SSSD-konfigurációt archiváltam és eltávolítottam."
else
    warn "Az SSSD-konfiguráció nem egyezik pontosan a beléptető script által létrehozott tartományi konfigurációval; érintetlenül hagytam."
fi

if systemctl is-enabled sssd >/dev/null 2>&1 || systemctl is-active sssd >/dev/null 2>&1; then
    systemctl disable --now sssd || warn "Az SSSD leállítása/letiltása nem sikerült."
fi

log "A tartományból való kilépés és a helyi takarítás befejeződött."
log "Biztonsági mentések helye: $BACKUP_DIR"
warn "A gépnevet nem állítottam vissza: a beléptető script nem mentette el a korábbi gépnevet."
warn "Ha a felhasználó még be van jelentkezve tartományi fiókkal, jelentkezzen ki, majd indítsa újra a gépet."
