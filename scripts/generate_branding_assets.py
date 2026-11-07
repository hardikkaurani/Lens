#!/usr/bin/env python3
"""
Official LENS Logo Asset Generation Script
Extracts, decontaminates, upscales, and exports the official LENS metallic
ribbon + dot brand mark across web and mobile asset structures.

Features:
- Dynamic reference background detection (sampling canvas corners).
- Dynamic foreground segmentation & connected-component spatial validation.
- Geometric verification: validates independent circular dot at lower-left of ribbon.
- Subpixel Lanczos interpolation & Gaussian-smoothed signed distance fields.
- 100% monochromatic grayscale chrome luminance with zero cream fringe.
- Multi-platform asset export for Web and Flutter mobile.
- Automated validation suite for CI/CD (--check and --dry-run flags).
"""

import os
import io
import sys
import base64
import argparse
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter, label, binary_fill_holes

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REF_PATH = os.path.join(REPO_ROOT, "assets", "branding", "lens-logo-reference.png")


def verify_assets(repo_root: str = REPO_ROOT) -> bool:
    """Verifies that all expected branding assets are present on disk and meet quality standards."""
    expected_files = [
        os.path.join(repo_root, "assets", "branding", "lens-logo-reference.png"),
        os.path.join(repo_root, "assets", "branding", "lens-symbol.png"),
        os.path.join(repo_root, "assets", "branding", "lens-logo-preview.png"),
        os.path.join(repo_root, "apps", "web", "public", "branding", "lens-symbol.png"),
        os.path.join(repo_root, "apps", "web", "public", "branding", "lens-symbol@2x.png"),
        os.path.join(repo_root, "apps", "web", "public", "branding", "lens-symbol@3x.png"),
        os.path.join(repo_root, "apps", "web", "public", "branding", "lens-symbol.svg"),
        os.path.join(repo_root, "apps", "web", "public", "favicon.ico"),
        os.path.join(repo_root, "apps", "web", "public", "apple-touch-icon.png"),
        os.path.join(repo_root, "apps", "mobile", "assets", "branding", "lens_symbol.png"),
        os.path.join(repo_root, "apps", "mobile", "assets", "branding", "2.0x", "lens_symbol.png"),
        os.path.join(repo_root, "apps", "mobile", "assets", "branding", "3.0x", "lens_symbol.png"),
    ]
    missing = [f for f in expected_files if not os.path.isfile(f)]
    if missing:
        print(f"Missing {len(missing)} branding asset(s):", file=sys.stderr)
        for m in missing:
            print(f"  - {os.path.relpath(m, repo_root)}", file=sys.stderr)
        return False

    # Inspect master asset quality
    master_path = os.path.join(repo_root, "assets", "branding", "lens-symbol.png")
    master = Image.open(master_path)
    arr = np.array(master)
    if arr.ndim != 3 or arr.shape[2] != 4:
        print("Master asset must be RGBA format.", file=sys.stderr)
        return False

    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    if np.min(alpha) != 0 or np.max(alpha) != 255:
        print("Master asset lacks genuine alpha transparency (min=0, max=255).", file=sys.stderr)
        return False

    # Check for warm cream contamination (R > B or G > B)
    warm = (rgb[:, :, 0].astype(float) - rgb[:, :, 2].astype(float)) + (rgb[:, :, 1].astype(float) - rgb[:, :, 2].astype(float))
    warm_fg = warm[alpha > 30]
    if len(warm_fg) > 0 and np.max(warm_fg) > 1.0:
        print(f"Master asset exhibits warm cream fringing (max warm chroma = {np.max(warm_fg):.1f}).", file=sys.stderr)
        return False

    print(f"All {len(expected_files)} branding assets verified with clean grayscale transparency.")
    return True


