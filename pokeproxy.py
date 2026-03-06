#!/usr/bin/env python3
"""PokeProxy - Generate readable Pokemon TCG proxy cards with large text."""

import base64
import io
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import freetype

from set_codes import SET_MAP

CACHE_DIR = Path(__file__).parent / "cache"
OUTPUT_DIR = Path(__file__).parent / "output"

# Pokemon card dimensions: 2.5" x 3.5" at 300dpi = 750x1050
# We'll use a standard card ratio for SVG
CARD_W = 750
CARD_H = 1050  # 2.5" x 3.5" at 300dpi, ratio 5:7

# Artwork crop region on the 600x825 source image (approximate)
# The art sits roughly in the center, below the name bar, above the attacks
ART_TOP = 110
ART_BOTTOM = 430
ART_LEFT = 45
ART_RIGHT = 555

# Type colors — deeper/saturated to match real TCG cards
TYPE_COLORS = {
    "Grass": "#3B9B2F",
    "Fire": "#D4301A",
    "Water": "#2980C0",
    "Lightning": "#E8A800",
    "Psychic": "#A8318C",
    "Fighting": "#A0522D",
    "Darkness": "#3E2D68",
    "Metal": "#8A8A9A",
    "Fairy": "#D44D8A",
    "Dragon": "#5B2DA0",
    "Colorless": "#8A8A70",
}

# Energy symbols (single-letter abbreviations)
ENERGY_ABBREV = {
    "Grass": "G",
    "Fire": "R",
    "Water": "W",
    "Lightning": "L",
    "Psychic": "P",
    "Fighting": "F",
    "Darkness": "D",
    "Metal": "M",
    "Fairy": "Y",
    "Dragon": "N",
    "Colorless": "C",
}

# --- FreeType font measurement ---
# Load the actual fonts used in SVG rendering for accurate text measurement
_TITLE_FACE = freetype.Face('/System/Library/Fonts/Supplemental/Arial Black.ttf')
_BODY_FACE = freetype.Face('/System/Library/Fonts/HelveticaNeue.ttc', 1)  # Bold


def _measure_width(face, text, size_px):
    """Measure text width in pixels using FreeType glyph advances."""
    face.set_pixel_sizes(0, size_px)
    width = 0
    for ch in text:
        face.load_char(ch, freetype.FT_LOAD_DEFAULT)
        width += face.glyph.advance.x >> 6
    return width


