# Open Image Blender

A small tool for turning images into 3D scenes.

Drop an image in, get a 3D scene file out.

## Install (Arch / CachyOS)

Build and install the local package:

```bash
cd packaging
makepkg -si
```

Then launch **Open Image Blender** from your application menu, or run
`openimageblender`.

You will need Blender installed. The app can install its Blender add-on
and launch Blender for you from its Setup panel.

## Usage

Open the app, choose an image, and click Run. The result is a `.blend`
file. Runs and outputs are kept in
`~/.local/share/openimageblender/`.

From a source checkout you can also use the command line:

```bash
python3 -m src.loop inputs/your_image.png --output outputs/model.blend
python3 -m src.app   # the desktop app
```

## How the loop works

1. **Reference sheet (images only, no Blender).** Muse Image
   (`muse-image-1.0`) turns your image into a 2×2 turnaround sheet
   (front/side/back/top). You confirm it before any Blender work.
2. **Build.** Blender (via MCP) builds the model — parametric
   strategies by default, or free-form `bpy` written by Muse Spark
   (`muse-spark-1.3-contributor`) with `--driver-code`.
3. **Critique.** Muse Wonder (`muse-wonder-1.0`) compares the renders
   to the references, rates the model **0–10**, lists critical
   defects, and writes the next round's plan and improvement prompt.
   Segmentation for the metric scores uses SAM 3.1 (`sam-3.1`) when a
   key is set, with a local fallback otherwise.
4. **Repeat** until the rating reaches your target (default 8/10),
   the rounds plateau, or you cancel. The best round's `.blend` wins.

Useful flags:

```bash
python3 -m src.loop inputs/char.png --target-rating 8          # default finish line
python3 -m src.loop inputs/char.png --no-rating --max-rounds 5 # rating off
python3 -m src.loop inputs/char.png --driver-code              # AI-written bpy rounds
python3 -m src.loop inputs/char.png --segment-prompt character # SAM concept prompt
```

In the desktop app the same controls are the **AI rating finish
line** checkbox + rating spin, and the experimental driver-code
checkbox. Each round's `score.json` records the rating, plan and
prompt; `summary.json` records why the loop stopped (`target`,
`user`, `plateau` or `max-rounds`). All model calls use the Meta
Responses API (`/responses`, plus `/files` uploads for images).

## API key (optional)

The app works without a key. To use your own Meta API key, paste it in
the app's API key field (stored locally), or copy `.env.example` to
`.env` for command-line use.

## License

MIT — see [LICENSE](LICENSE).