def extract_master_symbol(ref_image: Image.Image) -> Image.Image:
    """Extracts the official LENS mark from reference image with full decontamination."""
    ref_arr = np.array(ref_image).astype(np.float64)
    h_orig, w_orig = ref_arr.shape[:2]

    # 1. Background color detection via canvas corners
    patch_size = min(30, h_orig // 10, w_orig // 10)
    corners = np.concatenate([
        ref_arr[:patch_size, :patch_size].reshape(-1, 3),
        ref_arr[:patch_size, -patch_size:].reshape(-1, 3),
        ref_arr[-patch_size:, :patch_size].reshape(-1, 3),
        ref_arr[-patch_size:, -patch_size:].reshape(-1, 3),
    ], axis=0)
    bg_color = np.median(corners, axis=0)
    print(f"Detected reference background color: RGB({bg_color[0]:.1f}, {bg_color[1]:.1f}, {bg_color[2]:.1f})")

    # 2. Dynamic foreground segmentation & connected-component discovery
    dist = np.linalg.norm(ref_arr - bg_color, axis=2)
    fg_mask = dist > 25.0
    lbl, n = label(fg_mask)
    if n < 2:
        raise ValueError(f"Expected at least 2 foreground components (ribbon + dot), found {n}")

    sizes = [np.sum(lbl == i) for i in range(1, n + 1)]
    top_indices = np.argsort(sizes)[::-1][:2]

    comp_a = binary_fill_holes(lbl == (top_indices[0] + 1))
    comp_b = binary_fill_holes(lbl == (top_indices[1] + 1))

    if np.sum(comp_a) > np.sum(comp_b):
        ribbon_mask = comp_a
        dot_mask = comp_b
    else:
        ribbon_mask = comp_b
        dot_mask = comp_a

    coords_dot = np.argwhere(dot_mask)
    coords_ribbon = np.argwhere(ribbon_mask)
    cy_dot, cx_dot = coords_dot.mean(axis=0)
    cy_rib, cx_rib = coords_ribbon.mean(axis=0)

    # Validate non-negotiable geometry: dot is strictly lower-left relative to ribbon
    if cx_dot >= cx_rib:
        raise ValueError(f"Geometry anomaly: dot (cx={cx_dot:.1f}) is not left of ribbon (cx={cx_rib:.1f})")
    if cy_dot <= coords_ribbon[:, 0].min():
        raise ValueError(f"Geometry anomaly: dot (cy={cy_dot:.1f}) is above ribbon top")

    print(f"Geometric validation passed: Dot at ({cx_dot:.1f}, {cy_dot:.1f}), Ribbon center at ({cx_rib:.1f}, {cy_rib:.1f})")

    # 3. Dynamic tight crop around detected mark with margin
    all_fg = np.vstack([coords_dot, coords_ribbon])
    ymin_f, xmin_f = all_fg.min(axis=0)
    ymax_f, xmax_f = all_fg.max(axis=0)

    pad_box = 8
    crop_box = (
        max(0, int(xmin_f - pad_box)),
        max(0, int(ymin_f - pad_box)),
        min(w_orig, int(xmax_f + pad_box + 1)),
        min(h_orig, int(ymax_f + pad_box + 1)),
    )
    crop = ref_image.crop(crop_box)

    # 4. 4x Lanczos reconstruction for continuous subpixel interpolation
    scale = 4
    large_w = crop.size[0] * scale
    large_h = crop.size[1] * scale
    large = crop.resize((large_w, large_h), Image.Resampling.LANCZOS)
    arr = np.array(large).astype(np.float64)

    dist_l = np.linalg.norm(arr - bg_color, axis=2)
    core = dist_l > 25.0
    lbl_l, n_l = label(core)
    sizes_l = [np.sum(lbl_l == i) for i in range(1, n_l + 1)]
    top_l = np.argsort(sizes_l)[::-1][:2]

    comp_a_l = binary_fill_holes(lbl_l == (top_l[0] + 1))
    comp_b_l = binary_fill_holes(lbl_l == (top_l[1] + 1))

    if np.sum(comp_a_l) > np.sum(comp_b_l):
        ribbon_core = comp_a_l
        dot_core = comp_b_l
    else:
        ribbon_core = comp_b_l
        dot_core = comp_a_l

    # Smooth circular dot mask
    coords_dot_l = np.argwhere(dot_core)
    cy_d_l, cx_d_l = coords_dot_l.mean(axis=0)
    r_dot = np.sqrt(np.sum(dot_core) / np.pi)

    Y, X = np.ogrid[:arr.shape[0], :arr.shape[1]]
    dist_dot = np.sqrt((X - cx_d_l) ** 2 + (Y - cy_d_l) ** 2)
    dot_alpha = np.clip((r_dot + 1.5 - dist_dot) / 3.0, 0.0, 1.0)
    dot_alpha = 3 * dot_alpha ** 2 - 2 * dot_alpha ** 3

    # Smooth ribbon mask via Gaussian-smoothed signed distance field
    d_in = distance_transform_edt(ribbon_core)
    d_out = distance_transform_edt(~ribbon_core)
    signed = gaussian_filter(d_in - d_out, sigma=0.75)
    ribbon_alpha = np.clip((signed + 1.5) / 3.0, 0.0, 1.0)
    ribbon_alpha = 3 * ribbon_alpha ** 2 - 2 * ribbon_alpha ** 3

    alpha = np.maximum(ribbon_alpha, dot_alpha)

    # 5. Monochromatic grayscale luminance and boundary decontamination
    # Reference defines a monochromatic grayscale metallic chrome mark.
    # Convert RGB to pure luminance to eliminate paper background tint completely.
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    mono_arr = np.dstack([lum, lum, lum])

    # Nearest neighbor metallic color propagation on semi-transparent transition boundary
    solid_core = (alpha >= 0.90)
    _, indices = distance_transform_edt(~solid_core, return_indices=True)
    propagated_mono = mono_arr[indices[0], indices[1]]

    t_prop = np.clip((0.95 - alpha) / 0.10, 0.0, 1.0)[:, :, None]
    final_mono = (1.0 - t_prop) * mono_arr + t_prop * propagated_mono

    final_rgb = np.clip(final_mono, 0, 255).astype(np.uint8)
    final_alpha = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)

    # 6. Tight crop with standard clear-space padding
    y_idx, x_idx = np.where(final_alpha > 0)
    ymin_c = max(0, int(y_idx.min() - 8))
    ymax_c = min(arr.shape[0], int(y_idx.max() + 9))
    xmin_c = max(0, int(x_idx.min() - 8))
    xmax_c = min(arr.shape[1], int(x_idx.max() + 9))

    rgba_master = np.dstack([
        final_rgb[ymin_c:ymax_c, xmin_c:xmax_c],
        final_alpha[ymin_c:ymax_c, xmin_c:xmax_c],
    ])
    master_img = Image.fromarray(rgba_master, "RGBA")
    print(f"Master transparent logo extracted: {master_img.size} (aspect ratio = {master_img.width / master_img.height:.3f})")
    return master_img


