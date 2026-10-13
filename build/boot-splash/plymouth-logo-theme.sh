#!/usr/bin/env bash
#
# plymouth-logo-theme.sh
# Egyszeru Plymouth tema keszitese: kozepre igazitott logo + alul futo toltocsik.
# Tesztelve: Linux Mint / LMDE (Debian alapu), Ubuntu.
# Install: sudo apt install plymouth plymouth-themes
#
set -euo pipefail

# Fix tizedespont (magyar locale-nal a tizedesvesszo elrontana a Plymouth scriptet)
export LC_ALL=C

# ---------- alapertelmezett ertekek ----------
NAME=""
LOGO=""
BG="000000"          # hatterszin (hex, # nelkul)
BAR="d4af34"         # csik szine (hex, # nelkul)
LOGO_PCT=38          # logo magassaga a kepernyo magassaganak %-aban
BAR_W_PCT=30         # csik teljes szelessege a kepernyo szelessegenek %-aban
BAR_Y_PCT=85         # csik fuggoleges pozicioja a kepernyo magassaganak %-aban
ACTIVATE=1
FIX_GRUB=0
THEMES_DIR="${THEMES_DIR:-/usr/share/plymouth/themes}"

usage() {
    cat <<EOF
Hasznalat: sudo $0 -n TEMANEV -l LOGO [opciok]

Kotelezo:
  -n NEV     A tema neve (betu, szam, kotojel, alahuzas), pl. crnl
  -l FAJL    A logo fajl (svg, png, jpg, ...)

Opcionalis:
  -b HEX     Hatterszin, alapertelmezett: ${BG}      (pl. ffffff)
  -c HEX     Toltocsik szine, alapertelmezett: ${BAR}  (pl. ffffff)
  -s SZAZ    Logo magassaga a kepernyo %-aban, alap: ${LOGO_PCT}
  -w SZAZ    Csik szelessege a kepernyo %-aban, alap: ${BAR_W_PCT}
  -y SZAZ    Csik helye fentrol a kepernyo %-aban, alap: ${BAR_Y_PCT}
  -g         Ha hianyzik, hozzaadja a "quiet splash"-t a GRUB-hoz (mentessel)
  -A         Ne aktivalja a temat (csak elkesziti)
  -h         Ez a sugo

Pelda:
  sudo $0 -n crnl -l ~/crnl_logo.svg -b 000000 -c d4af34
EOF
}

die() { echo "Hiba: $*" >&2; exit 1; }
info() { echo "==> $*"; }

# ---------- argumentumok ----------
while getopts ":n:l:b:c:s:w:y:gAh" opt; do
    case "$opt" in
        n) NAME="$OPTARG" ;;
        l) LOGO="$OPTARG" ;;
        b) BG="${OPTARG#\#}" ;;
        c) BAR="${OPTARG#\#}" ;;
        s) LOGO_PCT="$OPTARG" ;;
        w) BAR_W_PCT="$OPTARG" ;;
        y) BAR_Y_PCT="$OPTARG" ;;
        g) FIX_GRUB=1 ;;
        A) ACTIVATE=0 ;;
        h) usage; exit 0 ;;
        :) die "A(z) -$OPTARG opcionak ertek kell." ;;
        \?) usage; die "Ismeretlen opcio: -$OPTARG" ;;
    esac
done

[[ -n "$NAME" ]] || { usage; die "Hianyzik a temanev (-n)."; }
[[ -n "$LOGO" ]] || { usage; die "Hianyzik a logo (-l)."; }
[[ "$NAME" =~ ^[A-Za-z0-9_-]+$ ]] || die "A temanev csak betut, szamot, '-' es '_' jelet tartalmazhat."
[[ -f "$LOGO" ]] || die "A logo fajl nem letezik: $LOGO"
[[ "$BG"  =~ ^[0-9A-Fa-f]{6}$ ]] || die "A hatterszin (-b) 6 jegyu hex legyen, pl. 000000"
[[ "$BAR" =~ ^[0-9A-Fa-f]{6}$ ]] || die "A csik szine (-c) 6 jegyu hex legyen, pl. d4af34"
for v in LOGO_PCT BAR_W_PCT BAR_Y_PCT; do
    [[ "${!v}" =~ ^[0-9]+$ ]] && (( ${!v} >= 1 && ${!v} <= 100 )) || die "$v 1 es 100 kozotti egesz szam legyen."
