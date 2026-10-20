#!/usr/bin/env bash
# Windows 11-szerű kinézet Xfce 4.20-hoz (Debian 13)
# GTK/xfwm4: Fluent-gtk-theme (vinceliuice), ikonok: Win11-icon-theme (yeyushengfan258),
# kurzor: Fluent cursors, betűtípus: Inter, háttérkép és Start ikon saját rajzolású
#
# Használat:  bash xfce-win11.sh [dark|light]
set -euo pipefail

MODE="${1:-dark}"                       # dark | light
case "$MODE" in dark|light) ;; *) echo "Használat: $0 [dark|light]"; exit 1;; esac
MODE_CAP="$(tr '[:lower:]' '[:upper:]' <<<"${MODE:0:1}")${MODE:1}"   # Dark | Light

SRC="$HOME/.cache/xfce-win11-src"
THEMES="$HOME/.themes"
ICONS="$HOME/.local/share/icons"
mkdir -p "$SRC" "$THEMES" "$ICONS"

echo "==> Csomagok telepítése (sudo kell)"
sudo apt update
sudo apt install -y git sassc fonts-inter xfce4-settings libglib2.0-bin librsvg2-bin x11-xserver-utils

# opcionális csomagok: ha valamelyik nem elérhető, nem baj
for pkg in gnome-themes-extra gtk2-engines-murrine xfce4-whisker-menu-plugin; do
    sudo apt install -y "$pkg" || echo "   (kihagyva, nem elérhető: $pkg)"
done

clone() {  # clone <url> <könyvtár>
    if [ -d "$SRC/$2/.git" ]; then git -C "$SRC/$2" pull --ff-only
    else git clone --depth=1 "$1" "$SRC/$2"; fi
}

echo "==> GTK + xfwm4 téma (Fluent)"
clone https://github.com/vinceliuice/Fluent-gtk-theme.git Fluent-gtk-theme
( cd "$SRC/Fluent-gtk-theme" && ./install.sh -d "$THEMES" -c "$MODE" --tweaks round )

echo "==> Ikonkészlet (Win11-icon-theme)"
clone https://github.com/yeyushengfan258/Win11-icon-theme.git Win11-icon-theme
( cd "$SRC/Win11-icon-theme" && ./install.sh -d "$ICONS" )

echo "==> Kurzor (Fluent cursors) – ha nem sikerül, kihagyjuk"
clone https://github.com/vinceliuice/Fluent-icon-theme.git Fluent-icon-theme
if [ -f "$SRC/Fluent-icon-theme/cursors/install.sh" ]; then
    ( cd "$SRC/Fluent-icon-theme/cursors" && ./install.sh ) || echo "   (kurzor telepítése kihagyva)"
fi

# --- a ténylegesen létrejött nevek megkeresése ---
GTK_THEME="$(find "$THEMES" -maxdepth 1 -type d -name "Fluent*round*${MODE_CAP}" -printf '%f\n' | head -n1 || true)"
[ -z "$GTK_THEME" ] && GTK_THEME="$(find "$THEMES" -maxdepth 1 -type d -name "Fluent*${MODE_CAP}*" -printf '%f\n' | head -n1 || true)"
if [ "$MODE" = dark ]; then ICON_PAT="Win11-dark"; else ICON_PAT="Win11"; fi
ICON_THEME="$(find "$ICONS" -maxdepth 1 -type d -name "$ICON_PAT" -printf '%f\n' | head -n1 || true)"
CURSOR_THEME="$(find "$ICONS" "$HOME/.icons" -maxdepth 1 -type d -iname "*fluent*cursor*" -printf '%f\n' 2>/dev/null | head -n1 || true)"

echo "   GTK téma:   ${GTK_THEME:-nincs}"
echo "   Ikonok:     ${ICON_THEME:-nincs}"
echo "   Kurzor:     ${CURSOR_THEME:-nincs}"

xset_str() {  # xset_str <csatorna> <property> <érték>
    xfconf-query -c "$1" -p "$2" -n -t string -s "$3"
}

echo "==> Xfce beállítások"
[ -n "$GTK_THEME" ]    && xset_str xsettings /Net/ThemeName "$GTK_THEME"
[ -n "$ICON_THEME" ]   && xset_str xsettings /Net/IconThemeName "$ICON_THEME"
[ -n "$CURSOR_THEME" ] && xset_str xsettings /Gtk/CursorThemeName "$CURSOR_THEME"
xset_str xsettings /Gtk/FontName "Inter 10"

# ablakkeret: Win11-es elrendezés (cím balra, gombok jobbra)
if [ -n "$GTK_THEME" ] && [ -d "$THEMES/$GTK_THEME/xfwm4" ]; then
    xset_str xfwm4 /general/theme "$GTK_THEME"
fi
xset_str xfwm4 /general/title_font "Inter Semi-Bold 10"
xset_str xfwm4 /general/title_alignment "left"
xset_str xfwm4 /general/button_layout "O|HMC"

echo "==> Háttérkép generálása és beállítása (saját rajzolású 'bloom' stílus)"
WPDIR="$HOME/.local/share/backgrounds"
mkdir -p "$WPDIR"
WP_SVG="$WPDIR/win11-bloom-$MODE.svg"
WP="$WPDIR/win11-bloom-$MODE.png"

