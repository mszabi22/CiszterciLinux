#!/usr/bin/env python3
"""Ciszterci Linux - arculati elemek generálása (Plymouth, GRUB, syslinux).
Futtatás: python3 tools/gen_assets.py   (kell hozzá: python3-pil, fonts-dejavu-core)
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INC = os.path.join(ROOT, "config/includes.chroot")
PLY = os.path.join(INC, "usr/share/plymouth/themes/ciszterci")
GRUB = os.path.join(INC, "usr/share/ciszterci/grub")
BOOT = os.path.join(ROOT, "config/bootloaders")
for d in (PLY, GRUB, os.path.join(BOOT, "grub-pc"), os.path.join(BOOT, "syslinux")):
    os.makedirs(d, exist_ok=True)

# Paletta: mély tengerkék alap (stabilitás), türkiz kiemelés (frissesség), borostyán pont (melegség)
NAVY_TOP, NAVY_BOT = (13, 33, 54), (6, 17, 30)
TEAL, TEAL_D, TEAL_L = (46, 196, 182), (27, 143, 138), (126, 224, 214)
BLUE, AMBER, TEXT, MUTED = (58, 124, 165), (244, 185, 66), (232, 238, 244), (140, 160, 180)
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FL = "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf"

def gradient(w, h):
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        px.line([(0, y), (w, y)], fill=tuple(int(NAVY_TOP[i] + (NAVY_BOT[i] - NAVY_TOP[i]) * t) for i in range(3)))
    return img

def bird(size=512, alpha=255):
    """Geometrikus (low-poly) ciszterci, balra néz. Támogatott méret: tetszőleges, 512-es rácson rajzolva."""
    S = 4
    im = Image.new("RGBA", (512 * S, 512 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    def poly(pts, col):
        d.polygon([(x * S, y * S) for x, y in pts], fill=col + (alpha,))
    # szárny (hátul, nagyobb)
    poly([(236, 246), (300, 236), (404, 96), (468, 40), (440, 170), (352, 282)], BLUE)
    poly([(236, 246), (300, 236), (404, 96), (330, 270)], TEAL_D)
    poly([(300, 236), (404, 96), (468, 40), (380, 210)], TEAL)
    # farok
    poly([(330, 372), (372, 318), (462, 444), (418, 478)], TEAL_D)
    poly([(330, 372), (372, 318), (420, 470), (372, 440)], BLUE)
    # test
    poly([(206, 262), (236, 222), (312, 252), (372, 318), (330, 372), (246, 332)], TEAL)
    poly([(206, 262), (246, 332), (330, 372), (290, 300)], TEAL_D)
    poly([(236, 222), (312, 252), (290, 300), (222, 270)], TEAL_L)
    # fej
    poly([(120, 232), (152, 192), (206, 186), (240, 222), (222, 270), (162, 270)], TEAL_L)
    poly([(152, 192), (206, 186), (240, 222), (186, 226)], TEAL)
    # csőr
    poly([(32, 250), (130, 224), (134, 244)], TEXT)
    # torokfolt (borostyán) és szem
    poly([(134, 244), (162, 270), (206, 262), (176, 246)], AMBER)
    r = 7 * S
    d.ellipse([(176 * S - r, 218 * S - r), (176 * S + r, 218 * S + r)], fill=NAVY_BOT + (255,))
    return im.resize((size, size), Image.LANCZOS)

def font(path, px):
    return ImageFont.truetype(path, px)

def wordmark(px=64, color=TEXT):
    f = font(FB, px)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = tmp.textbbox((0, 0), "Ciszterci", font=f)
    im = Image.new("RGBA", (box[2] + 8, box[3] + 16), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4, 0), "Ciszterci", font=f, fill=color + (255,))
    return im.crop(im.getbbox())

def centered(canvas, im, cx, y):
    canvas.alpha_composite(im, (int(cx - im.width / 2), int(y)))

def tagline(px, text="Stabil. Egyszerű. Kezdőbarát.", color=MUTED):
    f = font(FL, px)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    b = tmp.textbbox((0, 0), text, font=f)
    im = Image.new("RGBA", (b[2] + 8, b[3] + 12), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4, 0), text, font=f, fill=color + (255,))
    return im.crop(im.getbbox())

def scene(w, h, ghost=True):
    bg = gradient(w, h).convert("RGBA")
    if ghost:  # nagy, halvány madár a jobb alsó sarokban: mélység, de a menüt nem zavarja
        g = bird(int(h * 1.05), alpha=22)
        bg.alpha_composite(g, (int(w - g.width * 0.78), int(h - g.height * 0.80)))
    # vékony türkiz vonal alul
    ImageDraw.Draw(bg).rectangle([0, h - max(3, h // 270), w, h], fill=TEAL + (255,))
    return bg

# ---------- Plymouth ----------
logo_h = 200
b = bird(logo_h)
b.save(os.path.join(PLY, "logo.png"))
wordmark(46).save(os.path.join(PLY, "wordmark.png"))
Image.new("RGBA", (1, 4), (255, 255, 255, 38)).save(os.path.join(PLY, "track.png"))
Image.new("RGBA", (1, 4), TEAL + (255,)).save(os.path.join(PLY, "fill.png"))

# ---------- GRUB (1920x1080) ----------
W, H = 1920, 1080
g = scene(W, H)
centered(g, bird(150), W / 2, 70)
centered(g, wordmark(64), W / 2, 230)
centered(g, tagline(26), W / 2, 318)
g.convert("RGB").save(os.path.join(GRUB, "background.png"))
g.convert("RGB").save(os.path.join(BOOT, "grub-pc", "splash.png"))

# ---------- Asztal háttér (ugyanaz a kép, mint a GRUB-é) és Start gomb ikon ----------
WALL = os.path.join(INC, "usr/share/backgrounds/ciszterci")
KOL = os.path.join(INC, "usr/share/ciszterci")
os.makedirs(WALL, exist_ok=True); os.makedirs(KOL, exist_ok=True)
g.convert("RGB").save(os.path.join(WALL, "background.png"))
bird(256).save(os.path.join(KOL, "logo.png"))

# ---------- syslinux (640x480) ----------
W2, H2 = 640, 480
s = scene(W2, H2)
centered(s, bird(80), W2 / 2, 22)
centered(s, wordmark(30), W2 / 2, 108)
centered(s, tagline(14), W2 / 2, 146)
s.convert("RGB").save(os.path.join(BOOT, "syslinux", "splash.png"))

# előnézet (nem kerül az ISO-ba)
os.makedirs(os.path.join(ROOT, "tools/preview"), exist_ok=True)
g.convert("RGB").resize((960, 540)).save(os.path.join(ROOT, "tools/preview/grub.png"))
pv = gradient(960, 540).convert("RGBA")
centered(pv, b, 480, 150)
centered(pv, wordmark(46), 480, 365)
pv.alpha_composite(Image.new("RGBA", (300, 4), (255, 255, 255, 38)), (330, 430))
pv.alpha_composite(Image.new("RGBA", (190, 4), TEAL + (255,)), (330, 430))
pv.convert("RGB").save(os.path.join(ROOT, "tools/preview/plymouth.png"))
print("kész")
