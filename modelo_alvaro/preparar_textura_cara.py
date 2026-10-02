"""Prepara la textura de la cara a partir de la foto frontal.

Uso: python3 preparar_textura_cara.py foto_frontal.jpg salida.png
Requiere Pillow y numpy. Corrige la orientacion EXIF, recorta la cara y
compensa la iluminacion (divide por una version muy desenfocada de la
luminancia) para que la luz de la foto no quede "pintada" en el modelo.
"""
import sys
import numpy as np
from PIL import Image, ImageOps, ImageFilter

# Recorte en pixeles de la foto original (ya rotada): cara completa con margen
CROP = (300, 200, 2300, 3200)   # x0, y0, x1, y1

def main(src, dst):
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB").crop(CROP)
    a = np.asarray(im).astype(np.float32) / 255.0
    lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
    blur = np.asarray(Image.fromarray((lum * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(90))).astype(np.float32) / 255.0
    target = np.median(lum[900:2200, 500:1500])
    gain = np.clip(target / np.maximum(blur, 0.05), 0.55, 1.6)
    out = a * gain[..., None]
    # el lado derecho de la foto tiene un velo de luz: recuperar contraste local
    detail = out - np.asarray(Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(25))).astype(np.float32) / 255.0
    x = np.linspace(0, 1, out.shape[1])[None, :, None]
    boost = 1.0 + 0.8 * np.clip((x - 0.5) / 0.3, 0, 1)
    out = out + detail * (boost - 1.0)
    # balance de blancos: la foto tiene luz fria; llevar la frente a tono calido
    fr = np.median(out[700:1100, 700:1300].reshape(-1, 3), 0)
    out = out * np.array([1.22 * fr[1] / fr[0], 1.0, 0.86 * fr[1] / fr[2]], np.float32)
    # estirar niveles (la foto esta lavada por el contraluz)
    zona = out[700:2600, 400:1600].reshape(-1, 3)
    lo, hi = np.percentile(zona, 1, 0), np.percentile(zona, 99.5, 0)
    out = (out - lo * 0.85) / (hi - lo * 0.85) * hi
    # leve desaturacion del velo y gamma hacia albedo
    out = np.clip(out, 0, 1) ** 1.08
    Image.fromarray((out * 255).astype(np.uint8)).save(dst)
    borde = np.median(out[1500:2000, 350:500].reshape(-1, 3), 0)
    print("tono mejilla (lineal):", np.round(borde ** 2.2, 3))
    print("ok", dst, out.shape)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
