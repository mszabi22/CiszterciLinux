#!/bin/bash
# cleanup_live_user.sh
# Lezárja a 'live' felhasználó folyamatait, törli a felhasználót és az /etc/debian_chroot fájlt

set -e

TARGET_USER="live"

# Root jogosultság ellenőrzése
if [[ "$EUID" -ne 0 ]]; then
    echo "Ez a script root jogosultságot igényel. Futtasd sudo-val."
    exit 1
fi

# 1. Ellenőrzés: létezik-e a felhasználó
if ! id "$TARGET_USER" &>/dev/null; then
    echo "A '$TARGET_USER' felhasználó nem létezik, kihagyva."
else
    # 2. Folyamatok leállítása SIGTERM-mel
    echo "A '$TARGET_USER' felhasználó folyamatainak leállítása (SIGTERM)..."
    pkill -TERM -u "$TARGET_USER" 2>/dev/null || true

    # Rövid várakozás
    sleep 3

    # 3. Maradék folyamatok kényszerített leállítása (SIGKILL)
    if pgrep -u "$TARGET_USER" &>/dev/null; then
        echo "Maradék folyamatok kényszerített leállítása (SIGKILL)..."
        pkill -KILL -u "$TARGET_USER" 2>/dev/null || true
        sleep 1
    fi

    # 4. Felhasználó törlése (home könyvtárral együtt)
    echo "A '$TARGET_USER' felhasználó törlése..."
    userdel -r "$TARGET_USER" 2>/dev/null && \
        echo "A '$TARGET_USER' felhasználó sikeresen törölve." || \
        echo "FIGYELEM: A felhasználó törlése közben hiba lépett fel."
fi

# 5. /etc/debian_chroot törlése
CHROOT_FILE="/etc/debian_chroot"
if [[ -f "$CHROOT_FILE" ]]; then
    echo "A '$CHROOT_FILE' fájl törlése..."
    rm -f "$CHROOT_FILE" && \
        echo "A '$CHROOT_FILE' sikeresen törölve."
else
    echo "A '$CHROOT_FILE' fájl nem létezik, kihagyva."
fi

echo "Kész."
