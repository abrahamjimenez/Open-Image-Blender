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

## API key (optional)

The app works without a key. To use your own Meta API key, paste it in
the app's API key field (stored locally), or copy `.env.example` to
`.env` for command-line use.

## License

MIT — see [LICENSE](LICENSE).
