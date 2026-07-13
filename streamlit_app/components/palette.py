"""Semantic color palette for the platform's navy + gold dark theme.

Single source of truth for every color used in inline HTML/CSS across the
pages. All values are verified against WCAG 2.1 AA on the app's three dark
surfaces by ``scripts/check_contrast.py`` — run it after ANY change here.

Brand (matches the 6de.xyz website): navy ``#2E3186`` + gold ``#D4B878``.
On a DARK theme the gold is the accent that reads — it's used for links,
labels, borders, and as the primary-button fill (with navy ink on top).

Background surfaces (defined in .streamlit/config.toml + assets/theme.css):
    bg #14152A, panel #1E2140, panel2 #2A2E54  (dark, desaturated navy)

Usage:  from streamlit_app.components.palette import MUTED, DANGER, ...
"""

# Text
INK = "#EDEEF5"            # primary body text (15.5:1 on bg)
MUTED = "#B7BAD1"          # secondary text / labels (9.4:1 on bg)

# Brand accent, split by role. On dark surfaces the GOLD reads as text/border;
# it's also the primary-button FILL, but with dark navy ink (not white) on top:
ACCENT_TEXT = "#D4B878"    # gold as TEXT on dark surfaces (links, labels) 9.3:1
ACCENT_BUTTON = "#D4B878"  # gold as BUTTON FILL under navy ink (BTN_INK)
ACCENT_BORDER = "#D4B878"  # gold as a border/underline (3:1 UI rule)
BTN_INK = "#14152A"        # navy ink on gold buttons (9.3:1 on the gold fill)

# Status colors - calmer, dark-surface tuned (kept from the previous theme;
# these are semantic, not brand chrome, and still pass AA on the navy bg):
DANGER = "#F2917F"         # was #dc3545 (3.9:1) / #8b0000 (1.5:1!)
WARNING = "#E5A54E"        # was #fd7e14 / #e67e22
SUCCESS = "#62C384"        # was #198754 (2.9:1)
INFO = "#8FB8F2"           # was #0d6efd (3.0:1)
CYAN = "#6FCFE0"           # was #0dcaf0

# Aging buckets (Dashboard AR aging) - ordered severity ramp, all AA:
AGING = {
    "current": SUCCESS,
    "1-30": WARNING,
    "31-60": "#E08A45",
    "61-90": DANGER,
    "90+": "#F2776B",
}
