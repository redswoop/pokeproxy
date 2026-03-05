#!/usr/bin/env python3
"""Inpaint text from Pokemon full-art cards using LaMa."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from simple_lama_inpainting import SimpleLama

CACHE_DIR = Path(__file__).parent / "cache"
OUTPUT_DIR = Path(__file__).parent / "output"


def make_text_mask(width, height, card_type="trainer_supporter"):
    """Generate a binary mask (white = inpaint) for known text regions on a full-art card.

    Coordinates are proportional to handle different image resolutions.
    Masks are slightly feathered at edges for smoother inpainting.
    """
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    if card_type == "trainer_supporter":
        # Full-art trainer/supporter layout (like Iono SIR):
        # - Top banner: "Supporter" tab (left) + "TRAINER" (right), narrow strip
        draw.rectangle([0, 0, width, int(height * 0.055)], fill=255)
        # - Card name below banner — just the name area, not too tall
        draw.rectangle([int(width * 0.03), int(height * 0.055), int(width * 0.45), int(height * 0.115)], fill=255)
        # - Effect text block in the lower portion (the main paragraph)
        draw.rectangle([
            int(width * 0.03), int(height * 0.58),
            int(width * 0.97), int(height * 0.80)
        ], fill=255)
        # - Orange "You may play only 1 Supporter" rule box — wider mask
        draw.rectangle([
            int(width * 0.10), int(height * 0.80),
            int(width * 0.90), int(height * 0.92)
        ], fill=255)
        # - Bottom info line (illustrator, set number, copyright)
        draw.rectangle([0, int(height * 0.93), width, height], fill=255)

    elif card_type == "pokemon_ex":
        # Full-art Pokemon ex layout (like Charizard ex SIR):
        # - Top: name + HP
        draw.rectangle([0, 0, width, int(height * 0.09)], fill=255)
        # - Stage line below name
        draw.rectangle([0, int(height * 0.09), int(width * 0.5), int(height * 0.13)], fill=255)
        # - Attack/ability text block — usually lower third
        draw.rectangle([
            int(width * 0.03), int(height * 0.58),
            int(width * 0.97), int(height * 0.82)
        ], fill=255)
        # - Weakness/resistance/retreat bar
        draw.rectangle([
            int(width * 0.03), int(height * 0.83),
            int(width * 0.97), int(height * 0.90)
        ], fill=255)
        # - Bottom info
        draw.rectangle([0, int(height * 0.92), width, height], fill=255)

    elif card_type == "pokemon_ir":
        # Illustration Rare — text only at bottom
        # - Attack text
        draw.rectangle([
            int(width * 0.03), int(height * 0.68),
            int(width * 0.97), int(height * 0.85)
        ], fill=255)
        # - Weakness/resistance/retreat
        draw.rectangle([
            int(width * 0.03), int(height * 0.86),
            int(width * 0.97), int(height * 0.92)
        ], fill=255)
        # - Bottom info
        draw.rectangle([0, int(height * 0.93), width, height], fill=255)

    elif card_type == "item_hyper":
        # Gold hyper rare items — text in lower portion
        draw.rectangle([0, 0, width, int(height * 0.09)], fill=255)
        draw.rectangle([
            int(width * 0.05), int(height * 0.55),
            int(width * 0.95), int(height * 0.80)
        ], fill=255)
        # Rule box
        draw.rectangle([
            int(width * 0.15), int(height * 0.82),
            int(width * 0.85), int(height * 0.90)
        ], fill=255)
        draw.rectangle([0, int(height * 0.92), width, height], fill=255)

    else:
        # Generic fallback — mask bottom 40%
        draw.rectangle([0, int(height * 0.60), width, height], fill=255)

    # Feather the mask edges for smoother inpainting
    mask = mask.filter(ImageFilter.GaussianBlur(radius=3))
    # Re-threshold to keep it mostly binary but with soft edges
    mask = mask.point(lambda x: 255 if x > 30 else 0)

    return mask


def classify_card(card_json):
    """Determine mask type from card JSON data."""
    import json
    data = json.load(open(card_json))
    category = data.get("category", "")
    rarity = (data.get("rarity") or "").lower()
    trainer_type = data.get("trainerType", "")

    if category == "Trainer":
        return "trainer_supporter"
    elif "illustration rare" == rarity:
        return "pokemon_ir"
    elif "hyper rare" in rarity:
        if category == "Trainer":
            return "item_hyper"
        return "item_hyper"  # gold items
    elif category == "Pokemon":
        return "pokemon_ex"
    return "generic"


def inpaint_card(card_id, card_type=None):
    """Inpaint text from a cached card image."""
    img_path = CACHE_DIR / f"{card_id}.png"
    json_path = CACHE_DIR / f"{card_id}.json"

    if not img_path.exists():
        print(f"Image not found: {img_path}")
        return None

    if card_type is None and json_path.exists():
        card_type = classify_card(json_path)
    elif card_type is None:
        card_type = "generic"

    print(f"  Loading image: {img_path}")
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    print(f"  Image size: {w}x{h}, mask type: {card_type}")

    mask = make_text_mask(w, h, card_type)

    # Save mask for debugging
    mask_path = OUTPUT_DIR / f"{card_id}_mask.png"
    mask.save(mask_path)
    print(f"  Mask saved: {mask_path}")

    print(f"  Running LaMa inpainting...")
    lama = SimpleLama()
    result = lama(img, mask)

    out_path = OUTPUT_DIR / f"{card_id}_clean.png"
    result.save(out_path)
    print(f"  Clean image saved: {out_path}")
    return out_path


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if len(sys.argv) < 2:
        # Default: test with Iono full art
        card_ids = ["sv04.5-237"]
    else:
        card_ids = sys.argv[1:]

    for card_id in card_ids:
        print(f"\nInpainting {card_id}...")
        inpaint_card(card_id)

    print("\nDone!")


if __name__ == "__main__":
    main()
