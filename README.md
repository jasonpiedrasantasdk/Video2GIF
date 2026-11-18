# Video → GIF

[![CI](https://github.com/jasonpiedrasantasdk/video2gif/actions/workflows/ci.yml/badge.svg)](https://github.com/jasonpiedrasantasdk/video2gif/actions/workflows/ci.yml)

A small Tkinter desktop app that converts MP4/MKV/WebM video to GIF using
`ffmpeg`'s two-pass palette pipeline. No lossy GIF compression: the palette is
generated from the actual frames, so colors stay accurate and gradients don't
band.

## Features

- Two-pass `palettegen` / `paletteuse` conversion
- Output FPS, output width (0 = original), trim start/end in seconds
- Five dither modes: `sierra2_4a`, `sierra2`, `floyd_steinberg`, `bayer`, `none`
- Palette size from 2 to 256 colors
- Source info from `ffprobe` (resolution, FPS, duration, codec)
- Thumbnail preview of the source video and animated preview of the result
- Progress messages and an estimated output size
- Dark themed UI

## Requirements

- Python 3.8+
- `tkinter` (Debian/Ubuntu: `sudo apt install python3-tk`)
- `ffmpeg` and `ffprobe` on `PATH` (required)
- No third-party Python packages

## Run

```bash
./launch.sh
# or
python3 video2gif.py
```

## Usage

1. **Open Video…** and pick an MP4/MKV/WebM file.
2. Set FPS, width, trim range, dither and max colors.
3. **Convert to GIF**, choose the output path, and wait for the two passes.
4. The result is previewed in the right-hand pane.

## How it works

```
Pass 1:  ffmpeg -i input -vf "fps=N,scale=W:-1:flags=lanczos,palettegen=max_colors=C:stats_mode=diff" palette.png
Pass 2:  ffmpeg -i input -i palette.png -lavfi "fps=N,scale=W:-1 [x]; [x][1:v] paletteuse=dither=D" output.gif
```

Both passes respect the trim range. The temporary palette file is removed
afterwards, including on failure.

## License

MIT — see [LICENSE](LICENSE).