if [ "$MODE" = dark ]; then
    BG1="#010716"; BG2="#0b3a8c"; P1="#6fd3ff"; P2="#0a46c8"; P3="#a8e6ff"; GL="#1e6bff"
else
    BG1="#f3f8ff"; BG2="#b7d6ff"; P1="#ffffff"; P2="#3d86ff"; P3="#ffffff"; GL="#9cc8ff"
fi
PA=""; PB=""
for a in 0 60 120 180 240 300; do
    PA+="<ellipse cx=\"0\" cy=\"-330\" rx=\"250\" ry=\"520\" transform=\"rotate($((a+8)))\" fill=\"url(#pg)\" opacity=\"0.75\"/>"
done
for a in 30 90 150 210 270 330; do
    PB+="<ellipse cx=\"0\" cy=\"-250\" rx=\"170\" ry=\"400\" transform=\"rotate($((a-6)))\" fill=\"url(#pg2)\" opacity=\"0.6\"/>"
done
cat > "$WP_SVG" <<SVGEOF
<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2160" viewBox="0 0 3840 2160">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="$BG1"/><stop offset="1" stop-color="$BG2"/></linearGradient>
<radialGradient id="pg" cx="0.5" cy="0.85" r="0.9"><stop offset="0" stop-color="$P1"/><stop offset="1" stop-color="$P2"/></radialGradient>
<radialGradient id="pg2" cx="0.5" cy="0.85" r="0.9"><stop offset="0" stop-color="$P3"/><stop offset="1" stop-color="$P1"/></radialGradient>
<radialGradient id="gl" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="$GL" stop-opacity="0.7"/><stop offset="1" stop-color="$GL" stop-opacity="0"/></radialGradient>
<filter id="b1" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
<filter id="b2" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="60"/></filter>
</defs>
<rect width="3840" height="2160" fill="url(#bg)"/>
<circle cx="1920" cy="1080" r="1500" fill="url(#gl)"/>
<g transform="translate(1920 1080)" filter="url(#b1)">$PA</g>
<g transform="translate(1920 1080)" filter="url(#b1)">$PB</g>
<circle cx="1920" cy="1080" r="140" fill="$P3" opacity="0.55" filter="url(#b2)"/>
</svg>
SVGEOF
rsvg-convert -w 3840 -h 2160 "$WP_SVG" -o "$WP"

# minden már ismert monitor/munkaterület + az xrandr szerinti monitorok
mapfile -t WP_KEYS < <(xfconf-query -c xfce4-desktop -l 2>/dev/null | grep '/last-image$' || true)
for m in $(xrandr --query 2>/dev/null | awk '/ connected/{print $1}'); do
    WP_KEYS+=("/backdrop/screen0/monitor${m}/workspace0/last-image")
done
for k in "${WP_KEYS[@]}"; do
    xfconf-query -c xfce4-desktop -p "$k" -n -t string -s "$WP"
    xfconf-query -c xfce4-desktop -p "${k%last-image}image-style" -n -t int -s 5   # 5 = kitöltés (zoom)
done
xfdesktop --reload 2>/dev/null || true

echo "==> Start menü ikon (kék négyablakos ikon)"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
START_ICON="$ICON_DIR/start-win11.svg"
cat > "$START_ICON" <<SVGEOF
<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48">
<defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4cc2ff"/><stop offset="1" stop-color="#0a6cff"/></linearGradient>
</defs>
<rect x="5" y="5" width="18" height="18" rx="1.5" fill="url(#g)"/>
<rect x="25" y="5" width="18" height="18" rx="1.5" fill="url(#g)"/>
<rect x="5" y="25" width="18" height="18" rx="1.5" fill="url(#g)"/>
<rect x="25" y="25" width="18" height="18" rx="1.5" fill="url(#g)"/>
</svg>
SVGEOF
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# a panel menü-bővítményeinek megkeresése (Alkalmazásmenü vagy Whisker)
FOUND_MENU=0
while read -r path plugin; do
    [ -z "${path:-}" ] && continue
    xfconf-query -c xfce4-panel -p "$path/button-icon" -n -t string -s "$START_ICON"
    xfconf-query -c xfce4-panel -p "$path/show-button-title" -n -t bool -s false
    FOUND_MENU=1
    echo "   beállítva: $path ($plugin)"
done < <(xfconf-query -c xfce4-panel -l -v 2>/dev/null \
         | awk '$1 ~ /^\/plugins\/plugin-[0-9]+$/ && ($2=="applicationsmenu" || $2=="whiskermenu") {print $1, $2}')

if [ "$FOUND_MENU" = 1 ]; then
    xfce4-panel -r >/dev/null 2>&1 &
else
    echo "   Nem találtam menü-bővítményt a panelen; add hozzá az 'Alkalmazásmenü' elemet, majd futtasd újra a szkriptet."
fi

cat <<'EOF'

Kész. Kézzel még érdemes:
  1. Panel: Panel beállítások -> alulra, 100% hosszú, magasság ~44-48 px.
  2. Indítók középre: két "Elválasztó" elem (kiterjesztett) a bal és jobb szélre.
  3. Start menü: az ikon automatikusan beállt; ha nem látszik, jelentkezz ki és be.
  4. Qt appok: sudo apt install qt5ct qt6ct kvantum, QT_QPA_PLATFORMTHEME=qt5ct.
Ha valami elcsúszott: jelentkezz ki és be, hogy az xfwm4/GTK téma frissüljön.
EOF
