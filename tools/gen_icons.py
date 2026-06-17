"""Generate AudioCowboy's flat icon set with Pillow.

Each icon is a rounded-square background in an accent colour with a simple white
pictogram, drawn at 4x and downscaled for smooth edges. Run from the repo root:

    python tools/gen_icons.py
"""
import os
from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Images")
SS = 4            # supersample factor
SIZE = 256        # final size
S = SIZE * SS     # working size
WHITE = (255, 255, 255, 255)


def canvas(bg):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(0.22 * S), fill=bg)
    return img, d


def save(img, name):
    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    img.save(os.path.join(OUT_DIR, name))


def p(*xy):
    """Scale a list of 0..256 coordinates into working space."""
    return [v * SS for v in xy]


def poly(d, pts, fill=WHITE):
    d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)


def rrect(d, box, radius, fill=WHITE):
    d.rounded_rectangle(p(*box), radius=radius * SS, fill=fill)


def ellipse(d, box, fill=WHITE):
    d.ellipse(p(*box), fill=fill)


def line(d, box, width, fill=WHITE):
    d.line(p(*box), width=width * SS, fill=fill)


def arc(d, box, start, end, width, fill=WHITE):
    d.arc(p(*box), start, end, fill=fill, width=width * SS)


# --------------------------------------------------------------------------- #
def icon_app():
    # Cowboy hat on teal — the AudioCowboy mark.
    img, d = canvas((31, 111, 120, 255))
    # brim
    d.ellipse(p(40, 150, 216, 196), fill=WHITE)
    # crown
    poly(d, [(96, 168), (104, 96), (118, 78), (138, 78), (152, 96), (160, 168)])
    # band
    d.rectangle(p(96, 150, 160, 168), fill=(31, 111, 120, 255))
    save(img, "app.png")


def icon_output():
    # Speaker with sound waves on blue.
    img, d = canvas((37, 99, 235, 255))
    poly(d, [(70, 104), (104, 104), (150, 70), (150, 186), (104, 152), (70, 152)])
    arc(d, [150, 78, 200, 178], -55, 55, 12)
    arc(d, [150, 58, 226, 198], -50, 50, 12)
    save(img, "output.png")


def icon_input():
    # Microphone on rose.
    img, d = canvas((219, 39, 119, 255))
    rrect(d, [108, 56, 148, 150], radius=20)
    arc(d, [84, 84, 172, 172], 20, 160, 12)
    line(d, [128, 168, 128, 196], 12)
    line(d, [100, 196, 156, 196], 12)
    save(img, "input.png")


def icon_profile():
    # Folder on amber.
    img, d = canvas((245, 158, 11, 255))
    poly(d, [(64, 92), (108, 92), (124, 110), (192, 110), (192, 176), (64, 176)])
    save(img, "profile.png")


def icon_save():
    # Floppy disk on green.
    img, d = canvas((22, 163, 74, 255))
    bg = (22, 163, 74, 255)
    poly(d, [(72, 72), (168, 72), (184, 88), (184, 184), (72, 184)])
    d.rectangle(p(96, 72, 152, 104), fill=bg)        # shutter slot
    d.rectangle(p(140, 76, 152, 100), fill=WHITE)
    d.rectangle(p(92, 132, 164, 184), fill=bg)       # label area
    save(img, "save.png")


def icon_delete():
    # Trash can on red.
    img, d = canvas((220, 38, 38, 255))
    line(d, [72, 88, 184, 88], 12)                   # lid
    d.rectangle(p(108, 70, 148, 84), fill=WHITE)     # handle
    poly(d, [(86, 96), (170, 96), (160, 188), (96, 188)])  # body
    bg = (220, 38, 38, 255)
    for x in (110, 128, 146):
        line(d, [x, 112, x, 172], 6, fill=bg)
    save(img, "delete.png")


def icon_warning():
    # Triangle with exclamation on amber.
    img, d = canvas((217, 119, 6, 255))
    poly(d, [(128, 60), (196, 188), (60, 188)])
    bg = (217, 119, 6, 255)
    d.rounded_rectangle(p(121, 104, 135, 156), radius=7 * SS, fill=bg)
    d.ellipse(p(120, 166, 136, 182), fill=bg)
    save(img, "warning.png")


def icon_error():
    # Circle with X on red.
    img, d = canvas((220, 38, 38, 255))
    ellipse(d, [62, 62, 194, 194])
    bg = (220, 38, 38, 255)
    line(d, [102, 102, 154, 154], 14, fill=bg)
    line(d, [154, 102, 102, 154], 14, fill=bg)
    save(img, "error.png")


def icon_back():
    # Left arrow on slate.
    img, d = canvas((71, 85, 105, 255))
    poly(d, [(96, 128), (152, 80), (152, 110), (180, 110), (180, 146), (152, 146), (152, 176)])
    save(img, "back.png")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for fn in (icon_app, icon_output, icon_input, icon_profile, icon_save,
               icon_delete, icon_warning, icon_error, icon_back):
        fn()
    print("Icons written to", OUT_DIR)


if __name__ == "__main__":
    main()
