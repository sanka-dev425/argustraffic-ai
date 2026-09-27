import os
from PIL import Image

def process_logo():
    src_img_path = r"C:\Users\rampa\.gemini\antigravity-ide\brain\9864c740-a105-46fa-85e5-f45362983e57\.user_uploaded\media_1790517469382.png"
    if not os.path.exists(src_img_path):
        raise FileNotFoundError(f"Source image not found: {src_img_path}")

    os.makedirs("assets", exist_ok=True)
    os.makedirs("src/web/static/img", exist_ok=True)

    img = Image.open(src_img_path).convert("RGBA")
    
    # 1. Save master high-res PNG
    img.save("assets/logo.png", format="PNG")
    img.save("src/web/static/img/logo.png", format="PNG")
    print("Saved assets/logo.png and src/web/static/img/logo.png")

    # 2. Save multi-resolution Windows .ico
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save("assets/app_icon.ico", format="ICO", sizes=icon_sizes)
    img.save("src/web/static/favicon.ico", format="ICO", sizes=icon_sizes)
    print("Saved assets/app_icon.ico and src/web/static/favicon.ico")

    # 3. Create Inno Setup Wizard BMPs (RGB mode with dark sleek background)
    # WizardSmallImageFile (55x58)
    small_bg = Image.new("RGB", (55, 58), (10, 15, 29))
    logo_small = img.resize((48, 48), Image.Resampling.LANCZOS)
    small_bg.paste(logo_small, (3, 5), logo_small)
    small_bg.save("assets/wizard_small.bmp", format="BMP")

    # WizardImageFile (164x314)
    large_bg = Image.new("RGB", (164, 314), (7, 11, 20))
    logo_large = img.resize((140, 140), Image.Resampling.LANCZOS)
    large_bg.paste(logo_large, (12, 87), logo_large)
    large_bg.save("assets/wizard_large.bmp", format="BMP")
    print("Saved assets/wizard_small.bmp and assets/wizard_large.bmp")

if __name__ == "__main__":
    process_logo()
