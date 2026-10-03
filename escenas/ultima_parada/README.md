# Última parada

Cortometraje de 75 segundos (24 fps, formato cine 2,39:1, 1920×804) hecho entero con scripts de Blender 5.0 y renderizado con Cycles.

Un túnel ferroviario abandonado hace décadas. La bóveda se ha hundido en tres sitios y por los huecos entra el sol del atardecer en haces de luz cargados de polvo. Las raíces atraviesan el ladrillo y gotean sobre la vía. En medio del túnel duerme una locomotora de vapor 030 de RENFE, comida por el óxido y la hiedra, con un árbol que ha crecido dentro de la cabina y sale por el techo hacia la luz. La cámara recorre la vía, se acerca a la máquina y después echa a volar hacia la boca del túnel, que da a un viaducto de piedra roto sobre un valle con niebla, río y bosque.

## Planos

| # | Fotogramas | Plano |
|---|---|---|
| 1 | 1–144 | **Gota.** Macro a ras de un charco entre las traviesas. Una gota se forma en la punta de una raíz y cae en el haz de luz. |
| 2 | 145–432 | **Vía.** Travelling a ras de los carriles bajo los haces de luz; al fondo, la silueta de la locomotora. |
| 3 | 433–672 | **Locomotora.** Lateral a lo largo de la caldera hasta la cabina y el árbol que la atraviesa. |
| 4 | 673–816 | **Rueda.** Detalle de las ruedas motrices y las bielas con musgo. |
| 5 | 817–936 | **Placa.** Panorámica vertical de la placa 030-2471 al farol. |
| 6 | 937–1560 | **Hacia la luz.** De la locomotora a la boca del túnel atravesando la cortina de lianas; al salir, la cámara sube como una grúa sobre el viaducto roto y una bandada de pájaros despega del valle. |
| 7 | 1561–1800 | **Última parada.** Plano general desde el otro lado del valle: la boca del túnel iluminada por el sol bajo. Título. |

## Archivos

| Archivo | Qué hace |
|---|---|
| `recursos.json` | Lista de texturas, modelos y cielo HDRI que se usan (con alternativas) |
| `descargar_recursos.py` | Descarga todo lo anterior de Poly Haven y ambientCG (CC0) a `recursos/` |
| `construir_escena.py` | Construye la escena completa y guarda `ultima_parada.blend` y `timing.json` |
| `up/` | Módulos de la escena: túnel, locomotora, vegetación, exterior, luz, cámaras, materiales |
| `render.py` | Render con GPU (OptiX), reanudable, por planos o entero |
| `prueba_nube.py` | Pruebas rápidas con CPU a baja resolución |
| `audio.py` | Sintetiza `sonido.wav`: ambientes, efectos y la música |
| `montar_video.bat` / `.sh` | Une fotogramas y sonido con etalonaje, grano, viñeta y título en `ultima_parada.mp4` |

## Pasos en el PC (Windows)

```
cd "C:\Users\Usuario\Documents\Blender claude\Blender\escenas\ultima_parada"
set BLENDER="C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

%BLENDER% -b -P descargar_recursos.py            (1,5–3 GB de texturas y modelos)
%BLENDER% -b -P construir_escena.py
%BLENDER% -b ultima_parada.blend -P render.py -- --gpu --prueba   (un fotograma por plano)
%BLENDER% -b ultima_parada.blend -P render.py -- --gpu            (la película entera)
%BLENDER% -b -P audio.py
montar_video.bat
```

El render se puede cortar en cualquier momento y volver a lanzar con el mismo comando: sigue donde lo dejó. También se puede hacer por planos con `--plano N`. Los fotogramas (PNG de 8 bits) ocupan unos 3 MB cada uno, unos 6 GB en total.

Si falta algún recurso, la escena se construye igual con materiales y plantas procedurales.

Texturas, modelos y cielo: [Poly Haven](https://polyhaven.com) y [ambientCG](https://ambientcg.com), licencia CC0.
