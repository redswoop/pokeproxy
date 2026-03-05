#!/usr/bin/env python3
"""Test mflux-generate-fill for removing text from a Pokemon card."""

from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

def make_umbreon_vmax_mask(width, height):
    """Create mask for Umbreon VMAX alt art (swsh7/215).
    White = regions to inpaint (text areas)."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    # Top: VMAX name bar + HP + "Single Strike" badge
    draw.rectangle([0, 0, width, int(height * 0.075)], fill=255)

    # "Evolves from Umbreon V" line
    draw.rectangle([0, int(height * 0.075), int(width * 0.65), int(height * 0.11)], fill=255)

    # Ability box: "Dark Signal" text block (mid card)
    draw.rectangle([
        int(width * 0.03), int(height * 0.52),
        int(width * 0.97), int(height * 0.68)
    ], fill=255)

    # Attack: "Max Darkness 160" line
    draw.rectangle([
        int(width * 0.03), int(height * 0.68),
        int(width * 0.97), int(height * 0.76)
    ], fill=255)

    # Weakness/Resistance/Retreat bar
    draw.rectangle([
        int(width * 0.03), int(height * 0.80),
        int(width * 0.97), int(height * 0.88)
    ], fill=255)

    # Bottom info line (VMAX rule, illustrator, set number)
    draw.rectangle([0, int(height * 0.88), width, height], fill=255)

    # Feather edges
    mask = mask.filter(ImageFilter.GaussianBlur(radius=2))
    mask = mask.point(lambda x: 255 if x > 30 else 0)

    return mask


def main():
    orig = OUTPUT_DIR / "swsh7_215_orig.png"
    img = Image.open(orig).convert("RGB")
    w, h = img.size
    print(f"Original size: {w}x{h}")

    # Upscale to Flux-friendly dimensions (multiples of 16, ~3x)
    new_w = 736  # 245 * 3 ≈ 735 → 736
    new_h = 1024  # 342 * 3 ≈ 1026 → 1024
    img_resized = img.resize((new_w, new_h), Image.LANCZOS)
    resized_path = OUTPUT_DIR / "swsh7_215_resized.png"
    img_resized.save(resized_path)
    print(f"Resized to: {new_w}x{new_h}")

    # Create mask at the resized dimensions
    mask = make_umbreon_vmax_mask(new_w, new_h)
    mask_path = OUTPUT_DIR / "swsh7_215_mask.png"
    mask.save(mask_path)
    print(f"Mask saved: {mask_path}")

    # Preview: overlay mask on image for visual check
    preview = img_resized.copy()
    red_overlay = Image.new("RGB", (new_w, new_h), (255, 0, 0))
    preview = Image.composite(red_overlay, preview, mask)
    preview_path = OUTPUT_DIR / "swsh7_215_mask_preview.png"
    preview.save(preview_path)
    print(f"Mask preview saved: {preview_path}")

    print(f"\nRun mflux-generate-fill with:")
    print(f"  .venv/bin/mflux-generate-fill \\")
    print(f"    --model dev \\")
    print(f"    -q 8 \\")
    print(f"    --prompt 'anime illustration of Umbreon, dark purple night sky, moonlit cityscape, glowing yellow rings, no text, no writing, clean artwork' \\")
    print(f"    --image-path {resized_path} \\")
    print(f"    --masked-image-path {mask_path} \\")
    print(f"    --width {new_w} --height {new_h} \\")
    print(f"    --steps 30 \\")
    print(f"    --output {OUTPUT_DIR / 'swsh7_215_mflux.png'}")


if __name__ == "__main__":
    main()