done

if [[ "$THEMES_DIR" == "/usr/share/plymouth/themes" && $EUID -ne 0 ]]; then
    die "Rootkent futtasd: sudo $0 ..."
fi

THEME_DIR="${THEMES_DIR}/${NAME}"

# ---------- fuggosegek ----------
need_pkgs=()
(( ACTIVATE )) && ! command -v plymouth-set-default-theme >/dev/null 2>&1 && need_pkgs+=(plymouth plymouth-themes)
command -v convert >/dev/null 2>&1 || command -v magick >/dev/null 2>&1 || need_pkgs+=(imagemagick)
LOGO_EXT="${LOGO##*.}"; LOGO_EXT="${LOGO_EXT,,}"
if [[ "$LOGO_EXT" == "svg" ]] && ! command -v rsvg-convert >/dev/null 2>&1 && ! command -v inkscape >/dev/null 2>&1; then
    need_pkgs+=(librsvg2-bin)
fi
if (( ${#need_pkgs[@]} )); then
    info "Hianyzo csomagok telepitese: ${need_pkgs[*]}"
    apt-get update -qq
    apt-get install -y "${need_pkgs[@]}"
fi

IM=convert
command -v convert >/dev/null 2>&1 || IM="magick"

# ---------- tema mappa ----------
if [[ -e "$THEME_DIR" ]]; then
    BACKUP="${THEME_DIR}.bak.$(date +%Y%m%d-%H%M%S)"
    info "Mar letezik a tema, mentes ide: $BACKUP"
    mv "$THEME_DIR" "$BACKUP"
fi
mkdir -p "$THEME_DIR"

# ---------- logo konvertalas ----------
info "Logo konvertalasa PNG-re"
if [[ "$LOGO_EXT" == "svg" ]]; then
    if command -v rsvg-convert >/dev/null 2>&1; then
        rsvg-convert -h 800 "$LOGO" -o "$THEME_DIR/logo.png"
    elif command -v inkscape >/dev/null 2>&1; then
        inkscape "$LOGO" -h 800 -o "$THEME_DIR/logo.png" >/dev/null 2>&1
    fi
elif [[ "$LOGO_EXT" == "png" ]]; then
    cp "$LOGO" "$THEME_DIR/logo.png"
else
    "$IM" "$LOGO" -background none PNG32:"$THEME_DIR/logo.png"
fi
[[ -s "$THEME_DIR/logo.png" ]] || die "A logo konvertalasa sikertelen."

# ---------- csik kep ----------
"$IM" -size 1x1 "xc:#${BAR}" "PNG32:$THEME_DIR/bar.png"

# ---------- hatterszin -> 0..1 ----------
hex2f() { LC_ALL=C awk -v h="$((16#$1))" 'BEGIN { printf "%.3f", h/255 }'; }
BG_R=$(hex2f "${BG:0:2}")
BG_G=$(hex2f "${BG:2:2}")
BG_B=$(hex2f "${BG:4:2}")

# ---------- .plymouth leiro ----------
cat > "$THEME_DIR/${NAME}.plymouth" <<EOF
[Plymouth Theme]
Name=${NAME}
Description=Kozepre igazitott logo es toltocsik
ModuleName=script

[script]
ImageDir=${THEME_DIR}
ScriptFile=${THEME_DIR}/${NAME}.script
EOF

# ---------- .script ----------
cat > "$THEME_DIR/${NAME}.script" <<EOF
# Hatter
Window.SetBackgroundTopColor(${BG_R}, ${BG_G}, ${BG_B});
Window.SetBackgroundBottomColor(${BG_R}, ${BG_G}, ${BG_B});

screen_w = Window.GetWidth();
screen_h = Window.GetHeight();

# Logo kozepre, a kepernyo magassaganak ${LOGO_PCT}%-ara skalazva
logo.orig = Image("logo.png");
logo_h = Math.Int(screen_h * ${LOGO_PCT} / 100);
logo_w = Math.Int(logo.orig.GetWidth() * logo_h / logo.orig.GetHeight());
logo.image = logo.orig.Scale(logo_w, logo_h);
logo.sprite = Sprite(logo.image);
logo.sprite.SetX(Math.Int(screen_w / 2 - logo_w / 2));
logo.sprite.SetY(Math.Int(screen_h / 2 - logo_h / 2));

# Toltocsik
bar_w = Math.Int(screen_w * ${BAR_W_PCT} / 100);
bar_h = Math.Int(screen_h * 0.004);
if (bar_h < 3) bar_h = 3;
bar_x = Math.Int(screen_w / 2 - bar_w / 2);
bar_y = Math.Int(screen_h * ${BAR_Y_PCT} / 100);

bar.image = Image("bar.png");
bar.sprite = Sprite();
bar.sprite.SetX(bar_x);
bar.sprite.SetY(bar_y);
bar.sprite.SetImage(bar.image.Scale(1, bar_h));

fun progress_callback(duration, progress) {
    w = Math.Int(bar_w * progress);
    if (w < 1) w = 1;
    bar.sprite.SetImage(bar.image.Scale(w, bar_h));
}

Plymouth.SetBootProgressFunction(progress_callback);
EOF

grep -qE 'Color\([0-9]\.[0-9]{3}, [0-9]\.[0-9]{3}, [0-9]\.[0-9]{3}\)' "$THEME_DIR/${NAME}.script" || die "Hibas hatterszin-ertek a generalt scriptben: $THEME_DIR/${NAME}.script"

chmod -R a+rX "$THEME_DIR"
info "Tema elkeszult: $THEME_DIR"

# ---------- GRUB: quiet splash ----------
GRUB_FILE="/etc/default/grub"
if [[ -f "$GRUB_FILE" && "$THEMES_DIR" == "/usr/share/plymouth/themes" ]]; then
    if grep -E '^GRUB_CMDLINE_LINUX_DEFAULT=' "$GRUB_FILE" | grep -q 'splash'; then
        :
    elif (( FIX_GRUB )); then
        cp "$GRUB_FILE" "${GRUB_FILE}.bak.$(date +%Y%m%d-%H%M%S)"
        sed -i -E 's/^(GRUB_CMDLINE_LINUX_DEFAULT=")([^"]*)"/\1\2 quiet splash"/' "$GRUB_FILE"
        info "A 'quiet splash' hozzaadva a GRUB-hoz, update-grub fut."
        update-grub
    else
        echo "Figyelem: a GRUB_CMDLINE_LINUX_DEFAULT nem tartalmazza a 'splash'-t," >&2
        echo "          enelkul a Plymouth nem jelenik meg. Futtasd ujra -g kapcsoloval," >&2
        echo "          vagy add hozza kezzel, majd: sudo update-grub" >&2
    fi
fi

# ---------- aktivalas ----------
if (( ACTIVATE )) && [[ "$THEMES_DIR" == "/usr/share/plymouth/themes" ]]; then
    info "Tema aktivalasa (initramfs ujragenerals)"
    if command -v plymouth-set-default-theme >/dev/null 2>&1; then
        plymouth-set-default-theme -R "$NAME"
    else
        update-alternatives --install "$THEMES_DIR/default.plymouth" default.plymouth \
            "$THEME_DIR/${NAME}.plymouth" 100
        update-alternatives --set default.plymouth "$THEME_DIR/${NAME}.plymouth"
        update-initramfs -u
    fi
    info "Kesz. Inditsd ujra a gepet a kiprobalashoz."
else
    info "Aktivalas kihagyva. Kezzel: sudo plymouth-set-default-theme -R ${NAME}"
fi
