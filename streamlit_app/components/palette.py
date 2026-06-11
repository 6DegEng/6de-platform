"""Semantic color palette for the platform's warm-dark theme.

Single source of truth for every color used in inline HTML/CSS across the
pages. All values are verified against WCAG 2.1 AA on the app's three dark
surfaces by ``scripts/check_contrast.py`` — run it after ANY change here.

Background surfaces (defined in .streamlit/config.toml + assets/theme.css):
    bg #15120F, panel #211B15, panel2 #2A231C

Usage:  from streamlit_app.components.palette import MUTED, DANGER, ...
"""

# Text
INK = "#F2EDE5"            # primary body text
MUTED = "#C6BCAE"          # secondary text / labels (was #6c757d - 3.0:1, FAIL)

# Brand accent, split by role:
ACCENT_TEXT = "#E78A52"    # accent as TEXT on dark surfaces (links, labels)
ACCENT_BUTTON = "#A23A0D"  # accent as BUTTON FILL under white text
ACCENT_BORDER = "#B8410F"  # accent as a border/underline (3:1 UI rule)

# Status colors - calmer, dark-surface tuned (the old saturated Bootstrap
# light-theme values strained the eyes and failed AA on dark):
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
