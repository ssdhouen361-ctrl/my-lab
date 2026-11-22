"""Render exact, pixel-perfect UI mockups for all 6 color themes of TacTicTap.
Ensures zero font hallucination or random variation between generations.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WATCH_SIZE = 480  # 480x480 Galaxy Watch 8 44mm circular display
BEZEL_PADDING = 30
TOTAL_W = 1600
TOTAL_H = 1120

# 6 Themes:
# 1. Dark Orange
# 2. Dark Green
# 3. Dark Monochrome
# 4. Light Warm Amber/Orange (refined pleasant tone)
# 5. Light Green
# 6. Light Monochrome

THEMES = [
    {
        "name": "1. Dark Amber-Orange (Setup Mode: 33:24)",
        "bg": (0, 0, 0),
        "active_fg": (255, 140, 0),       # High-clarity energetic deep amber-orange
        "inactive_fg": (255, 140, 0, 110), # 43% opacity (clearly legible, not too dim)
        "hairline": (255, 140, 0, 40),
        "digits": ("3", "3:24"),
        "active_idx": 0,
        "is_dark": True,
        "colon_blink": False,
    },
    {
        "name": "2. Dark Cyber Green (Running: 15:00)",
        "bg": (0, 0, 0),
        "active_fg": (0, 255, 110),
        "inactive_fg": (0, 255, 110),
        "hairline": (0, 255, 110, 40),
        "digits": ("15:00", ""),
        "active_idx": -1,
        "is_dark": True,
        "colon_blink": True,
    },
    {
        "name": "3. Dark Monochrome (Running: 25:00)",
        "bg": (0, 0, 0),
        "active_fg": (255, 255, 255),
        "inactive_fg": (255, 255, 255),
        "hairline": (255, 255, 255, 40),
        "digits": ("25:00", ""),
        "active_idx": -1,
        "is_dark": True,
        "colon_blink": True,
    },
    {
        "name": "4. Light Refined Amber (Setup Mode: 33:24)",
        "bg": (248, 248, 250),           # Premium soft off-white
        "active_fg": (225, 100, 0),       # Rich Hermès/Amber orange (not garish)
        "inactive_fg": (225, 100, 0, 115),# 45% opacity (clearly visible)
        "hairline": (225, 100, 0, 50),
        "digits": ("3", "3:24"),
        "active_idx": 0,
        "is_dark": False,
        "colon_blink": False,
    },
    {
        "name": "5. Light Emerald Green (Running: 15:00)",
        "bg": (248, 248, 250),
        "active_fg": (0, 168, 85),
        "inactive_fg": (0, 168, 85),
        "hairline": (0, 168, 85, 50),
        "digits": ("15:00", ""),
        "active_idx": -1,
        "is_dark": False,
        "colon_blink": True,
    },
    {
        "name": "6. Light Monochrome (Running: 25:00)",
        "bg": (248, 248, 250),
        "active_fg": (20, 22, 26),        # Deep charcoal
        "inactive_fg": (20, 22, 26),
        "hairline": (20, 22, 26, 50),
        "digits": ("25:00", ""),
        "active_idx": -1,
        "is_dark": False,
        "colon_blink": True,
    },
]

def render_watch_case(size=WATCH_SIZE):
    # Renders circular watch body with subtle bezel
    case = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(case)
    # Bezel
    d.ellipse((0, 0, size, size), fill=(28, 30, 34), outline=(50, 53, 60), width=4)
    # Screen inner circle
    margin = 8
    d.ellipse((margin, margin, size - margin, size - margin), fill=(0, 0, 0, 255))
    return case

def render_all_themes():
    canvas = Image.new("RGB", (TOTAL_W, TOTAL_H), (15, 16, 18))
    draw = ImageDraw.Draw(canvas)

    # Fonts
    font_path = "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf"
    title_font_path = "/System/Library/Fonts/SFNS.ttf"
    
    number_font = ImageFont.truetype(font_path, 110)
    label_font = ImageFont.truetype(title_font_path, 22)
    small_tag_font = ImageFont.truetype(title_font_path, 17)

    # Grid 3 columns x 2 rows
    col_w = TOTAL_W // 3
    row_h = (TOTAL_H - 80) // 2
    offset_y = 60

    # Main title
    draw.text((TOTAL_W // 2, 30), "TacTicTap — All 6 Themes & Visual States (Galaxy Watch 8 44mm)",
              fill=(220, 225, 230), font=label_font, anchor="mm")

    watch_case = render_watch_case(WATCH_SIZE)

    for i, t in enumerate(THEMES):
        col = i % 3
        row = i // 3
        center_x = col * col_w + col_w // 2
        center_y = offset_y + row * row_h + row_h // 2

        # Draw watch case
        watch_layer = Image.new("RGBA", (WATCH_SIZE, WATCH_SIZE), (0, 0, 0, 0))
        wd = ImageDraw.Draw(watch_layer)

        # Screen background circle
        screen_m = 10
        screen_rect = (screen_m, screen_m, WATCH_SIZE - screen_m, WATCH_SIZE - screen_m)
        wd.ellipse(screen_rect, fill=t["bg"])

        # Hairline at bottom 1/3 (y = WATCH_SIZE * 0.67) if in setup mode
        if t["active_idx"] == 0:
            hl_y = int(WATCH_SIZE * 0.67)
            wd.line([(screen_m + 30, hl_y), (WATCH_SIZE - screen_m - 30, hl_y)],
                    fill=t["hairline"], width=2)

        # Numbers
        # Setup mode: first digit highlighted, rest dimmer
        num_y = int(WATCH_SIZE * 0.46)
        
        if t["active_idx"] == 0:
            # Measure exact widths
            act_text = t["digits"][0]
            inact_text = t["digits"][1]
            full_text = act_text + inact_text
            bbox = number_font.getbbox(full_text)
            total_num_w = bbox[2] - bbox[0]
            start_x = WATCH_SIZE // 2 - total_num_w // 2

            # Draw active digit
            wd.text((start_x, num_y), act_text, fill=t["active_fg"], font=number_font, anchor="lm")
            act_bbox = number_font.getbbox(act_text)
            act_w = act_bbox[2] - act_bbox[0]

            # Draw inactive digits (adjusted to ~45% alpha so clearly readable)
            wd.text((start_x + act_w, num_y), inact_text, fill=t["inactive_fg"], font=number_font, anchor="lm")
        else:
            text = t["digits"][0]
            wd.text((WATCH_SIZE // 2, num_y), text, fill=t["active_fg"], font=number_font, anchor="mm")

        # Paste watch layer onto canvas
        watch_img = Image.alpha_composite(watch_case, watch_layer)
        canvas.paste(watch_img, (center_x - WATCH_SIZE // 2, center_y - WATCH_SIZE // 2 - 20), watch_img)

        # Label below each watch
        draw.text((center_x, center_y + WATCH_SIZE // 2 - 5), t["name"],
                  fill=(190, 195, 205), font=small_tag_font, anchor="mm")

    out_path = Path("/Users/sasadayuto/my-lab/projects/galaxy-watch-timer/docs/mockups/tactictap_all_6_themes.jpg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(out_path), quality=95)
    print("Saved:", out_path)

if __name__ == "__main__":
    render_all_themes()
