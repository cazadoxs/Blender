# Palacio abandonado

Recorrido a pie (22 s, 24 fps, formato cine 2,39:1) que cruza la puerta abierta de una muralla en ruinas y entra en un patio invadido por la vegetación, frente a un palacio-castillo abandonado. Todo es procedural: geometría, materiales, vegetación, luz y sonido salen de los scripts, sin texturas ni HDRI externos.

| Archivo | Qué hace |
| --- | --- |
| `build_scene.py` | Construye la escena y la animación de cámara, guarda `palacio_abandonado.blend` y `timing.json` |
| `render.py` | Renderiza con Cycles (GPU con `--gpu`), reanudable |
| `audio.py` | Sintetiza `sonido.wav`: viento, pasos sincronizados, eco del túnel, puerta, pájaros, cuervos y música |
| `montar_video.bat` / `.sh` | Une fotogramas y sonido en `palacio_abandonado.mp4` con viñeta y grano |

Pasos (Blender 5.0):

```
blender -b -P build_scene.py              # opcional: regenera la escena
blender -b palacio_abandonado.blend -P render.py -- --gpu
python3 audio.py                          # opcional: regenera el sonido
montar_video.bat
```
