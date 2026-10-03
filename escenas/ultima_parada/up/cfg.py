"""Medidas y constantes compartidas de la escena (metros, eje Y = dirección de la vía)."""
import math
from mathutils import Vector

FPS = 24
# Túnel
Y0, Y1 = -30.0, 100.0        # fondo derrumbado y boca del túnel
HALF_W = 4.5                 # semiancho interior
WALL_H = 3.5                 # altura de los muros rectos
R_ARCH = 4.5                 # radio de la bóveda (clave a 8 m)
THICK = 1.1                  # espesor de la fábrica
CROWN = WALL_H + R_ARCH
# Vía
BALLAST_TOP = 0.2
SLEEPER_TOP = 0.36
RAIL_TOP = 0.51
GAUGE = 1.435
RAIL_X = GAUGE / 2 + 0.035
# Viaducto
VIA_END = 330.0
GAP = (212.0, 238.0)         # tramo hundido
VALLEY_Z = -72.0
# Sol: bajo, al fondo del valle (+Y), un poco hacia -X
SUN_ELEV = math.radians(16)
SUN_AZ = math.radians(-7)    # giro respecto a +Y
SUN_DIR = Vector((math.sin(SUN_AZ) * math.cos(SUN_ELEV), math.cos(SUN_AZ) * math.cos(SUN_ELEV), math.sin(SUN_ELEV)))  # hacia el sol
# Locomotora
LOCO_FRONT = 57.0            # topes delanteros
CAB_Y = 47.4                 # centro de la cabina
TREE_POS = (0.25, 46.9)      # el árbol que atraviesa la cabina

def vault_z(x):
    """Altura del intradós de la bóveda en x (sin el muro)."""
    ax = min(abs(x), R_ARCH - 1e-6)
    return WALL_H + math.sqrt(R_ARCH ** 2 - ax ** 2)