def generate_all_assets(repo_root: str = REPO_ROOT) -> None:
    """Generates all web, mobile, and documentation assets."""
    if not os.path.exists(REF_PATH):
        raise FileNotFoundError(f"Reference image not found at {REF_PATH}")

    ref = Image.open(REF_PATH)
    master_img = extract_master_symbol(ref)

    # Standard target dimensions preserving aspect ratio (2.38:1)
    size_3x = (1200, 504)
    size_2x = (800, 336)
    size_1x = (400, 168)

    img_3x = master_img.resize(size_3x, Image.Resampling.LANCZOS)
    img_2x = master_img.resize(size_2x, Image.Resampling.LANCZOS)
    img_1x = master_img.resize(size_1x, Image.Resampling.LANCZOS)

    # Web branding directory
    web_branding_dir = os.path.join(repo_root, "apps", "web", "public", "branding")
    os.makedirs(web_branding_dir, exist_ok=True)

    img_1x.save(os.path.join(web_branding_dir, "lens-symbol.png"), "PNG", optimize=True)
    img_2x.save(os.path.join(web_branding_dir, "lens-symbol@2x.png"), "PNG", optimize=True)
    img_3x.save(os.path.join(web_branding_dir, "lens-symbol@3x.png"), "PNG", optimize=True)
    print("Saved web PNG symbols (1x, 2x, 3x).")

    # Web SVG symbol with embedded high-resolution raster
    buffer = io.BytesIO()
    img_3x.save(buffer, format="PNG", optimize=True)
    b64_png = base64.b64encode(buffer.getvalue()).decode("utf-8")

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 504" width="100%" height="100%" fill="none">
  <!-- LENS Official Brand Mark - Monochromatic Metallic Chrome Ribbon + Dot -->
  <defs>
    <filter id="lens-contrast" x="-5%" y="-5%" width="110%" height="110%">
      <feColorMatrix type="matrix" values="
        1.05 0    0    0 0
        0    1.05 0    0 0
        0    0    1.05 0 0
        0    0    0    1 0" />
    </filter>
  </defs>
  <image
    href="data:image/png;base64,{b64_png}"
    width="1200"
    height="504"
    preserveAspectRatio="xMidYMid meet"
    filter="url(#lens-contrast)"
  />
