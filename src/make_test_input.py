"""Draw a simple synthetic cartoon character as a pipeline test input."""
import sys
from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else "inputs/test_character.png"
img = Image.new("RGB", (400, 600), "white")
d = ImageDraw.Draw(img)
# Legs / shoes
d.rectangle([165, 400, 195, 520], fill=(40, 40, 90))
d.rectangle([205, 400, 235, 520], fill=(40, 40, 90))
d.ellipse([150, 505, 200, 535], fill=(20, 20, 20))
d.ellipse([200, 505, 250, 535], fill=(20, 20, 20))
# Torso
d.rounded_rectangle([140, 230, 260, 410], 25, fill=(30, 100, 200))
# Folded arms
d.line([150, 300, 250, 340], fill=(240, 200, 160), width=22)
d.line([250, 300, 150, 345], fill=(235, 190, 150), width=22)
# Head and hair
d.ellipse([145, 60, 255, 190], fill=(240, 200, 160))
d.pieslice([140, 40, 260, 150], 180, 360, fill=(90, 50, 20))
d.ellipse([175, 115, 190, 135], fill=(0, 0, 0))
d.ellipse([210, 115, 225, 135], fill=(0, 0, 0))
img.save(OUT)
print("wrote", OUT)