def ft_wrap(face, text, size_px, max_width):
    """Word-wrap text using actual glyph measurements. Returns list of lines."""
    if not text:
        return []
    # Strip energy symbols {X} for measurement (they render as single glyphs)
    import re
    clean = re.sub(r'\{[A-Z]\}', '\u2B24', text)
    words = clean.split()
    lines = []
    current = []
    for word in words:
        test_line = ' '.join(current + [word])
        if _measure_width(face, test_line, size_px) > max_width and current:
            lines.append(' '.join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(' '.join(current))
    return lines


def ft_content_height(body_size, head_size, max_width, category,
                      trainer_effect, abilities, attacks):
    """Measure total content height using FreeType. Mirrors the render layout."""
    line_h = int(body_size * 1.25)  # LINE_H = BASE_LINE_H * scale = 30/24 * body
    h = 0
    if category == "Trainer" and trainer_effect:
        h += len(ft_wrap(_BODY_FACE, trainer_effect, body_size, max_width)) * line_h
        h += int(body_size * 0.83)  # 20/24 * body_size
    for ab in abilities:
        h += int(head_size * 0.5)  # gap after header text
        effect = ab.get("effect", "")
        h += len(ft_wrap(_BODY_FACE, effect, body_size, max_width)) * line_h
        h += int(body_size * 1.46)
    for atk in attacks:
        h += int(head_size * 0.64)  # gap after attack header
        effect = atk.get("effect", "")
        if effect:
            h += len(ft_wrap(_BODY_FACE, effect, body_size, max_width)) * line_h
        h += int(body_size * 1.25)
    return h


def fetch_card(set_code: str, number: str) -> dict:
    """Fetch card data from TCGdex API."""
    tcgdex_id = SET_MAP.get(set_code.upper())
    if not tcgdex_id:
        raise ValueError(f"Unknown set code: {set_code}. Known: {', '.join(SET_MAP.keys())}")

    padded = number.zfill(3)
    url = f"https://api.tcgdex.net/v2/en/cards/{tcgdex_id}-{padded}"

    cache_file = CACHE_DIR / f"{tcgdex_id}-{padded}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    print(f"  Fetching card data: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "PokeProxy/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, indent=2))
    return data


def fetch_image(image_url: str, card_id: str) -> bytes:
    """Fetch and cache card image."""
    cache_file = CACHE_DIR / f"{card_id}.png"
    if cache_file.exists():
        return cache_file.read_bytes()

    full_url = image_url + "/high.png"
    print(f"  Fetching image: {full_url}")
    req = urllib.request.Request(full_url, headers={"User-Agent": "PokeProxy/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(data)
    return data


def crop_artwork(image_data: bytes) -> str:
    """Crop the artwork portion from the card image, return as base64 PNG.

    Uses PIL if available, otherwise embeds the full image.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_data))
        # Scale crop coords to actual image size
        scale_x = img.width / 600
        scale_y = img.height / 825
        box = (
            int(ART_LEFT * scale_x),
            int(ART_TOP * scale_y),
            int(ART_RIGHT * scale_x),
            int(ART_BOTTOM * scale_y),
        )
        cropped = img.crop(box)
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        print("  Warning: Pillow not installed, using full card image. Install with: pip install Pillow")
        return base64.b64encode(image_data).decode()


ENERGY_COLORS = {
    "Grass": "#3B9B2F", "G": "#3B9B2F",
    "Fire": "#D4301A", "R": "#D4301A",
    "Water": "#2980C0", "W": "#2980C0",
    "Lightning": "#E8A800", "L": "#E8A800",
    "Psychic": "#A8318C", "P": "#A8318C",
    "Fighting": "#A0522D", "F": "#A0522D",
    "Darkness": "#3E2D68", "D": "#3E2D68",
    "Metal": "#8A8A9A", "M": "#8A8A9A",
    "Fairy": "#D44D8A", "Y": "#D44D8A",
    "Dragon": "#5B2DA0", "N": "#5B2DA0",
    "Colorless": "#8A8A70", "C": "#8A8A70",
}



# Text compression: shorten verbose Pokemon TCG phrasing
COMPRESS_RULES = [
    # === Long phrases first (before sub-phrases get replaced) ===
    # Evolution trigger
    ("When you play this Pokémon from your hand to evolve 1 of your Pokémon during your turn, you may",
     "On evolve:"),
    ("When you play this Pokémon from your hand to evolve 1 of your Pokémon during your turn,",
     "On evolve,"),
    # Knock out — long forms first
    ("is Knocked Out by damage from an attack from your opponent's Pokémon", "is KO'd by opponent"),
    ("were Knocked Out during your opponent's last turn", "were KO'd last turn"),
    ("would be Knocked Out", "would be KO'd"),
    ("is Knocked Out", "is KO'd"),
    ("Knocked Out", "KO'd"),
    # Next turn restrictions
    ("During your next turn, this Pokémon can't attack", "Can't attack next turn"),
    ("During your next turn, this Pokémon can't use", "Can't use next turn:"),
    # Cure
    ("This Pokémon recovers from all Special Conditions", "Cure all conditions"),
    # Switch
    ("Switch your Active Pokémon with 1 of your Benched Pokémon", "Switch Active with Bench"),
    ("1 of your opponent's Benched Pokémon to the Active Spot", "1 of opponent's Bench to Active"),
    # === Pokemon references ===
    ("your opponent's Active Pokémon", "the Defending Pokémon"),
    ("your opponent's Benched Pokémon", "opponent's Bench"),
    ("your Active Pokémon", "your Active"),
    ("your Benched Pokémon", "your Bench"),
    ("to your Pokémon in any way you like", "to your Pokémon however you like"),
    ("this Pokémon", "it"),
    ("This Pokémon", "It"),
    # === Turn / timing ===
    ("Once during your first turn, you may", "First turn, you may"),
    ("Once during your turn", "Once a turn"),
    ("Once during each player's turn, that player may", "Once a turn, each player may"),
    ("As often as you like during your turn, you may", "Any number of times,"),
    ("As often as you like on your turn, you may", "Any number of times,"),
    ("during your turn", "on your turn"),
    # === Search / deck ===
    ("Search your deck for", "Search deck for"),
    ("search your deck for", "search deck for"),
    ("Then, shuffle your deck.", "Shuffle deck."),
    ("then, shuffle your deck.", "shuffle deck."),
    ("Shuffle the other cards back into your deck", "Shuffle the rest back"),
    ("shuffle your deck", "shuffle deck"),
    ("reveal them, and put them into your hand", "and take them"),
    ("reveal it, and put it into your hand", "and take it"),
    ("and put it into your hand", "and take it"),
    ("and put them into your hand", "and take them"),
    ("from your discard pile into your hand", "from discard to hand"),
    ("from your discard pile into your deck", "from discard to deck"),
    ("from your discard pile", "from discard"),
    ("into your hand", "to hand"),
    # === Boilerplate clauses ===
    ("If you attached Energy to a Pokémon in this way, ", "If so, "),
    ("If you attached Energy to your Active in this way, ", "If so, "),
    ("Energy card", "Energy"),
    # === Energy ===
    ("Basic Energy cards", "Basic Energy"),
    ("Basic Energy card", "Basic Energy"),
    ("Energy cards", "Energy"),
    ("Energys", "Energy"),
    # === Prize ===
    ("your opponent takes 1 fewer Prize card", "opponent takes 1 fewer Prize"),
    ("Prize card your opponent has taken", "Prize taken"),
    ("Prize cards", "Prizes"),
    ("Prize card", "Prize"),
    # === Play conditions ===
    ("You can use this card only if you discard", "Discard"),
    ("other cards from your hand", "other cards to play"),
    ("another card from your hand", "1 card to play"),
    # === Damage / effects ===
    ("(Don't apply Weakness and Resistance for Benched Pokémon.)", "(Bench damage)"),
    ("(before applying Weakness and Resistance)", ""),
    ("This attack does", "Does"),
    ("this attack does", "does"),
    ("more damage for each", "+damage per"),
    ("more damage", "extra"),
    ("has any damage counters on it", "has damage"),
    ("has no damage counters on it", "has no damage"),
    ("damage counters", "damage"),
    ("damage on it", "damage"),
    ("damage to itself", "self-damage"),
    # === Status / conditions ===
    ("is now Poisoned", "becomes Poisoned"),
    ("is now Confused", "becomes Confused"),
    ("is now Asleep", "becomes Asleep"),
    ("is now Burned", "becomes Burned"),
    ("is now Paralyzed", "becomes Paralyzed"),
    # === Misc ===
    ("Flip a coin. If heads, ", "Flip: heads, "),
    ("Look at the top", "Check top"),
    ("in order to use this Ability", "to use this"),
    ("You can't use more than 1", "Max 1"),
    ("Ability each turn", "per turn"),
    ("Ability during your turn", "per turn"),
    ("Ability on your turn", "per turn"),
    ("you may draw cards until you have", "draw up to"),
    ("cards in your hand", "cards"),
]


def compress_text(text: str) -> str:
    """Apply shorthand compression rules to card effect text."""
    for pattern, replacement in COMPRESS_RULES:
        text = text.replace(pattern, replacement)
    # Clean up double spaces
    while "  " in text:
        text = text.replace("  ", " ")
    return text.strip()


def fit_attack_header(name, damage, cost_count, head_size, card_w, margin):
    """Shrink attack name + damage font sizes until they fit without overlap.

    Returns (name_size, dmg_size).
    """
    dot_r = max(8, int(head_size * 0.5))
    cost_w = (dot_r * 2 + 4) * cost_count + 6 if cost_count else 0
    name_x = margin + cost_w + 6
    available = card_w - 2 * margin - cost_w - 12  # space for name + gap + damage

    name_size = head_size
    dmg_size = int(head_size * 1.21)
    dmg_str = str(damage) if damage else ""

    for _ in range(6):  # up to 6 shrink steps
        name_w = _measure_width(_TITLE_FACE, name, name_size)
        dmg_w = _measure_width(_TITLE_FACE, dmg_str, dmg_size) if dmg_str else 0
        gap = 20
        if name_w + gap + dmg_w <= available:
            break
        # Shrink both proportionally
        name_size = int(name_size * 0.88)
        dmg_size = int(dmg_size * 0.88)

    return name_size, dmg_size


def escape_xml(text: str) -> str:
    """Escape text for XML/SVG."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def wrap_text(text: str, max_chars: int) -> list[str]:
    """Word-wrap text to fit within max_chars per line."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines


def render_energy_dots(x: int, y: int, cost: list[str], radius: int) -> tuple[list[str], int]:
    """Render energy cost as colored circles. Returns (svg_elements, new_x)."""
    elems = []
    cx = x + radius
    cy = y - radius + 2  # vertically center with text baseline
    for energy in cost:
        c = ENERGY_COLORS.get(energy, "#888")
        elems.append(f'  <circle cx="{cx}" cy="{cy}" r="{radius}" fill="{c}" stroke="#333" stroke-width="1.5"/>')
        # White letter inside the dot
        letter = ENERGY_ABBREV.get(energy, "?")
        elems.append(f'  <text x="{cx}" y="{cy + 1}" font-family="Helvetica, Arial, sans-serif" font-size="{int(radius * 1.3)}" font-weight="bold" fill="white" text-anchor="middle" dominant-baseline="central">{letter}</text>')
        cx += radius * 2 + 4
    return elems, cx - x + 6  # total width consumed


def energy_inline_svg(text: str, font_size: int) -> str:
    """Convert {D}, {W} etc. in text to colored circle Unicode + tspan markup.
    Returns SVG tspan markup that can be placed inside a <text> element."""
    import re

    def replace_energy(m):
        letter = m.group(1)
        color = ENERGY_COLORS.get(letter, "#888")
        # Use a filled circle Unicode char, colored, with the letter after it
        return f'<tspan fill="{color}" font-size="{int(font_size * 1.1)}">&#x2B24;</tspan>'

    escaped = escape_xml(text)
    # Now replace the escaped {X} patterns — escape_xml won't touch {X}
    return re.sub(r'\{([A-Z])\}', replace_energy, escaped)


def is_fullart(card: dict) -> bool:
    """Detect if a card is a full-art variant (artwork spans the entire card)."""
    rarity = (card.get("rarity") or "").lower()
    fullart_rarities = [
        "illustration rare",
        "special illustration rare",
        "special art rare",
        "hyper rare",
        "art rare",
    ]
    if any(r in rarity for r in fullart_rarities):
        return True
    # Card number above official set count is usually a secret/full-art
    card_count = card.get("set", {}).get("cardCount", {})
    official = card_count.get("official", 999)
    local_id = card.get("localId", "0")
    try:
        if int(local_id) > official:
            return True
    except ValueError:
        pass
    return False


def generate_fullart_svg(card: dict, image_b64: str, overlay_opacity: float = 0.7,
                         font_size: int = None, max_cover: float = 0.55) -> str:
    """Generate an SVG proxy for a full-art card.

    Uses the full card image as background with a gradient overlay
    on the lower portion, then renders large readable text on top.
    overlay_opacity: max darkness of the text background (0.0–1.0).
    font_size: force body font size in px (None = auto-select 36 or 30).
    max_cover: max fraction of card the overlay can cover (0.0–1.0).
    """
    name = escape_xml(card.get("name", "Unknown"))
    hp = card.get("hp", "")
    types = card.get("types", [])
    stage = card.get("stage", "")
    card_type = types[0] if types else "Colorless"
    color = TYPE_COLORS.get(card_type, "#888888")
    retreat = card.get("retreat", 0)
    abilities = card.get("abilities", [])
    attacks = card.get("attacks", [])
    set_name = card.get("set", {}).get("name", "")
    local_id = card.get("localId", "")
    category = card.get("category", "Pokemon")
    trainer_type = card.get("trainerType", "")
    trainer_effect = compress_text(card.get("effect", ""))
    abilities = [
        {**ab, "effect": compress_text(ab.get("effect", ""))}
        for ab in abilities
    ]
    attacks = [
        {**atk, "effect": compress_text(atk.get("effect", ""))}
        for atk in attacks
    ]

    if category == "Trainer":
        if trainer_type == "Supporter":
            color = "#C04010"
        elif trainer_type == "Stadium":
            color = "#1A7A3A"
        else:
            color = "#1860A0"

    FONT_TITLE = "'Arial Black', 'Helvetica Neue', Impact, Arial, sans-serif"
    FONT_BODY = "'Helvetica Neue', 'Arial Black', Arial, Helvetica, sans-serif"
    MARGIN = 30
    text_max_w = CARD_W - 2 * MARGIN

    # Measure text to determine how much overlay we need
    has_text = bool(
        (category == "Trainer" and trainer_effect)
        or abilities or attacks
    )

    HEAD_RATIO = 28 / 24
    text_pad = 50
    footer_h = 80
    half_card = int(CARD_H * 0.50)

    # Try large (36) first, drop to medium (30) if overlay would cover >50% of card
    BODY_LARGE, BODY_MEDIUM = 36, 30
    if font_size is not None:
        # Forced font size — skip auto-selection
        BODY_SIZE = font_size
        if has_text:
            head_candidate = int(BODY_SIZE * HEAD_RATIO)
            text_h = ft_content_height(
                BODY_SIZE, head_candidate, text_max_w,
                category, trainer_effect, abilities, attacks)
            text_block_h = text_h + text_pad + footer_h
            overlay_top = CARD_H - text_block_h - 40
        else:
            text_h = 0
            overlay_top = CARD_H - footer_h - 40
    elif has_text:
        for body_candidate in [BODY_LARGE, BODY_MEDIUM]:
            head_candidate = int(body_candidate * HEAD_RATIO)
            text_h = ft_content_height(
                body_candidate, head_candidate, text_max_w,
                category, trainer_effect, abilities, attacks)
            text_block_h = text_h + text_pad + footer_h
            overlay_top = CARD_H - text_block_h - 40
            if overlay_top >= half_card:
                break  # fits in bottom half
        BODY_SIZE = body_candidate
    else:
        text_h = 0
        BODY_SIZE = BODY_LARGE
        overlay_top = CARD_H - footer_h - 40

    HEAD_SIZE = int(BODY_SIZE * HEAD_RATIO)
    LINE_H = int(BODY_SIZE * 1.25)

    # Compute final overlay position
    if has_text:
        text_block_h = text_h + text_pad + footer_h
        overlay_top = CARD_H - text_block_h - 40
    overlay_top = max(overlay_top, int(CARD_H * (1.0 - max_cover)))

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {CARD_W} {CARD_H}" width="{CARD_W}" height="{CARD_H}">')
    lines.append("  <defs>")
    # Gradient overlay: transparent at top, quickly ramps to near-opaque
    lines.append('    <linearGradient id="overlay-grad" x1="0" y1="0" x2="0" y2="1">')
    lines.append(f'      <stop offset="0%" stop-color="#000" stop-opacity="0"/>')
    lines.append(f'      <stop offset="15%" stop-color="#000" stop-opacity="{overlay_opacity * 0.6:.2f}"/>')
    lines.append(f'      <stop offset="40%" stop-color="#000" stop-opacity="{overlay_opacity * 0.85:.2f}"/>')
    lines.append(f'      <stop offset="100%" stop-color="#000" stop-opacity="{overlay_opacity:.2f}"/>')
    lines.append('    </linearGradient>')
    # Header gradient: dark at top, transparent at bottom
    lines.append('    <linearGradient id="header-grad" x1="0" y1="0" x2="0" y2="1">')
    lines.append(f'      <stop offset="0%" stop-color="#000" stop-opacity="0.7"/>')
    lines.append(f'      <stop offset="100%" stop-color="#000" stop-opacity="0"/>')
    lines.append('    </linearGradient>')
    # Text shadow filter
    lines.append('    <filter id="shadow" x="-2%" y="-2%" width="104%" height="104%">')
    lines.append('      <feDropShadow dx="1" dy="1" stdDeviation="1.5" flood-color="#000" flood-opacity="0.7"/>')
    lines.append("    </filter>")
    lines.append('    <filter id="shadow-title" x="-2%" y="-5%" width="104%" height="110%">')
    lines.append('      <feDropShadow dx="2" dy="2" stdDeviation="2" flood-color="#000" flood-opacity="0.8"/>')
    lines.append("    </filter>")
    # Clip path for rounded corners
    lines.append(f'    <clipPath id="card-clip"><rect width="{CARD_W}" height="{CARD_H}" rx="25" ry="25"/></clipPath>')
    lines.append("  </defs>")

    # Full card image as background
    lines.append(f'  <g clip-path="url(#card-clip)">')
    lines.append(f'    <image x="0" y="0" width="{CARD_W}" height="{CARD_H}" preserveAspectRatio="xMidYMid slice"')
    lines.append(f'           href="data:image/png;base64,{image_b64}"/>')

    # Bottom gradient overlay for text (no header overlay — keep the card's own header)
    overlay_h = CARD_H - overlay_top
    lines.append(f'    <rect x="0" y="{overlay_top}" width="{CARD_W}" height="{overlay_h}" fill="url(#overlay-grad)"/>')
    lines.append(f'  </g>')

    # Solid black footer strip — fully opaque, covers the card's own copyright/illustrator text
    footer_strip_h = 50
    lines.append(f'  <rect x="0" y="{CARD_H - footer_strip_h}" width="{CARD_W}" height="{footer_strip_h}" rx="0" fill="#000" clip-path="url(#card-clip)"/>')

    # Card border
    lines.append(f'  <rect width="{CARD_W}" height="{CARD_H}" rx="25" ry="25" fill="none" stroke="{color}" stroke-width="4"/>')

    # Text content starts below the overlay top + padding
    y = overlay_top + text_pad + int(BODY_SIZE * 0.5)

    # Trainer effect text
    if category == "Trainer" and trainer_effect:
        wrapped = ft_wrap(_BODY_FACE, trainer_effect, BODY_SIZE, text_max_w)
        for wline in wrapped:
            y += LINE_H
            markup = energy_inline_svg(wline, BODY_SIZE)
            lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="white" filter="url(#shadow)">{markup}</text>')
        y += int(BODY_SIZE * 0.83)

    # Abilities
    for ab in abilities:
        ab_type = ab.get("type", "Ability")
        ab_name = escape_xml(ab.get("name", ""))
        ab_effect = ab.get("effect", "")

        # Colored bar behind ability name — opaque enough to read on any artwork
        bar_h = int(HEAD_SIZE * 1.5)
        lines.append(f'  <rect x="20" y="{y - int(HEAD_SIZE * 1.07)}" width="{CARD_W - 40}" height="{bar_h}" rx="5" fill="{color}" opacity="0.7"/>')
        lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_TITLE}" font-size="{HEAD_SIZE}" font-weight="900" fill="white" filter="url(#shadow)">{escape_xml(ab_type)}: {ab_name}</text>')
        y += int(HEAD_SIZE * 0.5)

        wrapped = ft_wrap(_BODY_FACE, ab_effect, BODY_SIZE, text_max_w)
        for wline in wrapped:
            y += LINE_H
            markup = energy_inline_svg(wline, BODY_SIZE)
            lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="white" filter="url(#shadow)">{markup}</text>')
        y += int(BODY_SIZE * 1.46)

    # Attacks
    for atk in attacks:
        atk_cost = atk.get("cost", [])
        atk_name = escape_xml(atk.get("name", ""))
        damage = atk.get("damage", "")
        effect = atk.get("effect", "")

        bar_h = int(HEAD_SIZE * 1.57)
        lines.append(f'  <rect x="20" y="{y - int(HEAD_SIZE * 1.0)}" width="{CARD_W - 40}" height="{bar_h}" rx="5" fill="white" opacity="0.1"/>')

        dot_r = max(8, int(HEAD_SIZE * 0.5))
        dot_x = MARGIN
        if atk_cost:
            dot_elems, dot_w = render_energy_dots(MARGIN, y + 2, atk_cost, dot_r)
            lines.extend(dot_elems)
            dot_x = MARGIN + dot_w + 6

        atk_name_size, atk_dmg_size = fit_attack_header(atk_name, damage, len(atk_cost), HEAD_SIZE, CARD_W, MARGIN)
        lines.append(f'  <text x="{dot_x}" y="{y + 2}" font-family="{FONT_TITLE}" font-size="{atk_name_size}" font-weight="900" fill="white" filter="url(#shadow)">{atk_name}</text>')
        if damage:
            lines.append(f'  <text x="{CARD_W - MARGIN}" y="{y + 2}" font-family="{FONT_TITLE}" font-size="{atk_dmg_size}" font-weight="900" fill="#FF6644" text-anchor="end" filter="url(#shadow)">{escape_xml(str(damage))}</text>')
        y += int(HEAD_SIZE * 0.64)

        if effect:
            wrapped = ft_wrap(_BODY_FACE, effect, BODY_SIZE, text_max_w)
            for wline in wrapped:
                y += LINE_H
                markup = energy_inline_svg(wline, BODY_SIZE)
                lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="white" filter="url(#shadow)">{markup}</text>')
        y += int(BODY_SIZE * 1.25)

    # Footer
    footer_y = CARD_H - 55
    weakness = card.get("weaknesses")
    resistance = card.get("resistances")
    has_footer = weakness or resistance or retreat

    if has_footer:
        lines.append(f'  <line x1="20" y1="{footer_y - 18}" x2="{CARD_W - 20}" y2="{footer_y - 18}" stroke="rgba(255,255,255,0.3)" stroke-width="1"/>')

    footer_x = MARGIN
    if weakness:
        for w in weakness:
            wtype = w.get("type", "")
            wval = w.get("value", "")
            lines.append(f'  <text x="{footer_x}" y="{footer_y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="rgba(255,255,255,0.9)" filter="url(#shadow)">Weak:</text>')
            footer_x += BODY_SIZE * 3.8
            wcolor = ENERGY_COLORS.get(wtype, "#888")
            dot_r = int(BODY_SIZE * 0.45)
            dot_cy = footer_y - dot_r + 2
            lines.append(f'  <circle cx="{int(footer_x + dot_r)}" cy="{dot_cy}" r="{dot_r}" fill="{wcolor}" stroke="#333" stroke-width="1.5"/>')
            footer_x += dot_r * 2 + 6
            lines.append(f'  <text x="{int(footer_x)}" y="{footer_y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="rgba(255,255,255,0.9)" filter="url(#shadow)">{escape_xml(wval)}</text>')
            footer_x += BODY_SIZE * 2.5

    if resistance:
        for r in resistance:
            rtype = r.get("type", "")
            rval = r.get("value", "")
            lines.append(f'  <text x="{int(footer_x)}" y="{footer_y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="rgba(255,255,255,0.9)" filter="url(#shadow)">Resist:</text>')
            footer_x += BODY_SIZE * 4.5
            rcolor = ENERGY_COLORS.get(rtype, "#888")
            dot_r = int(BODY_SIZE * 0.45)
            dot_cy = footer_y - dot_r + 2
            lines.append(f'  <circle cx="{int(footer_x + dot_r)}" cy="{dot_cy}" r="{dot_r}" fill="{rcolor}" stroke="#333" stroke-width="1.5"/>')
            footer_x += dot_r * 2 + 6
            lines.append(f'  <text x="{int(footer_x)}" y="{footer_y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="rgba(255,255,255,0.9)" filter="url(#shadow)">{escape_xml(rval)}</text>')
            footer_x += BODY_SIZE * 2.5

    if retreat:
        lines.append(f'  <text x="{int(footer_x)}" y="{footer_y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="rgba(255,255,255,0.9)" filter="url(#shadow)">Retreat: {retreat}</text>')

    # Set info
    lines.append(f'  <text x="{CARD_W // 2}" y="{CARD_H - 18}" font-family="{FONT_BODY}" font-size="18" font-weight="600" fill="rgba(255,255,255,0.5)" text-anchor="middle">{escape_xml(set_name)} {escape_xml(local_id)}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def generate_svg(card: dict, artwork_b64: str) -> str:
    """Generate an SVG proxy card with large readable text."""
    name = escape_xml(card.get("name", "Unknown"))
    hp = card.get("hp", "")
    types = card.get("types", [])
    stage = card.get("stage", "")
    card_type = types[0] if types else "Colorless"
    color = TYPE_COLORS.get(card_type, "#888888")
    retreat = card.get("retreat", 0)
    abilities = card.get("abilities", [])
    attacks = card.get("attacks", [])
    set_name = card.get("set", {}).get("name", "")
    local_id = card.get("localId", "")
    category = card.get("category", "Pokemon")
    trainer_type = card.get("trainerType", "")
    trainer_effect = compress_text(card.get("effect", ""))
    abilities = [
        {**ab, "effect": compress_text(ab.get("effect", ""))}
        for ab in abilities
    ]
    attacks = [
        {**atk, "effect": compress_text(atk.get("effect", ""))}
        for atk in attacks
    ]

    # Trainer cards get a distinct color
    if category == "Trainer":
        if trainer_type == "Supporter":
            color = "#C04010"
        elif trainer_type == "Stadium":
            color = "#1A7A3A"
        else:
            color = "#1860A0"  # Item / Tool

    # Darker shade for header
    # We'll just use the type color with opacity

    lines = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CARD_W} {CARD_H}" width="{CARD_W}" height="{CARD_H}">')
    # Font stacks: heavy for titles, semi-bold for body
    # Use single quotes inside so we can wrap in double quotes in the XML attribute
    FONT_TITLE = "'Arial Black', 'Helvetica Neue', Impact, Arial, sans-serif"
    FONT_BODY = "'Helvetica Neue', 'Arial Black', Arial, Helvetica, sans-serif"

    lines.append("  <defs>")
    lines.append(f'    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">')
    lines.append(f'      <stop offset="0%" stop-color="{color}" stop-opacity="0.3"/>')
    lines.append(f'      <stop offset="100%" stop-color="{color}" stop-opacity="0.1"/>')
    lines.append(f"    </linearGradient>")
    # Drop shadow filter for body text
    lines.append('    <filter id="shadow" x="-2%" y="-2%" width="104%" height="104%">')
    lines.append('      <feDropShadow dx="1" dy="1" stdDeviation="0.8" flood-color="#000" flood-opacity="0.35"/>')
    lines.append("    </filter>")
    # Heavier shadow for title text
    lines.append('    <filter id="shadow-title" x="-2%" y="-5%" width="104%" height="110%">')
    lines.append('      <feDropShadow dx="1.5" dy="2" stdDeviation="1" flood-color="#000" flood-opacity="0.5"/>')
    lines.append("    </filter>")
    # Black-white-black sandwich outline for trainer type tag
    lines.append('    <filter id="tag-outline" x="-8%" y="-20%" width="116%" height="140%">')
    lines.append('      <feMorphology in="SourceAlpha" operator="dilate" radius="4" result="outer"/>')
    lines.append('      <feFlood flood-color="#000" flood-opacity="0.8" result="black"/>')
    lines.append('      <feComposite in="black" in2="outer" operator="in" result="outer-stroke"/>')
    lines.append('      <feMorphology in="SourceAlpha" operator="dilate" radius="2" result="inner"/>')
    lines.append('      <feFlood flood-color="white" flood-opacity="0.95" result="white"/>')
    lines.append('      <feComposite in="white" in2="inner" operator="in" result="inner-stroke"/>')
    lines.append('      <feMerge>')
    lines.append('        <feMergeNode in="outer-stroke"/>')
    lines.append('        <feMergeNode in="inner-stroke"/>')
    lines.append('        <feMergeNode in="SourceGraphic"/>')
    lines.append('      </feMerge>')
    lines.append("    </filter>")
    lines.append("  </defs>")

    # Card background — solid white base so transparent areas don't bleed through
    lines.append(f'  <rect width="{CARD_W}" height="{CARD_H}" rx="25" ry="25" fill="white"/>')
    lines.append(f'  <rect width="{CARD_W}" height="{CARD_H}" rx="25" ry="25" fill="url(#bg)" stroke="{color}" stroke-width="4"/>')

    # Header bar
    lines.append(f'  <rect x="0" y="0" width="{CARD_W}" height="80" rx="25" ry="25" fill="{color}" opacity="0.85"/>')
    lines.append(f'  <rect x="0" y="40" width="{CARD_W}" height="40" fill="{color}" opacity="0.85"/>')

    # Name and HP / trainer type in header
    lines.append(f'  <text x="30" y="57" font-family="{FONT_TITLE}" font-size="42" font-weight="900" fill="white" filter="url(#shadow-title)">{name}</text>')
    if category == "Trainer":
        # Trainer type icon in header
        icon_size = 40
        icon_x = CARD_W - 30 - icon_size
        icon_y = 20
        icon_colors = {"Supporter": "#FFD040", "Stadium": "#50E878", "Item": "#60C8FF", "Tool": "#60C8FF"}
        icon_fill = icon_colors.get(trainer_type, "#FFD040")
        if trainer_type == "Supporter":
            # Person silhouette
            lines.append(f'  <g transform="translate({icon_x},{icon_y})" filter="url(#tag-outline)">')
            lines.append(f'    <circle cx="{icon_size//2}" cy="{int(icon_size*0.28)}" r="{int(icon_size*0.22)}" fill="{icon_fill}"/>')
            lines.append(f'    <path d="M{int(icon_size*0.15)},{icon_size} Q{int(icon_size*0.15)},{int(icon_size*0.45)} {icon_size//2},{int(icon_size*0.42)} Q{int(icon_size*0.85)},{int(icon_size*0.45)} {int(icon_size*0.85)},{icon_size} Z" fill="{icon_fill}"/>')
            lines.append(f'  </g>')
        elif trainer_type in ("Item", "Tool"):
            # Pokeball icon
            r = icon_size // 2
            cx = icon_x + r
            cy = icon_y + r
            lines.append(f'  <g filter="url(#tag-outline)">')
            lines.append(f'    <circle cx="{cx}" cy="{cy}" r="{r}" fill="{icon_fill}" stroke="white" stroke-width="2"/>')
            lines.append(f'    <rect x="{cx - r}" y="{cy - 2}" width="{icon_size}" height="4" fill="white"/>')
            lines.append(f'    <circle cx="{cx}" cy="{cy}" r="{int(r*0.3)}" fill="white" stroke="{icon_fill}" stroke-width="2"/>')
            lines.append(f'  </g>')
        elif trainer_type == "Stadium":
            # Stadium icon — simple building/columns silhouette
            sx = icon_x
            sy = icon_y
            s = icon_size
            lines.append(f'  <g filter="url(#tag-outline)">')
            # Roof / pediment triangle
            lines.append(f'    <polygon points="{sx},{sy + int(s*0.4)} {sx + s//2},{sy + int(s*0.08)} {sx + s},{sy + int(s*0.4)}" fill="{icon_fill}"/>')
            # Base platform
            lines.append(f'    <rect x="{sx + int(s*0.05)}" y="{sy + int(s*0.82)}" width="{int(s*0.9)}" height="{int(s*0.12)}" rx="2" fill="{icon_fill}"/>')
            # Three columns
            cw = int(s * 0.12)
            ch = int(s * 0.44)
            ctop = sy + int(s * 0.38)
            for col_x in [sx + int(s*0.15), sx + s//2 - cw//2, sx + int(s*0.85) - cw]:
                lines.append(f'    <rect x="{col_x}" y="{ctop}" width="{cw}" height="{ch}" rx="1" fill="{icon_fill}"/>')
            lines.append(f'  </g>')
        else:
            # Fallback: text label
            tag = escape_xml(trainer_type).upper() if trainer_type else "TRAINER"
            lines.append(f'  <text x="{CARD_W - 30}" y="57" font-family="{FONT_TITLE}" font-size="30" font-weight="900" fill="{icon_fill}" text-anchor="end" filter="url(#tag-outline)">{tag}</text>')
    elif hp:
        lines.append(f'  <text x="{CARD_W - 30}" y="57" font-family="{FONT_TITLE}" font-size="38" font-weight="900" fill="white" text-anchor="end" filter="url(#shadow-title)">{hp} HP</text>')

    # Subtitle line — Pokémon only (trainers put their type in the header)
    if category == "Trainer":
        art_y = 85  # no subtitle → artwork moves up
    else:
        stage_line = f"{stage} {category}" if stage else category
        type_str = " / ".join(types)
        subtitle = f"{stage_line} — {type_str}" if type_str else stage_line
        lines.append(f'  <text x="30" y="105" font-family="{FONT_BODY}" font-size="22" font-weight="700" fill="#444" filter="url(#shadow)">{escape_xml(subtitle)}</text>')
        art_y = 118  # after subtitle

    # Artwork — full width, height determined by text needs
    art_x = 20
    art_w = CARD_W - 40  # 710
    ART_H_MAX = int(art_w / 1.59)  # ~447
    ART_H_MIN = 200
    ART_PAD = 40  # padding between art and text
    MARGIN = 30
    content_bottom = CARD_H - 90  # leave room for footer + set info
    text_max_w = CARD_W - 2 * MARGIN  # 690px usable for text

    # --- FreeType-measured three-tier layout ---
    # Tiers: Large (40) → Medium (34) → Small (28)
    # Drop a tier when art would shrink below ART_PREFER; binary-search
    # between adjacent tiers for the largest body that keeps art >= ART_PREFER.
    has_text = bool(
        (category == "Trainer" and trainer_effect)
        or abilities or attacks
    )
    HEAD_RATIO = 28 / 24
    BODY_LARGE, BODY_MEDIUM, BODY_SMALL = 40, 34, 28
    ART_PREFER = 300  # minimum preferred art height before dropping a tier

    def _measure(body):
        return ft_content_height(
            body, int(body * HEAD_RATIO), text_max_w,
            category, trainer_effect, abilities, attacks)

    def _best_in_range(lo_body, hi_body):
        """Binary-search for largest body in [lo_body, hi_body] with art >= ART_PREFER."""
        lo, hi = float(lo_body), float(hi_body)
        for _ in range(12):
            mid = (lo + hi) / 2
            if _measure(int(mid)) <= space - ART_PREFER:
                lo = mid
            else:
                hi = mid
        size = int(lo)
        th = _measure(size)
        return size, th, max(ART_H_MIN, min(ART_H_MAX, space - th))

    if has_text:
        text_h_large = _measure(BODY_LARGE)
        space = content_bottom - art_y - ART_PAD

        if text_h_large <= space - ART_H_MAX:
            # Large fits with full art
            BODY_SIZE = BODY_LARGE
            text_h = text_h_large
            art_h = min(ART_H_MAX, space - text_h)
        elif text_h_large <= space - ART_PREFER:
            # Large tier can keep art >= ART_PREFER — binary-search Large→Medium
            BODY_SIZE, text_h, art_h = _best_in_range(BODY_MEDIUM, BODY_LARGE)
        elif _measure(BODY_MEDIUM) <= space - ART_PREFER:
            # Medium tier keeps art >= ART_PREFER — binary-search Medium→Large
            BODY_SIZE, text_h, art_h = _best_in_range(BODY_MEDIUM, BODY_LARGE)
        elif _measure(BODY_SMALL) <= space - ART_PREFER:
            # Small tier keeps art >= ART_PREFER — binary-search Small→Medium
            BODY_SIZE, text_h, art_h = _best_in_range(BODY_SMALL, BODY_MEDIUM)
        elif _measure(BODY_SMALL) <= space - ART_H_MIN:
            # Small fits with min art — use Small
            BODY_SIZE = BODY_SMALL
            text_h = _measure(BODY_SIZE)
            art_h = max(ART_H_MIN, min(ART_H_MAX, space - text_h))
        else:
            # Even Small doesn't fit with min art — keep Small, crop art
            BODY_SIZE = BODY_SMALL
            text_h = _measure(BODY_SIZE)
            art_h = max(ART_H_MIN, space - text_h)

        HEAD_SIZE = int(BODY_SIZE * HEAD_RATIO)
        LINE_H = int(BODY_SIZE * 1.25)
    else:
        art_h = ART_H_MAX
        BODY_SIZE, HEAD_SIZE, LINE_H = BODY_LARGE, int(BODY_LARGE * HEAD_RATIO), int(BODY_LARGE * 1.25)

    lines.append(f'  <rect x="{art_x}" y="{art_y}" width="{art_w}" height="{art_h}" rx="10" fill="#000" opacity="0.05"/>')
    lines.append(f'  <image x="{art_x}" y="{art_y}" width="{art_w}" height="{art_h}" preserveAspectRatio="xMidYMid slice"')
    lines.append(f'         href="data:image/png;base64,{artwork_b64}" clip-path="inset(0 round 10px)"/>')

    content_top = art_y + art_h + ART_PAD
    y = content_top

    # Trainer effect text
    if category == "Trainer" and trainer_effect:
        wrapped = ft_wrap(_BODY_FACE, trainer_effect, BODY_SIZE, text_max_w)
        for wline in wrapped:
            y += LINE_H
            markup = energy_inline_svg(wline, BODY_SIZE)
            lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#222" filter="url(#shadow)">{markup}</text>')
        y += int(BODY_SIZE * 0.83)

    # Abilities
    for ab in abilities:
        ab_type = ab.get("type", "Ability")
        ab_name = escape_xml(ab.get("name", ""))
        ab_effect = ab.get("effect", "")

        bar_h = int(HEAD_SIZE * 1.5)
        lines.append(f'  <rect x="20" y="{y - int(HEAD_SIZE * 1.07)}" width="{CARD_W - 40}" height="{bar_h}" rx="5" fill="{color}" opacity="0.25"/>')
        lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_TITLE}" font-size="{HEAD_SIZE}" font-weight="900" fill="{color}" filter="url(#shadow)">{escape_xml(ab_type)}: {ab_name}</text>')
        y += int(HEAD_SIZE * 0.5)

        wrapped = ft_wrap(_BODY_FACE, ab_effect, BODY_SIZE, text_max_w)
        for wline in wrapped:
            y += LINE_H
            markup = energy_inline_svg(wline, BODY_SIZE)
            lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#222" filter="url(#shadow)">{markup}</text>')
        y += int(BODY_SIZE * 1.46)

    # Attacks
    for atk in attacks:
        atk_cost = atk.get("cost", [])
        atk_name = escape_xml(atk.get("name", ""))
        damage = atk.get("damage", "")
        effect = atk.get("effect", "")

        # Attack header bar
        bar_h = int(HEAD_SIZE * 1.57)
        lines.append(f'  <rect x="20" y="{y - int(HEAD_SIZE * 1.0)}" width="{CARD_W - 40}" height="{bar_h}" rx="5" fill="#333" opacity="0.1"/>')

        # Energy dots then attack name
        dot_r = max(8, int(HEAD_SIZE * 0.5))
        dot_x = MARGIN
        if atk_cost:
            dot_elems, dot_w = render_energy_dots(MARGIN, y + 2, atk_cost, dot_r)
            lines.extend(dot_elems)
            dot_x = MARGIN + dot_w + 6

        atk_name_size, atk_dmg_size = fit_attack_header(atk_name, damage, len(atk_cost), HEAD_SIZE, CARD_W, MARGIN)
        lines.append(f'  <text x="{dot_x}" y="{y + 2}" font-family="{FONT_TITLE}" font-size="{atk_name_size}" font-weight="900" fill="#222" filter="url(#shadow)">{atk_name}</text>')
        if damage:
            lines.append(f'  <text x="{CARD_W - MARGIN}" y="{y + 2}" font-family="{FONT_TITLE}" font-size="{atk_dmg_size}" font-weight="900" fill="#c00" text-anchor="end" filter="url(#shadow)">{escape_xml(str(damage))}</text>')
        y += int(HEAD_SIZE * 0.64)

        if effect:
            wrapped = ft_wrap(_BODY_FACE, effect, BODY_SIZE, text_max_w)
            for wline in wrapped:
                y += LINE_H
                markup = energy_inline_svg(wline, BODY_SIZE)
                lines.append(f'  <text x="{MARGIN}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#222" filter="url(#shadow)">{markup}</text>')
        y += int(BODY_SIZE * 1.25)

    # Footer: weakness, resistance, retreat — anchored to bottom
    weakness = card.get("weaknesses")
    resistance = card.get("resistances")
    has_footer = weakness or resistance or retreat
    footer_y = CARD_H - 60

    if has_footer:
        lines.append(f'  <line x1="20" y1="{footer_y - 20}" x2="{CARD_W - 20}" y2="{footer_y - 20}" stroke="#ccc" stroke-width="1"/>')

    footer_x = MARGIN
    y = footer_y  # reuse y for footer positioning

    if weakness:
        for w in weakness:
            wtype = w.get("type", "")
            wval = w.get("value", "")
            lines.append(f'  <text x="{footer_x}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#444" filter="url(#shadow)">Weak:</text>')
            footer_x += BODY_SIZE * 3.8
            wcolor = ENERGY_COLORS.get(wtype, "#888")
            dot_r = int(BODY_SIZE * 0.45)
            dot_cy = y - dot_r + 2
            lines.append(f'  <circle cx="{int(footer_x + dot_r)}" cy="{dot_cy}" r="{dot_r}" fill="{wcolor}" stroke="#333" stroke-width="1.5"/>')
            footer_x += dot_r * 2 + 6
            lines.append(f'  <text x="{int(footer_x)}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#444" filter="url(#shadow)">{escape_xml(wval)}</text>')
            footer_x += BODY_SIZE * 2.5

    if resistance:
        for r in resistance:
            rtype = r.get("type", "")
            rval = r.get("value", "")
            lines.append(f'  <text x="{int(footer_x)}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#444" filter="url(#shadow)">Resist:</text>')
            footer_x += BODY_SIZE * 4.5
            rcolor = ENERGY_COLORS.get(rtype, "#888")
            dot_r = int(BODY_SIZE * 0.45)
            dot_cy = y - dot_r + 2
            lines.append(f'  <circle cx="{int(footer_x + dot_r)}" cy="{dot_cy}" r="{dot_r}" fill="{rcolor}" stroke="#333" stroke-width="1.5"/>')
            footer_x += dot_r * 2 + 6
            lines.append(f'  <text x="{int(footer_x)}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#444" filter="url(#shadow)">{escape_xml(rval)}</text>')
            footer_x += BODY_SIZE * 2.5

    if retreat:
        lines.append(f'  <text x="{int(footer_x)}" y="{y}" font-family="{FONT_BODY}" font-size="{BODY_SIZE}" font-weight="700" fill="#444" filter="url(#shadow)">Retreat: {retreat}</text>')

    # Set info — anchor to bottom of card
    lines.append(f'  <text x="{CARD_W // 2}" y="{CARD_H - 20}" font-family="{FONT_BODY}" font-size="18" font-weight="600" fill="#888" text-anchor="middle">{escape_xml(set_name)} {escape_xml(local_id)}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def parse_decklist(path: str) -> list[tuple[int, str, str, str, dict]]:
    """Parse a decklist file. Returns list of (count, set_code, number, comment, overrides).

    Supports two formats:
      COUNT SET NUM        # old format: 3 SFA 36
      SET NUM xCOUNT       # new format: SFA 36 x3

    Per-card overrides can be added as key=value tokens:
      BBT 169 x1 overlay=0.4 font=28  # Genesect ex SIR

    Supported overrides:
      overlay=N   Full-art overlay opacity (0.0–1.0)
      font=N      Force body font size in px
      max_cover=N Max fraction of card the overlay can cover (0.0–1.0)
    """
    entries = []
    seen = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip inline comment
            comment = ""
            if "#" in line:
                line, comment = line.split("#", 1)
                comment = comment.strip()
                line = line.strip()

            parts = line.split()
            if len(parts) < 2:
                print(f"  Skipping malformed line: {line}")
                continue

            # Extract key=value overrides from parts
            overrides = {}
            remaining = []
            for p in parts:
                if "=" in p and not p.startswith("="):
                    k, v = p.split("=", 1)
                    try:
                        overrides[k] = float(v)
                    except ValueError:
                        overrides[k] = v
                else:
                    remaining.append(p)
            parts = remaining

            # Detect format: does it start with a number or a set code?
            if parts[0].isdigit():
                # Old format: COUNT SET NUM
                count = int(parts[0])
                set_code = parts[1]
                number = parts[2]
            else:
                # New format: SET NUM xCOUNT
                set_code = parts[0]
                number = parts[1]
                count = 1
                if len(parts) >= 3 and parts[2].lower().startswith("x"):
                    try:
                        count = int(parts[2][1:])
                    except ValueError:
                        pass

            key = (set_code, number)
            if key not in seen:
                seen.add(key)
                entries.append((count, set_code, number, comment, overrides))
    return entries


def generate_print_html(cards: list[tuple[int, str]], output_dir: Path, out_name: str = "print.html"):
    """Generate a printable HTML file with all proxy cards tiled for letter paper.

    Args:
        cards: list of (count, svg_content) tuples
        output_dir: directory to write print.html into
    """
    html_parts = []
    html_parts.append("""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PokeProxy - Print Sheet</title>
<style>
  @page { size: letter; margin: 0.25in; }
  body { margin: 0; padding: 0.25in; }
  .card-grid {
    display: flex;
    flex-wrap: wrap;
    align-content: flex-start;
  }
  .card {
    width: 2.5in;
    height: 3.5in;
    page-break-inside: avoid;
    overflow: hidden;
  }
  .card svg {
    width: 100%;
    height: 100%;
  }
  @media print {
    body { padding: 0; }
  }
</style>
</head>
<body>
<div class="card-grid">
""")

    for count, svg_content in cards:
        # Strip the <?xml ...?> declaration if present
        svg_clean = re.sub(r'<\?xml[^?]*\?>\s*', '', svg_content)
        for _ in range(count):
            html_parts.append(f'<div class="card">{svg_clean}</div>\n')

    html_parts.append("""</div>
</body>
</html>
""")

    out_path = output_dir / out_name
    out_path.write_text("".join(html_parts))
    return out_path


def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print("""Usage: pokeproxy.py [OPTIONS] [DECKLIST]

Generate printable Pokemon TCG proxy cards from a decklist.

Arguments:
  DECKLIST          Path to decklist file (default: decklist.txt)

Options:
  --no-dupes        Print one copy of each card regardless of decklist count
  --overlay N       Full-art overlay opacity, 0.0–1.0 (default: 0.7)
  --font N          Full-art body font size in px (default: auto 36/30)
  --max-cover N     Max fraction of card the overlay can cover (default: 0.55)
  -h, --help        Show this help message

Output:
  output/*.svg      Individual SVG proxy cards
  output/print.html Printable sheet (2x3 grid, letter size)

Decklist format:
  SFA 36 x3         Set code, card number, optional count
  3 SFA 36          Count, set code, card number (alt format)
  # comment         Lines starting with # are ignored

Per-card overrides (on the same line, before the # comment):
  overlay=0.4       Full-art overlay opacity (0.0–1.0)
  font=28           Force body font size in px
  max_cover=0.6     Max fraction of card the overlay can cover""")
        sys.exit(0)

    no_dupes = "--no-dupes" in args
    # Parse --key value flags
    defaults = {"overlay": 0.7, "font": None, "max_cover": 0.55}
    flag_map = {"--overlay": "overlay", "--font": "font", "--max-cover": "max_cover"}
    positional = []
    i = 0
    while i < len(args):
        if args[i] in flag_map and i + 1 < len(args):
            key = flag_map[args[i]]
            defaults[key] = float(args[i + 1])
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            positional.append(args[i])
            i += 1
    overlay_opacity = defaults["overlay"]
    default_font = defaults["font"]
    if default_font is not None:
        default_font = int(default_font)
    default_max_cover = defaults["max_cover"]
    args = positional

    decklist_path = args[0] if args else "decklist.txt"
    if not os.path.exists(decklist_path):
        print(f"Decklist not found: {decklist_path}")
        sys.exit(1)

    entries = parse_decklist(decklist_path)
    if not entries:
        print("No cards found in decklist.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    print_cards = []  # (count, svg_content) for print.html
    for count, set_code, number, comment, overrides in entries:
        label = comment or f"{set_code} {number}"
        print(f"Processing {count}x {label}...")
        if overrides:
            print(f"  Overrides: {overrides}")

        try:
            card = fetch_card(set_code, number)
            image_data = fetch_image(card["image"], card["id"])
            if is_fullart(card):
                print(f"  Full-art detected ({card.get('rarity', 'unknown')})")
                image_b64 = base64.b64encode(image_data).decode()
                card_overlay = overrides.get("overlay", overlay_opacity)
                card_font = overrides.get("font", default_font)
                if card_font is not None:
                    card_font = int(card_font)
                card_max_cover = overrides.get("max_cover", default_max_cover)
                svg = generate_fullart_svg(card, image_b64, card_overlay, card_font, card_max_cover)
            else:
                artwork_b64 = crop_artwork(image_data)
                svg = generate_svg(card, artwork_b64)

            out_file = OUTPUT_DIR / f"{card['id']}.svg"
            out_file.write_text(svg)
            print(f"  -> {out_file}")
            print_cards.append((1 if no_dupes else count, svg))
            generated += 1
        except Exception as e:
            print(f"  ERROR: {e} — skipping")

    if print_cards:
        out_name = Path(decklist_path).with_suffix(".html").name
        html_path = generate_print_html(print_cards, OUTPUT_DIR, out_name)
        print(f"\nPrint sheet: {html_path}")

    print(f"Done! Generated {generated}/{len(entries)} proxy card(s) in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
