#!/usr/bin/env python3
"""
Official LENS Logo Asset Generation Script
Extracts, decontaminates, upscales, and exports the official LENS metallic
ribbon + dot brand mark across web and mobile asset structures.
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


def verify_assets_exist() -> bool:
    """Verifies that all expected branding assets are present on disk."""
    expected_files = [
        os.path.join(REPO_ROOT, "assets", "branding", "lens-logo-reference.png"),
        os.path.join(REPO_ROOT, "assets", "branding", "lens-symbol.png"),
        os.path.join(REPO_ROOT, "assets", "branding", "lens-logo-preview.png"),
        os.path.join(REPO_ROOT, "apps", "web", "public", "branding", "lens-symbol.png"),
        os.path.join(REPO_ROOT, "apps", "web", "public", "branding", "lens-symbol@2x.png"),
        os.path.join(REPO_ROOT, "apps", "web", "public", "branding", "lens-symbol@3x.png"),
        os.path.join(REPO_ROOT, "apps", "web", "public", "branding", "lens-symbol.svg"),
        os.path.join(REPO_ROOT, "apps", "web", "public", "favicon.ico"),
        os.path.join(REPO_ROOT, "apps", "web", "public", "apple-touch-icon.png"),
        os.path.join(REPO_ROOT, "apps", "mobile", "assets", "branding", "lens_symbol.png"),
        os.path.join(REPO_ROOT, "apps", "mobile", "assets", "branding", "2.0x", "lens_symbol.png"),
        os.path.join(REPO_ROOT, "apps", "mobile", "assets", "branding", "3.0x", "lens_symbol.png"),
    ]
    missing = [f for f in expected_files if not os.path.isfile(f)]
    if missing:
        print(f"Missing {len(missing)} branding asset(s):", file=sys.stderr)
        for m in missing:
            print(f"  - {os.path.relpath(m, REPO_ROOT)}", file=sys.stderr)
        return False
    print(f"All {len(expected_files)} primary branding assets verified successfully.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate and verify official LENS branding assets.")
    parser.add_argument("--check", action="store_true", help="Verify presence of generated assets without rebuilding.")
    args = parser.parse_args()

    if args.check:
        if verify_assets_exist():
            sys.exit(0)
        sys.exit(1)

    print(f"Loading reference from: {REF_PATH}")
    if not os.path.exists(REF_PATH):
        raise FileNotFoundError(f"Reference image not found at {REF_PATH}")

    ref = Image.open(REF_PATH)
    
    # 1. High-precision crop around symbol in reference coordinates
    # Reference image size is 574x1024, symbol sits at y=450..571, x=140..435
    crop_box = (136, 446, 439, 575)
    crop = ref.crop(crop_box)
    
    # 2. 4x Lanczos reconstruction for continuous subpixel interpolation
    scale = 4
    large_w = crop.size[0] * scale
    large_h = crop.size[1] * scale
    large = crop.resize((large_w, large_h), Image.Resampling.LANCZOS)
    arr = np.array(large).astype(np.float64)
    
    # Background color in reference image
    bg_color = np.array([252.0, 252.0, 244.0])
    
    # Distance in RGB space from the cream background
    dist = np.linalg.norm(arr - bg_color, axis=2)
    
    # Identify foreground components (core threshold > 25.0)
    core = dist > 25.0
    lbl, n = label(core)
    sizes = [np.sum(lbl == i) for i in range(1, n + 1)]
    top_indices = np.argsort(sizes)[::-1][:2]
    
    comp_a = binary_fill_holes(lbl == (top_indices[0] + 1))
    comp_b = binary_fill_holes(lbl == (top_indices[1] + 1))
    
    if np.sum(comp_a) > np.sum(comp_b):
        ribbon_core = comp_a
        dot_core = comp_b
    else:
        ribbon_core = comp_b
        dot_core = comp_a
        
    # 3. Smooth circular dot mask
    # Dot is an exact circular chrome sphere/disc
    coords_dot = np.argwhere(dot_core)
    cy_dot, cx_dot = coords_dot.mean(axis=0)
    r_dot = 90.5  # Radius in 4x pixels (~22.6px in 1x)
    
    Y, X = np.ogrid[:arr.shape[0], :arr.shape[1]]
    dist_dot = np.sqrt((X - cx_dot) ** 2 + (Y - cy_dot) ** 2)
    # Smooth Hermite transition across 3.0px width
    dot_alpha = np.clip((r_dot + 1.5 - dist_dot) / 3.0, 0.0, 1.0)
    dot_alpha = 3 * dot_alpha ** 2 - 2 * dot_alpha ** 3
    
    # 4. Ribbon mask with Gaussian-smoothed signed distance field
    # Preserves smooth curves without staircase artifacts
    d_in = distance_transform_edt(ribbon_core)
    d_out = distance_transform_edt(~ribbon_core)
    signed = gaussian_filter(d_in - d_out, sigma=0.75)
    ribbon_alpha = np.clip((signed + 1.5) / 3.0, 0.0, 1.0)
    ribbon_alpha = 3 * ribbon_alpha ** 2 - 2 * ribbon_alpha ** 3
    
    # 5. Combine alpha channels
    alpha = np.maximum(ribbon_alpha, dot_alpha)
    
    # 6. Color decontamination and nearest-neighbor metallic propagation
    # Core interior (alpha >= 0.90) contains authentic photographic chrome reflections.
    # Boundary pixels (alpha < 0.90) receive propagated metallic colors to eliminate cream fringing.
    solid_core = (alpha >= 0.90)
    _, indices = distance_transform_edt(~solid_core, return_indices=True)
    propagated_rgb = arr[indices[0], indices[1]]
    
    t_prop = np.clip((0.95 - alpha) / 0.10, 0.0, 1.0)[:, :, None]
    final_fg = (1.0 - t_prop) * arr + t_prop * propagated_rgb
    
    # Near outer transition boundary, ensure perfect grayscale neutrality
    lum_prop = (0.299 * final_fg[:, :, 0] + 0.587 * final_fg[:, :, 1] + 0.114 * final_fg[:, :, 2])[:, :, None]
    t_desat = np.clip((0.90 - alpha) / 0.80, 0.0, 1.0)[:, :, None]
    final_fg = (1.0 - t_desat) * final_fg + t_desat * lum_prop
    
    final_rgb = np.clip(final_fg, 0, 255).astype(np.uint8)
    final_alpha = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    
    # 7. Crop tightly to visible boundary with 8px margin
    y_idx, x_idx = np.where(final_alpha > 0)
    ymin, ymax = y_idx.min(), y_idx.max()
    xmin, xmax = x_idx.min(), x_idx.max()
    
    pad = 8
    ymin_c = max(0, ymin - pad)
    ymax_c = min(arr.shape[0], ymax + pad + 1)
    xmin_c = max(0, xmin - pad)
    xmax_c = min(arr.shape[1], xmax + pad + 1)
    
    rgba_master = np.dstack([final_rgb[ymin_c:ymax_c, xmin_c:xmax_c], final_alpha[ymin_c:ymax_c, xmin_c:xmax_c]])
    master_img = Image.fromarray(rgba_master, "RGBA")
    print(f"Master transparent logo extracted: {master_img.size}")
    
    # Standard target dimensions preserving aspect ratio (2.38:1)
    # 3x: 1200x504
    # 2x: 800x336
    # 1x: 400x168
    size_3x = (1200, 504)
    size_2x = (800, 336)
    size_1x = (400, 168)
    
    img_3x = master_img.resize(size_3x, Image.Resampling.LANCZOS)
    img_2x = master_img.resize(size_2x, Image.Resampling.LANCZOS)
    img_1x = master_img.resize(size_1x, Image.Resampling.LANCZOS)
    
    # 8. Web assets directory
    web_branding_dir = os.path.join(REPO_ROOT, "apps", "web", "public", "branding")
    os.makedirs(web_branding_dir, exist_ok=True)
    
    path_web_1x = os.path.join(web_branding_dir, "lens-symbol.png")
    path_web_2x = os.path.join(web_branding_dir, "lens-symbol@2x.png")
    path_web_3x = os.path.join(web_branding_dir, "lens-symbol@3x.png")
    
    img_1x.save(path_web_1x, "PNG", optimize=True)
    img_2x.save(path_web_2x, "PNG", optimize=True)
    img_3x.save(path_web_3x, "PNG", optimize=True)
    print("Saved web PNG symbols (1x, 2x, 3x).")
    
    # 9. Lossless SVG containing the high-res raster
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
    
    # 10. Generate Favicons and Apple Touch Icon
    def create_app_icon(size, bg_color=(10, 13, 20)):
        canvas = Image.new("RGBA", (size, size), bg_color + (255,))
        mark_w = int(size * 0.76)
        mark_h = int(mark_w * (504 / 1200))
        resized_mark = master_img.resize((mark_w, mark_h), Image.Resampling.LANCZOS)
        offset_x = (size - mark_w) // 2
        offset_y = (size - mark_h) // 2
        canvas.paste(resized_mark, (offset_x, offset_y), resized_mark)
        return canvas

    web_public_dir = os.path.join(REPO_ROOT, "apps", "web", "public")
    
    fav_16 = create_app_icon(16)
    fav_32 = create_app_icon(32)
    fav_48 = create_app_icon(48)
    fav_ico_path = os.path.join(web_public_dir, "favicon.ico")
    fav_16.save(fav_ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    
    fav_32.save(os.path.join(web_branding_dir, "favicon-32x32.png"), "PNG")
    fav_16.save(os.path.join(web_branding_dir, "favicon-16x16.png"), "PNG")
    
    apple_icon = create_app_icon(180)
    apple_icon.save(os.path.join(web_public_dir, "apple-touch-icon.png"), "PNG")
    print("Saved web favicon.ico, apple-touch-icon.png, and PNG favicons.")

    # 11. Mobile Assets Directory
    mobile_branding_dir = os.path.join(REPO_ROOT, "apps", "mobile", "assets", "branding")
    os.makedirs(mobile_branding_dir, exist_ok=True)
    os.makedirs(os.path.join(mobile_branding_dir, "2.0x"), exist_ok=True)
    os.makedirs(os.path.join(mobile_branding_dir, "3.0x"), exist_ok=True)
    
    img_1x.save(os.path.join(mobile_branding_dir, "lens_symbol.png"), "PNG", optimize=True)
    img_2x.save(os.path.join(mobile_branding_dir, "lens_symbol@2x.png"), "PNG", optimize=True)
    img_3x.save(os.path.join(mobile_branding_dir, "lens_symbol@3x.png"), "PNG", optimize=True)
    img_2x.save(os.path.join(mobile_branding_dir, "2.0x", "lens_symbol.png"), "PNG", optimize=True)
    img_3x.save(os.path.join(mobile_branding_dir, "3.0x", "lens_symbol.png"), "PNG", optimize=True)
    print("Saved Flutter mobile branding assets (1x, 2.0x, 3.0x).")
    
    # 12. Android Launcher Icons (mipmap)
    android_res_dir = os.path.join(REPO_ROOT, "apps", "mobile", "android", "app", "src", "main", "res")
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

    # 13. High-Resolution Presentation Preview Card (lens-logo-preview.png)
    card_w, card_h = 1600, 960
    card = Image.new("RGBA", (card_w, card_h), (10, 13, 20, 255))
    draw = ImageDraw.Draw(card)
    
    draw.text((60, 40), "LENS — OFFICIAL BRAND IDENTITY SYSTEM", fill=(241, 245, 249, 255))
    draw.text((60, 68), "Monochromatic Metallic Chrome Ribbon & Dot Mark • Transparent Raster & Vector System", fill=(148, 163, 184, 255))
    
    panel_dark = Image.new("RGBA", (690, 360), (17, 23, 38, 255))
    draw_pd = ImageDraw.Draw(panel_dark)
    draw_pd.rectangle([0, 0, 689, 359], outline=(255, 255, 255, 30), width=1)
    draw_pd.text((24, 20), "DARK INTERFACE (Default)", fill=(148, 163, 184, 255))
    p1_mark = master_img.resize((480, 201), Image.Resampling.LANCZOS)
    panel_dark.paste(p1_mark, (105, 95), p1_mark)
    card.paste(panel_dark, (60, 110))
    
    panel_light = Image.new("RGBA", (690, 360), (255, 255, 255, 255))
    draw_pl = ImageDraw.Draw(panel_light)
    draw_pl.rectangle([0, 0, 689, 359], outline=(0, 0, 0, 30), width=1)
    draw_pl.text((24, 20), "LIGHT INTERFACE", fill=(71, 85, 105, 255))
    panel_light.paste(p1_mark, (105, 95), p1_mark)
    card.paste(panel_light, (850, 110))
    
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
    path_card_root = os.path.join(REPO_ROOT, "assets", "branding", "lens-logo-preview.png")
    path_root_symbol = os.path.join(REPO_ROOT, "assets", "branding", "lens-symbol.png")
    
    card_rgb.save(path_card_web, "PNG", optimize=True)
    card_rgb.save(path_card_root, "PNG", optimize=True)
    img_3x.save(path_root_symbol, "PNG", optimize=True)
    print("Saved preview cards and root branding documentation assets.")
    print("All branding assets generated successfully!")


if __name__ == "__main__":
    main()
