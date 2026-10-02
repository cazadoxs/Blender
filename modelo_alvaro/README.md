# Modelo 3D de Álvaro

Modelo procedural (Blender + Python) hecho a partir de 12 fotos de referencia:
cabeza medida sobre las fotos de frente y perfil con la foto frontal proyectada
como textura, pelo con curvas (degradado en laterales, más largo arriba),
orejas, brazos y manos, camiseta blanca, vaqueros y zapatos negros.

Las fotos y la textura de la cara **no están en el repo** (es público): están en
la carpeta del proyecto (`modelo_alvaro/texturas/cara.png`).

## Uso

```bash
# 1. textura de la cara a partir de la foto frontal (Pillow + numpy)
python3 preparar_textura_cara.py foto_frontal.jpg cara.png

# 2. modelo + imágenes 1920x1080 (frente, 3/4, perfil, espalda y primeros planos)
blender -b -P crear_modelo.py -- --tex cara.png --modo fotos --out render --blend alvaro.blend

# 3. turntable (vuelta de 360°, 144 fotogramas a 24 fps) en GPU
blender -b -P crear_modelo.py -- --tex cara.png --modo turntable --out render --gpu
ffmpeg -framerate 24 -i render/turntable_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 18 turntable.mp4
```

Opciones: `--samples N`, `--pct 50` (resolución), `--vistas cara,frente`, `--frames 1-72`.

## Límites

Con fotos sueltas no se puede sacar un escaneo exacto: la forma de la cabeza
sale de medidas aproximadas y el parecido viene sobre todo de la textura.
La altura (1,78 m) es supuesta. Para un modelo fiel haría falta fotogrametría
(40-60 fotos alrededor con luz uniforme) o un escáner con el móvil.
