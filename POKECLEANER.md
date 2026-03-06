# PokeCleaner Integration Notes

## What It Does

PokeCleaner removes text from Pokemon card images using FLUX.2 Klein 9B via the framehouse server (ComfyUI + 4080 GPU). It generates "clean" versions of card art with no attack text, rules, weakness/resistance — just the artwork extended to fill the full card.

## How It Works

1. Takes a card image (600x825) from the pokeproxy cache
2. Resizes to 736x1024 (FLUX-friendly dimensions, multiple of 16)
3. Submits to framehouse as a Klein compose job with the card as a reference image
4. Klein 9B generates a new image that matches the card's art style but without text
5. Composites: keeps the original top 20% (name, HP, type icons) and replaces the bottom 80% with the generated text-free artwork

## Output Files (in `../pokecleaner/output/`)

For each card `{id}`:

- `{id}_resized.png` — Original card resized to 736x1024
- `{id}_clean.png` — Full Klein 9B generation (text-free, entire card regenerated)
- `{id}_composite.png` — Original top 20% + generated bottom 80%

## Integration with PokeProxy

PokeCleaner is now integrated directly into pokeproxy.py. The cleaning pipeline (resize → submit to framehouse → save clean + composite) runs on-demand when `--clean` mode is enabled.

### Usage via pokeproxy:

```bash
# Use composite images (original top 20% + AI bottom 80%)
python pokeproxy.py --clean composite decklist.txt

# Use fully clean images (AI-regenerated, pokeproxy renders header overlay)
python pokeproxy.py --clean clean decklist.txt

# Per-card override in decklist
SFA 90 x1 clean=clean    # force clean mode for this card only

# Specify framehouse server URL
python pokeproxy.py --clean composite --framehouse http://gpu-box:3000 decklist.txt
```

### Cache locations (checked in order):
1. `cache/{id}_clean.png` / `cache/{id}_composite.png` — local pokeproxy cache
2. `../pokecleaner/output/{id}_clean.png` / `..._composite.png` — legacy standalone output

When generating on-demand, both `_clean` and `_composite` variants are saved to `cache/`.

### Image dimensions:

- Clean images: 736x1024 (5:7 ratio, same as standard Pokemon cards)
- Original cache images: 600x825
- Pokeproxy SVG cards: 750x1050

All share the 5:7 aspect ratio so scaling is straightforward.

## Standalone PokeCleaner

The standalone `../pokecleaner/pokecleaner.py` script can still be used independently:

```bash
cd ../pokecleaner
../pokeproxy/.venv/bin/python3 pokecleaner.py --cards sv06.5-090 sv06.5-091
../pokeproxy/.venv/bin/python3 pokecleaner.py --mask-top 0.15 --seed 123 --cards sv06.5-090
```

### Requirements:
- framehouse server running (`cd ../framehouse/framehouse-server && npm run dev`)
- ComfyUI running on the GPU machine with Klein 9B model files installed
- pokeproxy venv with PIL (`../pokeproxy/.venv/bin/python3`)

### Performance:
- ~5-10 seconds per card on 4080 GPU via framehouse
- 19 Shrouded Fable cards processed in ~2 minutes

## Prompt Used

The default prompt for generation:
```
continue the artwork illustration, extend the scene naturally,
no text, no writing, no letters, no numbers, no symbols,
clean artwork only, high quality illustration
```

Card-specific prompts can be passed for better results on individual cards.

## Current Coverage

All 19 cached Shrouded Fable (sv06.5) cards have been processed, including:
- 4 Double Rare ex cards (036-039)
- 3 Uncommon trainers/items (055, 059, 061)
- 1 Illustration Rare (072)
- 5 Ultra Rare (082-085, 088)
- 4 Special Illustration Rare (090-093)
- 2 Hyper Rare (095-096)
