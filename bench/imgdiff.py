"""Compare two screenshots of the same frozen frame.

Prints mean absolute difference, PSNR, the share of pixels that changed by more than a small
threshold, and a sharpness ratio (Laplacian energy, b vs a) on a grid, so blurrier textures
(lower mips) show up as tiles with a ratio below 1.

    python3 bench/imgdiff.py a.png b.png [--heatmap out.png]
"""
import argparse
import hashlib
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('a'); ap.add_argument('b'); ap.add_argument('--heatmap'); ap.add_argument('--grid', type=int, default=8)
args = ap.parse_args()

a = np.asarray(Image.open(args.a).convert('RGB'), dtype=np.float32)
b = np.asarray(Image.open(args.b).convert('RGB'), dtype=np.float32)
d = np.abs(a - b).mean(axis=2)
mse = ((a - b) ** 2).mean()
psnr = float('inf') if mse == 0 else 10 * np.log10(255 ** 2 / mse)
print(f"mean |diff| {d.mean():.3f}   PSNR {psnr:.2f} dB   pixels changed >8: {100 * (d > 8).mean():.2f}%   >24: {100 * (d > 24).mean():.2f}%")
# Exact equality, not thresholds: "lossless" means these are all zero (or no larger than two
# captures of the unchanged build, which sets the noise floor).
ne = a != b
print(f"exact: identical={'yes' if not ne.any() else 'no'}  unequal pixels {int(ne.any(axis=2).sum())}"
      f"  unequal channels {int(ne.sum())}  max channel error {int(np.abs(a - b).max())}"
      f"  sha256 a {hashlib.sha256(a.astype(np.uint8).tobytes()).hexdigest()[:16]}"
      f" b {hashlib.sha256(b.astype(np.uint8).tobytes()).hexdigest()[:16]}")

def lap_energy(img):
    g = img.mean(axis=2)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return lap ** 2

ea, eb = lap_energy(a), lap_energy(b)
h, w = ea.shape
n = args.grid
rows = []
for i in range(n):
    row = []
    for j in range(n):
        ta = ea[i * h // n:(i + 1) * h // n, j * w // n:(j + 1) * w // n].mean()
        tb = eb[i * h // n:(i + 1) * h // n, j * w // n:(j + 1) * w // n].mean()
        row.append(tb / ta if ta > 0 else 1.0)
    rows.append(row)
print(f"sharpness b/a overall {eb.mean() / ea.mean():.3f}; per tile (row by row, {n}x{n}):")
for row in rows:
    print('  ' + ' '.join(f"{r:5.2f}" for r in row))
if args.heatmap:
    hm = np.clip(d * 8, 0, 255).astype(np.uint8)
    Image.fromarray(hm).save(args.heatmap)
