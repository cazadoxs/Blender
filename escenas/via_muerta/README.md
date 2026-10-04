# Vía muerta

Corto de terror de 3:17 en **primera persona** (24 fps, formato cine 2,39:1, 1920×804), hecho entero con scripts de Blender 5 y renderizado con Cycles. Es la versión de terror de "Última parada": el mismo monte, túnel, locomotora y viaducto roto, al anochecer, con niebla.

Todo se ve desde los ojos de un excursionista con un frontal: baja por un pozo de ventilación abierto en el monte hasta la vía de un túnel abandonado, camina en la oscuridad, oye algo detrás… y por un hundimiento de la bóveda se asoma el monstruo, una locomotora vieja con ocho patas de araña y una cara de sonrisa enorme. Corre, arranca la locomotora abandonada y huye por el viaducto, hasta que la vía se acaba. Cae mirando al monstruo, que ruge desde el borde; golpe, negro y título.

El cielo es el último resplandor del anochecer y se va apagando a lo largo del corto. La exposición se adapta como los ojos (el monte, el pozo, el túnel solo con el frontal).

El guion está en [GUION.md](GUION.md).

## Momentos

Una sola cámara (los ojos). Cada momento es un marcador en la línea de tiempo; `render.py --prueba` saca un fotograma de cada uno.

| # | Fotogramas | Momento |
|---|---|---|
| 1 | 1–288 | Monte |
| 2 | 289–612 | Camino |
| 3 | 613–744 | Pozo |
| 4 | 745–1143 | Bajada |
| 5 | 1144–1366 | Tunel |
| 6 | 1367–2218 | Camina |
| 7 | 2219–2314 | Para |
| 8 | 2315–2454 | Sonido |
| 9 | 2455–2650 | Mira atras |
| 10 | 2651–2770 | Se asoma |
| 11 | 2771–2979 | Cara |
| 12 | 2980–3030 | Cae |
| 13 | 3031–3217 | Corre |
| 14 | 3218–3357 | Mira atras corriendo |
| 15 | 3358–3630 | Techo |
| 16 | 3631–3704 | Locomotora |
| 17 | 3705–3772 | Regulador |
| 18 | 3773–3933 | Arranca |
| 19 | 3934–4003 | Boca |
| 20 | 4004–4135 | Lo ve |
| 21 | 4136–4229 | Delante |
| 22 | 4230–4353 | Freno |
| 23 | 4354–4379 | Vuelca |
| 24 | 4380–4385 | Caida |
| 25 | 4386–4456 | Ruge |

La imagen se corta a negro en el golpe; después quedan 7.5 s de negro (se oye al monstruo arriba) y 3.5 s con el título (los añade el montaje).

## Archivos

| Archivo | Qué hace |
|---|---|
| `recursos.json` | Texturas, modelos y cielo HDRI de noche (el HDRI no se usa: el cielo del anochecer es procedural) que se usan (con alternativas) |
| `descargar_recursos.py` | Descarga todo lo anterior de Poly Haven y ambientCG (CC0) a `recursos/` |
| `construir_escena.py` | Construye la escena y la animación y guarda `via_muerta.blend` y `timing.json` |
| `up/` | Módulos: túnel, pozo, locomotora y tren, exterior, vegetación, noche, personaje, monstruo, historia (animación), guion (la cámara en primera persona) |
| `render.py` | Render con GPU (OptiX), reanudable, por momentos o entero |
| `prueba_nube.py` | Pruebas rápidas con CPU a baja resolución |
| `audio.py` | Sintetiza `sonido.wav`: noche, túnel, pasos, respiración, el monstruo, el tren y la música |
| `montar_video.py` (`.bat` / `.sh`) | Une fotogramas y sonido con etalonaje, grano, viñeta y el título en `via_muerta.mp4` |

## Pasos en el PC (Windows)

```
cd "C:\Users\Usuario\Documents\Blender claude\Blender\escenas\via_muerta"
set BLENDER="C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

%BLENDER% -b -P descargar_recursos.py            (texturas, modelos y cielo de noche)
%BLENDER% -b -P construir_escena.py
%BLENDER% -b via_muerta.blend -P render.py -- --gpu --prueba   (un fotograma por momento)
%BLENDER% -b via_muerta.blend -P render.py -- --gpu            (la película entera)
%BLENDER% -b -P audio.py
montar_video.bat
```

El render **se puede parar en cualquier momento** (cerrar la ventana o Ctrl+C) y volver a lanzar con el mismo comando: los fotogramas ya hechos no se repiten y sigue donde lo dejó. También se puede hacer por planos con `--plano N` (el momento N). Son 4457 fotogramas.

Si falta algún recurso, la escena se construye igual con materiales y plantas procedurales.

Texturas, modelos y cielo: [Poly Haven](https://polyhaven.com) y [ambientCG](https://ambientcg.com), licencia CC0. El monstruo está modelado desde cero (inspirado en la idea de una locomotora-araña, no es una copia de ningún personaje).
