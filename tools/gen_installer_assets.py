#!/usr/bin/env python3
"""Ciszterci Linux - a Calamares telepítő képei (logó, ikon, üdvözlő kép, diavetítés).
Futtatás a projekt gyökeréből: python3 tools/gen_installer_assets.py   (kell: python3-pil, fonts-dejavu-core)
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "config/includes.chroot/etc/calamares/branding/ciszterci")
os.makedirs(OUT, exist_ok=True)

NAVY_TOP, NAVY_BOT = (13, 33, 54), (6, 17, 30)
TEAL, TEAL_D, TEAL_L = (46, 196, 182), (27, 143, 138), (126, 224, 214)
BLUE, AMBER, TEXT, MUTED = (58, 124, 165), (244, 185, 66), (232, 238, 244), (140, 160, 180)
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FL = "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf"

def bird(size=512):
    S = 4
    im = Image.new("RGBA", (512 * S, 512 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    def poly(pts, col):
        d.polygon([(x * S, y * S) for x, y in pts], fill=col + (255,))
    poly([(236,246),(300,236),(404,96),(468,40),(440,170),(352,282)], BLUE)
    poly([(236,246),(300,236),(404,96),(330,270)], TEAL_D)
    poly([(300,236),(404,96),(468,40),(380,210)], TEAL)
    poly([(330,372),(372,318),(462,444),(418,478)], TEAL_D)
    poly([(330,372),(372,318),(420,470),(372,440)], BLUE)
    poly([(206,262),(236,222),(312,252),(372,318),(330,372),(246,332)], TEAL)
    poly([(206,262),(246,332),(330,372),(290,300)], TEAL_D)
    poly([(236,222),(312,252),(290,300),(222,270)], TEAL_L)
    poly([(120,232),(152,192),(206,186),(240,222),(222,270),(162,270)], TEAL_L)
    poly([(152,192),(206,186),(240,222),(186,226)], TEAL)
    poly([(32,250),(130,224),(134,244)], TEXT)
    poly([(134,244),(162,270),(206,262),(176,246)], AMBER)
    r = 7 * S
    d.ellipse([(176*S-r, 218*S-r), (176*S+r, 218*S+r)], fill=NAVY_BOT + (255,))
    bb = im.getbbox()
    sc = size / max(bb[2]-bb[0], bb[3]-bb[1])
    return im.crop(bb).resize((max(1, int((bb[2]-bb[0]) * sc)), max(1, int((bb[3]-bb[1]) * sc))), Image.LANCZOS)

def text_img(text, path, px, color):
    f = ImageFont.truetype(path, px)
    box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=f)
    im = Image.new("RGBA", (box[2] + 8, box[3] + 12), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((4, 0), text, font=f, fill=color + (255,))
    return im.crop(im.getbbox())

def gradient(w, h):
    img = Image.new("RGB", (w, h)); p = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        p.line([(0, y), (w, y)], fill=tuple(int(NAVY_TOP[i] + (NAVY_BOT[i] - NAVY_TOP[i]) * t) for i in range(3)))
    return img

# productLogo: vízszintes logó az oldalsávba (átlátszó háttér)
b = bird(88); w = text_img("Ciszterci", FB, 52, TEXT)
logo = Image.new("RGBA", (b.width + 16 + w.width, 100), (0, 0, 0, 0))
logo.alpha_composite(b, (0, (100 - b.height) // 2)); logo.alpha_composite(w, (b.width + 16, (100 - w.height) // 2))
logo.save(os.path.join(OUT, "logo.png"))

# productIcon: ablakikon
sq = Image.new("RGBA", (128, 128), (0, 0, 0, 0)); bi = bird(112)
sq.alpha_composite(bi, ((128 - bi.width) // 2, (128 - bi.height) // 2)); sq.save(os.path.join(OUT, "icon.png"))

# productWelcome: üdvözlő kép (átlátszó, a telepítő sötét felületén áll)
wl = Image.new("RGBA", (720, 220), (0, 0, 0, 0))
b2 = bird(150); t1 = text_img("Ciszterci Linux", FB, 62, TEXT); t2 = text_img("Stabil. Egyszerű. Kezdőbarát.", FL, 24, MUTED)
tot = b2.width + 28 + max(t1.width, t2.width); x = (720 - tot) // 2
wl.alpha_composite(b2, (x, (220 - b2.height) // 2))
ty = (220 - (t1.height + 14 + t2.height)) // 2
wl.alpha_composite(t1, (x + b2.width + 28, ty)); wl.alpha_composite(t2, (x + b2.width + 28, ty + t1.height + 14))
wl.save(os.path.join(OUT, "welcome.png"))

# diavetítéshez: madár és az asztal rajza
bird(256).save(os.path.join(OUT, "bird.png"))
W, H = 760, 475
dk = gradient(W, H).convert("RGBA"); d = ImageDraw.Draw(dk)
bw = bird(70); dk.alpha_composite(bw, ((W - bw.width) // 2, 34))
wm = text_img("Ciszterci", FB, 34, TEXT); dk.alpha_composite(wm, ((W - wm.width) // 2, 112))
th = 56
d.rectangle([0, H - th, W, H], fill=(8, 20, 34, 255)); d.line([0, H - th, W, H - th], fill=(40, 56, 72, 255), width=1)
d.rectangle([0, H - th, th, H], fill=(24, 62, 74, 255))
sb = bird(38); dk.alpha_composite(sb, ((th - sb.width) // 2, H - th + (th - sb.height) // 2))
for i, c in enumerate([(35, 80, 86), (80, 45, 40)]):
    d.rounded_rectangle([th + 14 + i * 44, H - th + 12, th + 14 + i * 44 + 34, H - th + 46], 6, fill=c)
d.rectangle([th + 112, H - th, th + 230, H], fill=(40, 52, 66, 255)); d.rectangle([th + 112, H - 4, th + 230, H], fill=TEAL)
d.text((th + 126, H - th + 17), "Brave", font=ImageFont.truetype(FR, 15), fill=TEXT)
for i in range(3): d.ellipse([W - 130 + i * 18, H - 31, W - 118 + i * 18, H - 19], fill=MUTED)
d.text((W - 62, H - 46), "09:41", font=ImageFont.truetype(FR, 13), fill=TEXT)
d.text((W - 80, H - 28), "2026.10.14.", font=ImageFont.truetype(FR, 11), fill=MUTED)
mx, my, mw, mh = 10, H - th - 262, 250, 252
d.rounded_rectangle([mx, my, mx + mw, my + mh], 8, fill=(9, 24, 40, 252), outline=(60, 76, 92, 255))
d.rounded_rectangle([mx + 8, my + 8, mx + mw - 8, my + 38], 6, fill=(30, 42, 56, 255))
d.text((mx + 18, my + 15), "Keresés…", font=ImageFont.truetype(FR, 13), fill=MUTED)
items = [("B", "Brave", (242,106,61)), ("F", "Fájlkezelő", TEAL_L), ("W", "LibreOffice Writer", (111,179,242)),
         ("K", "KeePassXC", (107,208,143)), ("S", "Signal", (143,168,255))]
f13 = ImageFont.truetype(FR, 14); f11 = ImageFont.truetype(FB, 12)
for i, (ch, name, col) in enumerate(items):
    ry = my + 46 + i * 40
    if i == 0: d.rounded_rectangle([mx + 8, ry, mx + mw - 8, ry + 36], 6, fill=(20, 62, 70, 255))
    d.rounded_rectangle([mx + 16, ry + 7, mx + 38, ry + 29], 5, fill=col)
    d.text((mx + 22, ry + 10), ch, font=f11, fill=NAVY_BOT); d.text((mx + 48, ry + 9), name, font=f13, fill=TEXT)
dk.convert("RGB").save(os.path.join(OUT, "desktop.png"), optimize=True)
print("kész:", OUT)
