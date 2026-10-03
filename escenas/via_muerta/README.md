# Vía muerta

Corto de terror de 3:21 (24 fps, formato cine 2,39:1, 1920×804) hecho entero con scripts de Blender 5.0 y renderizado con Cycles. Es la versión nocturna de "Última parada": el mismo monte, túnel, locomotora y viaducto roto, pero de noche, con niebla y luna.

Un excursionista con un frontal baja por un pozo de ventilación abierto en el monte hasta la vía de un túnel abandonado. Camina en la oscuridad, oye algo detrás… y por un hundimiento de la bóveda se asoma el monstruo: una locomotora vieja con ocho patas de araña y una cara de sonrisa enorme. Lo persigue por el suelo, las paredes y el techo del túnel; el excursionista arranca la locomotora abandonada y huye por el viaducto, hasta que la vía se acaba.

El guion completo, plano a plano, está en [GUION.md](GUION.md).

## Planos

| # | Fotogramas | Plano |
|---|---|---|
| 1 | 1–192 | Monte |
| 2 | 193–372 | Camino |
| 3 | 373–636 | Alcantarilla |
| 4 | 637–744 | Pozo |
| 5 | 745–924 | Bajada |
| 6 | 925–1044 | Peldanos |
| 7 | 1045–1172 | Tunel |
| 8 | 1173–1402 | Nada |
| 9 | 1403–1630 | Camina |
| 10 | 1631–1690 | Traviesas |
| 11 | 1691–2038 | Luna |
| 12 | 2039–2230 | Respira |
| 13 | 2231–2454 | Sonido |
| 14 | 2455–2694 | Detras |
| 15 | 2695–2785 | Se asoma |
| 16 | 2786–2871 | Cara |
| 17 | 2872–2997 | Miedo |
| 18 | 2998–3118 | Cae |
| 19 | 3119–3229 | Corre |
| 20 | 3230–3321 | Paredes |
| 21 | 3322–3429 | Techo |
| 22 | 3430–3538 | Locomotora |
| 23 | 3539–3625 | Tender |
| 24 | 3626–3694 | Cabina |
| 25 | 3695–3732 | Regulador |
| 26 | 3733–3820 | Ruedas |
| 27 | 3821–3900 | Arranca |
| 28 | 3901–3967 | Boca |
| 29 | 3968–4020 | Mira atras |
| 30 | 4021–4121 | Lo ve |
| 31 | 4122–4221 | Delante |
| 32 | 4222–4295 | Freno |
| 33 | 4296–4408 | Caida |
| 34 | 4409–4492 | Abismo |
| 35 | 4493–4744 | Borde |

Después, 3.5 s de negro con el título (los añade el montaje).

## Archivos

| Archivo | Qué hace |
|---|---|
| `recursos.json` | Texturas, modelos y cielo HDRI de noche que se usan (con alternativas) |
| `descargar_recursos.py` | Descarga todo lo anterior de Poly Haven y ambientCG (CC0) a `recursos/` |
| `construir_escena.py` | Construye la escena y la animación y guarda `via_muerta.blend` y `timing.json` |
| `up/` | Módulos: túnel, pozo, locomotora y tren, exterior, vegetación, noche, personaje, monstruo, historia (animación), guion (cámaras) |
| `render.py` | Render con GPU (OptiX), reanudable, por planos o entero |
| `prueba_nube.py` | Pruebas rápidas con CPU a baja resolución |
| `audio.py` | Sintetiza `sonido.wav`: noche, túnel, pasos, respiración, el monstruo, el tren y la música |
| `montar_video.py` (`.bat` / `.sh`) | Une fotogramas y sonido con etalonaje de noche, grano, viñeta y el título en `via_muerta.mp4` |

## Pasos en el PC (Windows)

```
cd "C:\Users\Usuario\Documents\Blender claude\Blender\escenas\via_muerta"
set BLENDER="C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

%BLENDER% -b -P descargar_recursos.py            (texturas, modelos y cielo de noche)
%BLENDER% -b -P construir_escena.py
%BLENDER% -b via_muerta.blend -P render.py -- --gpu --prueba   (un fotograma por plano)
%BLENDER% -b via_muerta.blend -P render.py -- --gpu            (la película entera)
%BLENDER% -b -P audio.py
montar_video.bat
```

El render **se puede parar en cualquier momento** (cerrar la ventana o Ctrl+C) y volver a lanzar con el mismo comando: los fotogramas ya hechos no se repiten y sigue donde lo dejó. También se puede hacer por planos con `--plano N`. Son 4745 fotogramas.

Si falta algún recurso, la escena se construye igual con materiales y plantas procedurales.

Texturas, modelos y cielo: [Poly Haven](https://polyhaven.com) y [ambientCG](https://ambientcg.com), licencia CC0. El monstruo está modelado desde cero (inspirado en la idea de una locomotora-araña, no es una copia de ningún personaje).