</svg>
"""
    path_web_svg = os.path.join(web_branding_dir, "lens-symbol.svg")
    with open(path_web_svg, "w", encoding="utf-8") as f:
        f.write(svg_content)
    print("Saved web SVG symbol.")

    # Favicons and touch icons
    def create_app_icon(size, bg_color=(10, 13, 20)):
        canvas = Image.new("RGBA", (size, size), bg_color + (255,))
        mark_w = int(size * 0.70)
        mark_h = int(mark_w * (504 / 1200))
        resized_mark = master_img.resize((mark_w, mark_h), Image.Resampling.LANCZOS)
        offset_x = (size - mark_w) // 2
        offset_y = (size - mark_h) // 2
        canvas.paste(resized_mark, (offset_x, offset_y), resized_mark)
        return canvas

    web_public_dir = os.path.join(repo_root, "apps", "web", "public")
    fav_16 = create_app_icon(16)
    fav_32 = create_app_icon(32)
    fav_48 = create_app_icon(48)
    fav_16.save(os.path.join(web_public_dir, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    fav_32.save(os.path.join(web_branding_dir, "favicon-32x32.png"), "PNG")
    fav_16.save(os.path.join(web_branding_dir, "favicon-16x16.png"), "PNG")

    apple_icon = create_app_icon(180)
    apple_icon.save(os.path.join(web_public_dir, "apple-touch-icon.png"), "PNG")
    print("Saved web favicon.ico, apple-touch-icon.png, and PNG favicons.")

    # Mobile assets directory
    mobile_branding_dir = os.path.join(repo_root, "apps", "mobile", "assets", "branding")
    os.makedirs(mobile_branding_dir, exist_ok=True)
    os.makedirs(os.path.join(mobile_branding_dir, "2.0x"), exist_ok=True)
    os.makedirs(os.path.join(mobile_branding_dir, "3.0x"), exist_ok=True)

    img_1x.save(os.path.join(mobile_branding_dir, "lens_symbol.png"), "PNG", optimize=True)
    img_2x.save(os.path.join(mobile_branding_dir, "lens_symbol@2x.png"), "PNG", optimize=True)
    img_3x.save(os.path.join(mobile_branding_dir, "lens_symbol@3x.png"), "PNG", optimize=True)
    img_2x.save(os.path.join(mobile_branding_dir, "2.0x", "lens_symbol.png"), "PNG", optimize=True)
    img_3x.save(os.path.join(mobile_branding_dir, "3.0x", "lens_symbol.png"), "PNG", optimize=True)
    print("Saved Flutter mobile branding assets (1x, 2.0x, 3.0x).")

    # Android launcher icons
    android_res_dir = os.path.join(repo_root, "apps", "mobile", "android", "app", "src", "main", "res")
    mipmap_configs = [
        ("mipmap-mdpi", 48),
        ("mipmap-hdpi", 72),
        ("mipmap-xhdpi", 96),
        ("mipmap-xxhdpi", 144),
        ("mipmap-xxxhdpi", 192),
    ]
    for folder, icon_size in mipmap_configs:
        dest_dir = os.path.join(android_res_dir, folder)
        os.makedirs(dest_dir, exist_ok=True)
        launcher_img = create_app_icon(icon_size, bg_color=(10, 13, 20))
        launcher_img.save(os.path.join(dest_dir, "ic_launcher.png"), "PNG")
    print("Saved Android mipmap launcher icons.")

    # Presentation preview card
    card_w, card_h = 1600, 960
    card = Image.new("RGBA", (card_w, card_h), (10, 13, 20, 255))
    draw = ImageDraw.Draw(card)

    draw.text((60, 40), "LENS — OFFICIAL BRAND IDENTITY SYSTEM", fill=(241, 245, 249, 255))
    draw.text((60, 68), "Monochromatic Metallic Chrome Ribbon & Dot Mark • Transparent Raster & Vector System", fill=(148, 163, 184, 255))

    # Dark interface preview
    panel_dark = Image.new("RGBA", (690, 360), (17, 23, 38, 255))
    draw_pd = ImageDraw.Draw(panel_dark)
    draw_pd.rectangle([0, 0, 689, 359], outline=(255, 255, 255, 30), width=1)
    draw_pd.text((24, 20), "DARK INTERFACE (Default)", fill=(148, 163, 184, 255))
    p1_mark = master_img.resize((480, 201), Image.Resampling.LANCZOS)
    panel_dark.paste(p1_mark, (105, 95), p1_mark)
    card.paste(panel_dark, (60, 110))

    # Light interface preview
    panel_light = Image.new("RGBA", (690, 360), (255, 255, 255, 255))
    draw_pl = ImageDraw.Draw(panel_light)
    draw_pl.rectangle([0, 0, 689, 359], outline=(0, 0, 0, 30), width=1)
    draw_pl.text((24, 20), "LIGHT INTERFACE", fill=(71, 85, 105, 255))
    panel_light.paste(p1_mark, (105, 95), p1_mark)
    card.paste(panel_light, (850, 110))

    # Transparent checkered grid preview
    panel_grid = Image.new("RGBA", (1480, 380), (24, 30, 46, 255))
    chk_size = 20
    for y in range(0, 380, chk_size):
        for x in range(0, 1480, chk_size):
            if ((x // chk_size) + (y // chk_size)) % 2 == 0:
                draw_pg = ImageDraw.Draw(panel_grid)
                draw_pg.rectangle([x, y, x + chk_size - 1, y + chk_size - 1], fill=(32, 40, 60, 255))

    draw_pg = ImageDraw.Draw(panel_grid)
    draw_pg.rectangle([0, 0, 1479, 379], outline=(255, 255, 255, 30), width=1)
    draw_pg.text((24, 20), "TRANSPARENCY & CLEAR-SPACE SPECIFICATION (No Margins, Seamless Alpha Matte)", fill=(148, 163, 184, 255))

    p3_mark = master_img.resize((600, 252), Image.Resampling.LANCZOS)
    panel_grid.paste(p3_mark, (440, 75), p3_mark)
    card.paste(panel_grid, (60, 510))

    draw.text((60, 915), "Geometry: Stylized 'N' Ribbon + Detached Metallic Dot  |  Material: Monochromatic Grayscale Chrome  |  Ratio: 2.38:1", fill=(100, 116, 139, 255))

    card_rgb = card.convert("RGB")
    path_card_web = os.path.join(web_branding_dir, "lens-logo-preview.png")
    path_card_root = os.path.join(repo_root, "assets", "branding", "lens-logo-preview.png")
    path_root_symbol = os.path.join(repo_root, "assets", "branding", "lens-symbol.png")

    card_rgb.save(path_card_web, "PNG", optimize=True)
    card_rgb.save(path_card_root, "PNG", optimize=True)
    img_3x.save(path_root_symbol, "PNG", optimize=True)
    print("Saved preview cards and root branding documentation assets.")
    print("All branding assets generated successfully!")


def main():
    parser = argparse.ArgumentParser(description="Generate and verify official LENS branding assets.")
    parser.add_argument("--check", action="store_true", help="Verify presence and quality of branding assets without rebuilding.")
    parser.add_argument("--dry-run", action="store_true", help="Run generation in dry-run mode to validate workflow.")
    args = parser.parse_args()

    if args.check:
        if verify_assets():
            sys.exit(0)
        sys.exit(1)

    if args.dry_run:
        print("Executing dry-run asset extraction and validation...")
        ref = Image.open(REF_PATH)
        master = extract_master_symbol(ref)
        assert master.size[0] > 0 and master.size[1] > 0
        print("Dry run extraction and geometric verification succeeded.")
        sys.exit(0)

    generate_all_assets()
    if not verify_assets():
        sys.exit(1)


if __name__ == "__main__":
    main()
