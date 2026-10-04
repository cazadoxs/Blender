"""
Banda sonora de "Vía muerta", sintetizada desde cero (solo numpy).

Lee timing.json (planos, instantes clave, cada pisada del personaje, cada peldaño, cada
apoyo de las patas del monstruo y cada golpe de vapor de la locomotora) y genera sonido.wav
(48 kHz, estéreo):
  noche en el monte (viento, grillos, un búho), el hueco del túnel con goteos, la respiración
  del personaje (tranquila, contenida, jadeos), pasos en tierra, grava y chapa, los peldaños de
  hierro, el monstruo (tac-tac de las patas, chirridos de metal, gruñidos y su grito: un silbato
  de vapor desafinado con un rugido), la locomotora (purga, soplidos, traqueteo, freno), la caída
  y un estruendo lejano; y una música de tensión (graves que suben, latidos, golpes, silencios).

Uso: python audio.py   (también vale: blender -b -P audio.py)
"""
import json, os, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000
T = json.load(open(os.path.join(HERE, 'timing.json'), encoding='utf-8'))
EV = T['eventos']
TR = T['tren']
T_TITLE = T['titulo']['inicio']
T_END = T_TITLE + T['titulo']['duracion']
DUR = T_END + 1.5
N = int(SR * DUR)
t = np.arange(N) / SR
rng = np.random.default_rng(23)


# --------------------------------------------------------------------- utilidades
def spectral(x, gain_fn):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X * gain_fn(np.maximum(f, 1e-3)), len(x))


def lowpass(x, fc, order=2):
    return spectral(x, lambda f: 1 / np.sqrt(1 + (f / fc) ** (2 * order)))


def highpass(x, fc, order=2):
    return spectral(x, lambda f: 1 / np.sqrt(1 + (fc / f) ** (2 * order)))


def bandpass(x, f0, q):
    return spectral(x, lambda f: np.exp(-0.5 * (np.log2(f / f0) * q) ** 2))


def ctrl(points, n=N):
    ts, vs = zip(*points)
    return np.interp(np.arange(n) / SR, ts, vs)


def smoothstep(a, b, x):
    u = np.clip((x - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


def random_ctrl(step, lo, hi, n=N):
    k = int(n / SR / step) + 3
    c = ctrl([(i * step, rng.uniform(lo, hi)) for i in range(k)], n)
    return lowpass(c, 1.0 / step)


def pan(x, p):
    a = (p + 1) * np.pi / 4
    return np.cos(a) * x, np.sin(a) * x


def place(bus, sig, t0, p=0.0, gain=1.0):
    i = int(t0 * SR)
    if i >= N or i + len(sig) <= 0:
        return
    if i < 0:
        sig = sig[-i:]
        i = 0
    sig = sig[:N - i] * gain
    l, r = pan(sig, p)
    bus[0, i:i + len(sig)] += l
    bus[1, i:i + len(sig)] += r


def reverb(bus, rt, wet, predelay=0.02, seed=1, tone=5000):
    r2 = np.random.default_rng(seed)
    n = int(rt * SR * 1.2)
    tt = np.arange(n) / SR
    out = np.zeros_like(bus)
    m = 1 << int(np.ceil(np.log2(bus.shape[1] + n)))
    for ch in range(2):
        ir = r2.standard_normal(n) * np.exp(-6.9 * tt / rt)
        ir = lowpass(ir, tone)
        ir[: int(predelay * SR)] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        y = np.fft.irfft(np.fft.rfft(bus[ch], m) * np.fft.rfft(ir, m), m)[: bus.shape[1]]
        out[ch] = bus[ch] * (1 - wet) + y * wet
    return out


def Z():
    return np.zeros((2, N))


def norm(x):
    return x / (np.abs(x).max() + 1e-9)




# --------------------------------------------------------------------- dónde está (para la acústica)
T_IN = EV['corte_bajada'] + 6.0          # ya dentro del pozo / túnel
T_OUT = EV['tren_t_boca']
inside = smoothstep(EV['corte_bajada'], T_IN, t) * (1 - smoothstep(T_OUT - 0.5, T_OUT + 1.0, t))
outside = 1 - inside


def muffle(bus, env, fc=600):
    out = np.empty_like(bus)
    for ch in range(2):
        out[ch] = bus[ch] * (1 - env) + lowpass(bus[ch], fc) * env
    return out


def env_at(points):
    return ctrl(points)


def train_s(tt):
    """Avance de la locomotora (copia de tren.s_of_t)."""
    p = TR
    if tt <= p['t1']:
        return 0.0
    if tt <= p['t1'] + p['ta']:
        u = tt - p['t1']
        return 0.5 * p['accel'] * u * u
    if tt <= p['tb']:
        return p['sa'] + p['v_max'] * (tt - p['t1'] - p['ta'])
    if tt <= p['te']:
        u = tt - p['tb']
        return p['s_brake'] + p['v_max'] * u - 0.5 * p['decel'] * u * u
    return p['s_edge'] + p['v_edge'] * (tt - p['te'])


# --------------------------------------------------------------------- noche y túnel
def night():
    """Viento entre los árboles, grillos y un búho (fuera); muy apagado al bajar."""
    bus = Z()
    gust = random_ctrl(2.2, 0.25, 1.0)
    for ch in range(2):
        w = norm(lowpass(highpass(np.cumsum(rng.standard_normal(N)), 25), 700))
        leaves = norm(bandpass(rng.standard_normal(N), 3200 + 400 * ch, 1.0))
        bus[ch] = w * gust * 0.7 + leaves * gust ** 2 * 0.12
    # grillos: trinos de 4.6 kHz, unos pocos individuos
    for k in range(5):
        f = rng.uniform(4300, 5200)
        p = rng.uniform(-0.9, 0.9)
        rate = rng.uniform(14, 22)
        tt0 = rng.uniform(0, 1)
        L = int(0.35 * SR)
        x = np.arange(L) / SR
        chirp = np.sin(2 * np.pi * f * x) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * rate * x))) * np.sin(np.pi * x / 0.35)
        while tt0 < DUR - 1:
            place(bus, chirp, tt0, p, rng.uniform(0.02, 0.05))
            tt0 += rng.uniform(0.6, 1.4)
    # búho
    for t0 in (3.0, 11.5, 19.0, EV['tren_t_boca'] + 4.0):
        for k, (f, d) in enumerate(((390, 0.35), (360, 0.22), (370, 0.7))):
            L = int(d * SR)
            x = np.arange(L) / SR
            hoot = np.sin(2 * np.pi * f * x * (1 - 0.04 * x / d)) * np.sin(np.pi * x / d) ** 1.5
            hoot += 0.25 * bandpass(rng.standard_normal(L), f * 2, 2) * np.sin(np.pi * x / d)
            place(bus, hoot, t0 + (0, 0.5, 0.95)[k], -0.5, 0.05)
    bus = reverb(bus, 1.6, 0.35, seed=31)
    deep = muffle(bus, inside, 500)
    return deep * (outside + inside * 0.15)


def tunnel_tone():
    bus = Z()
    for ch in range(2):
        b = norm(lowpass(highpass(np.cumsum(rng.standard_normal(N)), 16), 180))
        bus[ch] = b
    hollow = norm(bandpass(rng.standard_normal(N), 120, 4)) * random_ctrl(2.5, 0.4, 1.0)
    bus += hollow * 0.45
    return bus * inside * random_ctrl(3.0, 0.7, 1.0)


def drip_sound(f_hi=2600, dur=0.12):
    L = int(dur * SR)
    tt = np.arange(L) / SR
    f = 700 + f_hi * np.minimum(1, tt / 0.025)
    d = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.022)
    click = rng.standard_normal(L) * np.exp(-tt / 0.0012) * 0.4
    return d + click


def drips():
    bus = Z()
    tt0 = EV['corte_bajada']
    while tt0 < T_OUT:
        place(bus, drip_sound(rng.uniform(1600, 3200)), tt0, rng.uniform(-0.8, 0.8), rng.uniform(0.06, 0.2))
        tt0 += rng.uniform(1.0, 4.0)
    # la gota que cae por el pozo en el plano subjetivo
    place(bus, drip_sound(3000, 0.18), EV['llega_pozo'] + 3.2, 0.0, 0.25)
    return reverb(bus, 3.2, 0.7, predelay=0.05, seed=32)


# --------------------------------------------------------------------- el personaje
def breath(t0, t1, period, gain, rough=0.0, p=0.0, bus=None):
    """Respiración: inspiraciones y espiraciones de ruido filtrado (a través de la braga)."""
    tt0 = t0
    k = 0
    while tt0 < t1:
        per = period * rng.uniform(0.85, 1.15)
        for part, (frac, fc, g) in enumerate(((0.42, 1500, 0.7), (0.5, 900, 1.0))):
            d = per * frac
            L = int(d * SR)
            x = np.arange(L) / SR
            env = np.sin(np.pi * x / d) ** (1.5 if part else 1.0)
            n = bandpass(rng.standard_normal(L), fc * rng.uniform(0.9, 1.1), 0.9)
            if rough > 0:
                n += rough * bandpass(rng.standard_normal(L), 260, 2.5) * (0.5 + 0.5 * np.sin(2 * np.pi * 37 * x))
            place(bus, norm(n * env), tt0 + (0 if part == 0 else per * 0.45), p, gain * g)
        tt0 += per
        k += 1


def breathing():
    bus = Z()
    b = lambda a, c, per, g, r=0.0: breath(a, c, per, g, r, bus=bus)
    b(0.0, EV['corte_bajada'], 3.6, 0.10)
    b(EV['corte_bajada'], EV['pisa_suelo'], 2.6, 0.13)            # bajando: esfuerzo
    b(EV['pisa_suelo'], EV['ruido1'], 3.4, 0.10)
    b(EV['ruido1'], EV['asoma'], 4.5, 0.05)                        # contiene la respiración
    b(EV['asoma'] + 6.5, EV['grito'] - 1.6, 1.3, 0.12, 0.3)          # respira deprisa, tiembla
    # silencio total antes del grito; después, jadeos corriendo
    b(EV['corre'], EV['llega_loco'], 0.55, 0.2, 0.5)
    b(EV['llega_loco'], EV['tren_t_boca'] + 1.0, 0.75, 0.17, 0.4)
    b(EV['tren_t_boca'] + 1.0, EV['tren_t_tip'], 0.9, 0.13, 0.4)
    b(EV['tren_t_tip'], EV['tren_t_impacto'], 0.42, 0.24, 0.7)       # cae: jadea
    # el grito ahogado al verlo y al ver que se acaba la vía
    for t0, g in ((EV['asoma'] + 6.6, 0.25), (EV['ve_monstruo'], 0.2), (EV['mira_delante'] + 0.4, 0.25)):
        L = int(0.7 * SR)
        x = np.arange(L) / SR
        gasp = bandpass(rng.standard_normal(L), 1100, 0.8) * np.sin(np.pi * x / 0.7) ** 0.6 * np.exp(-x / 0.4)
        place(bus, norm(gasp), t0, 0.0, g)
    return reverb(bus, 2.4, 0.25 * 1.0, seed=33) * (1 - 0.5 * smoothstep(EV['tren_t_tip'], EV['tren_t_tip'] + 1, t))


def footstep(kind):
    L = int(0.22 * SR)
    x = np.arange(L) / SR
    if kind == 'chapa':
        s = sum(np.sin(2 * np.pi * f * x) * np.exp(-x / d) for f, d in ((310, 0.09), (742, 0.05), (1530, 0.03)))
        return norm(s + 0.3 * rng.standard_normal(L) * np.exp(-x / 0.004))
    thump = lowpass(rng.standard_normal(L), 300) * np.exp(-x / 0.03)
    crunch = highpass(rng.standard_normal(L), 1800) * np.exp(-x / 0.05) * (0.4 + 0.6 * (rng.random(L) > 0.7))
    return norm(thump * 1.2 + crunch * 0.6)


def steps():
    bus = Z()
    for tt0, kind in T['pasos']:
        g = {'andar': 0.32, 'paso': 0.25, 'correr': 0.55, 'chapa': 0.5}.get(kind, 0.3)
        place(bus, footstep(kind), tt0, rng.uniform(-0.15, 0.15), g * rng.uniform(0.8, 1.1))
    for tt0, kind in T['peldanos']:
        L = int(0.5 * SR)
        x = np.arange(L) / SR
        s = sum(a * np.sin(2 * np.pi * f * rng.uniform(0.97, 1.03) * x) * np.exp(-x / d)
                for f, a, d in ((612, 1.0, 0.12), (1457, 0.6, 0.07), (2311, 0.4, 0.05), (3890, 0.2, 0.03)))
        scrape = bandpass(rng.standard_normal(L), 2500, 1.2) * np.exp(-x / 0.06) * 0.3
        place(bus, norm(s + scrape), tt0, rng.uniform(-0.2, 0.2), 0.28 if kind == 'pie' else 0.16)
    wet = reverb(bus, 2.8, 0.45, seed=34)
    return wet * inside + bus * outside


# --------------------------------------------------------------------- el monstruo
def whistle(dur, f0, bend, gain_noise=0.6):
    """Silbato de vapor desafinado: tres tubos con armónicos, glissando, y el soplido."""
    L = int(dur * SR)
    x = np.arange(L) / SR
    out = np.zeros(L)
    for ratio, a in ((1.0, 1.0), (1.19, 0.8), (1.42, 0.7), (0.5, 0.4)):
        f = f0 * ratio * (1 + bend * np.sin(np.pi * x / dur) - 0.06 * x / dur) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * x))
        ph = 2 * np.pi * np.cumsum(f) / SR
        out += a * (np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph))
    air = bandpass(rng.standard_normal(L), f0 * 2.4, 0.7) * gain_noise
    env = np.minimum(1, x / 0.08) * np.minimum(1, (dur - x) / 0.5)
    return norm(out * (1 + 0.3 * lowpass(rng.standard_normal(L), 12) / 0.05) + air * 3) * np.clip(env, 0, 1)


def roar(dur, f0=62):
    L = int(dur * SR)
    x = np.arange(L) / SR
    f = f0 * (1 + 0.25 * np.sin(np.pi * x / dur)) * (1 + 0.03 * lowpass(rng.standard_normal(L), 20) / 0.05)
    ph = 2 * np.pi * np.cumsum(f) / SR
    saw = sum(np.sin(k * ph) / k for k in range(1, 40))
    grit = bandpass(rng.standard_normal(L), 420, 0.7) * (0.6 + 0.4 * np.sin(2 * np.pi * 23 * x))
    env = np.minimum(1, x / 0.15) * np.minimum(1, (dur - x) / 0.6)
    return norm(lowpass(saw, 1800) + grit * 1.4) * np.clip(env, 0, 1)


def scream(t0, dur, bus, gain=1.0, p=0.0):
    place(bus, whistle(dur, 520, 0.12), t0, p, 0.55 * gain)
    place(bus, roar(dur * 0.95), t0 + 0.05, p, 0.75 * gain)
    L = int((dur + 1) * SR)
    x = np.arange(L) / SR
    steam = highpass(rng.standard_normal(L), 2500) * np.minimum(1, x / 0.1) * np.exp(-x / (dur * 0.7))
    place(bus, norm(steam), t0, p, 0.25 * gain)


def creak(dur, f0, f1):
    L = int(dur * SR)
    x = np.arange(L) / SR
    f = np.geomspace(f0, f1, L)
    pulses = (np.sin(2 * np.pi * np.cumsum(rng.uniform(20, 45) * np.ones(L)) / SR) > 0.6).astype(float)
    ph = 2 * np.pi * np.cumsum(f) / SR
    tone = (np.sin(ph) + 0.6 * np.sin(2.7 * ph)) * (0.3 + 0.7 * pulses)
    return norm(tone + 0.4 * bandpass(rng.standard_normal(L), f0 * 5, 2)) * np.sin(np.pi * x / dur) ** 1.2


def monster():
    bus = Z()
    # el primer ruido, lejano, detrás: un chirrido de hierro
    place(bus, creak(2.4, 180, 120), EV['ruido1'], -0.3, 0.35)
    place(bus, creak(1.6, 260, 210), EV['ruido1'] + 4.5, -0.2, 0.2)
    # se asoma: crujidos de chapa, un gruñido grave y aire por los dientes
    a = EV['asoma']
    place(bus, creak(3.0, 110, 85), a + 1.0, 0.0, 0.3)
    place(bus, roar(4.0, 48) * 0.6, a + 6.3, 0.0, 0.35)
    place(bus, whistle(3.0, 300, 0.05, 1.5) * 0.4, a + 7.0, 0.0, 0.15)
    place(bus, creak(2.0, 140, 100), a + 10.5, 0.0, 0.25)
    # los gritos
    scream(EV['grito'], 2.0, bus, 1.0)
    scream(EV['ruge'], 2.6, bus, 1.1)
    scream(EV['regulador'] + 0.3, 1.6, bus, 0.8, -0.4)
    scream(EV['grito_final'], 2.8, bus, 1.0)
    place(bus, roar(3.0, 40), EV['mira_camara'] + 1.2, 0.0, 0.45)
    # el golpe al caer al suelo del túnel
    place(bus, norm(lowpass(rng.standard_normal(int(1.2 * SR)), 180) * np.exp(-np.arange(int(1.2 * SR)) / SR / 0.25)),
          EV['aterriza'], 0.0, 0.9)
    # el tac-tac de las patas: punta dura sobre ladrillo, con un golpe sordo
    for tt0 in T['patas']:
        if tt0 < a or (EV['monstruo_borde'] + 1 < tt0):
            continue
        L = int(0.12 * SR)
        x = np.arange(L) / SR
        tick = bandpass(rng.standard_normal(L), rng.uniform(2200, 3800), 2.5) * np.exp(-x / 0.008)
        thud = lowpass(rng.standard_normal(L), 160) * np.exp(-x / 0.03)
        place(bus, norm(tick * 1.0 + thud * 0.6), tt0, rng.uniform(-0.6, 0.6), 0.22)
    wet = reverb(bus, 3.0, 0.5, seed=35)
    return wet * inside + reverb(bus, 1.2, 0.25, seed=36) * outside


# --------------------------------------------------------------------- la locomotora
def train():
    bus = Z()
    tr = EV['regulador']
    L = int(4.0 * SR)
    x = np.arange(L) / SR
    # regulador: golpe metálico y siseo creciente; purga de los cilindros
    place(bus, footstep('chapa'), tr, 0.1, 0.5)
    hiss = highpass(rng.standard_normal(L), 2000) * np.minimum(1, x / 0.3) * np.exp(-x / 1.4)
    place(bus, norm(hiss), tr + 0.4, -0.5, 0.45)
    place(bus, norm(hiss), tr + 0.45, 0.5, 0.45)
    # puerta del hogar y el fuego que se aviva
    fire = lowpass(rng.standard_normal(N), 500) * (rng.random(N) > 0.995) * 6 + lowpass(rng.standard_normal(N), 250)
    fire = norm(fire) * ctrl([(0, 0), (tr - 1.4, 0), (tr + 0.5, 0.25), (EV['tren_t_caida'], 0.25), (EV['tren_t_caida'] + 0.5, 0)])
    bus[0] += fire * 0.6
    bus[1] += fire * 0.6
    # soplidos por la chimenea
    for tt0 in T['ruedas']:
        Lc = int(0.32 * SR)
        xc = np.arange(Lc) / SR
        chuff = bandpass(rng.standard_normal(Lc), 900, 0.6) * np.exp(-xc / 0.09) + lowpass(rng.standard_normal(Lc), 120) * np.exp(-xc / 0.05)
        place(bus, norm(chuff), tt0, 0.0, 0.5)
    # traqueteo: dos golpes por cada junta de carril (cada 12 m), ruedas que ruedan
    s_prev = 0.0
    tt0 = TR['t1']
    while tt0 < EV['tren_t_tip']:
        s = train_s(tt0)
        if int(s / 12.0) != int(s_prev / 12.0):
            for k, dy in enumerate((0.0, 2.1, 5.0, 7.1, 10.5, 12.6)):
                v = max(0.5, (train_s(tt0 + 0.05) - s) / 0.05)
                Lk = int(0.1 * SR)
                xk = np.arange(Lk) / SR
                clack = bandpass(rng.standard_normal(Lk), 1600, 1.5) * np.exp(-xk / 0.012) + lowpass(rng.standard_normal(Lk), 200) * np.exp(-xk / 0.03)
                place(bus, norm(clack), tt0 + dy / v, rng.uniform(-0.3, 0.3), 0.3)
        s_prev = s
        tt0 += 1 / 200
    # freno: chirrido que sube hasta que se bloquean las ruedas
    tb, te = TR['tb'], TR['te']
    Lb = int((te - tb + 1.8) * SR)
    xb = np.arange(Lb) / SR
    f = 3300 + 400 * np.sin(2 * np.pi * 0.7 * xb) + 120 * lowpass(rng.standard_normal(Lb), 15) / 0.05
    squeal = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.5 * np.sin(2 * np.pi * np.cumsum(f * 1.51) / SR)
    grind = bandpass(rng.standard_normal(Lb), 2000, 0.8)
    envb = np.minimum(1, xb / 0.6) * np.minimum(1, (Lb / SR - xb) / 0.5)
    place(bus, norm(squeal * 0.5 + grind) * envb, tb + 0.3, 0.1, 0.4)
    # el vuelco: crujido enorme de hierro y el viento de la caída
    place(bus, creak(2.5, 70, 40), EV['tren_t_tip'], 0.0, 0.8)
    Lf = int((EV['tren_t_impacto'] - EV['tren_t_caida'] + 0.5) * SR)
    xf = np.arange(Lf) / SR
    whoosh = bandpass(rng.standard_normal(Lf), 500, 0.5) * (xf / xf[-1]) ** 1.5
    place(bus, norm(whoosh), EV['tren_t_caida'], 0.0, 0.5)
    bus = reverb(bus, 2.0, 0.3, seed=37)
    # dentro del túnel suena más encerrado
    return muffle(bus, inside * 0.3, 2500)


# --------------------------------------------------------------------- música de tensión
NOTE = {'C': 0, 'Db': 1, 'D': 2, 'Eb': 3, 'E': 4, 'F': 5, 'Gb': 6, 'F#': 6, 'G': 7, 'Ab': 8, 'A': 9, 'Bb': 10, 'B': 11, 'C#': 1}


def hz(name):
    n, octv = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((NOTE[n] + 12 * (octv + 1) - 69) / 12)


def saw_voice(f, n, detune=0.0, vib=0.0015):
    tt = np.arange(n) / SR
    ff = f * 2 ** (detune / 1200) * (1 + vib * np.sin(2 * np.pi * 4.6 * tt + rng.uniform(0, 6)))
    ph = 2 * np.pi * np.cumsum(ff) / SR + rng.uniform(0, 6.28)
    s = np.zeros(n)
    for k in range(1, int(min(30, 6000 / f)) + 1):
        s += np.sin(k * ph) / k
    return s


def pad(notes, t0, t1, gain, fc, a=1.8, r=2.2, choir=False, fc_end=None):
    i0 = int(max(0, t0 - 0.1) * SR)
    i1 = min(N, int((t1 + r) * SR))
    n = i1 - i0
    tt = np.arange(n) / SR + i0 / SR
    env = smoothstep(t0, t0 + a, tt) * (1 - smoothstep(t1, t1 + r, tt))
    L = np.zeros(n)
    R = np.zeros(n)
    for name in notes:
        for dc, p in ((-8, -0.6), (0, 0.0), (8, 0.6)):
            v = saw_voice(hz(name), n, dc, 0.003 if choir else 0.0015)
            l, rr = pan(v, p)
            L += l
            R += rr
    out = Z()
    for ch, x in enumerate((L, R)):
        if choir:
            x = bandpass(x, 650, 2.0) + 0.75 * bandpass(x, 1150, 2.4) + 0.3 * bandpass(x, 2500, 3)
        elif fc_end:
            # filtro que se abre: se mezclan dos versiones
            x = lowpass(x, fc) * (1 - np.linspace(0, 1, n)) + lowpass(x, fc_end) * np.linspace(0, 1, n)
        else:
            x = lowpass(x, fc)
        out[ch, i0:i1] = x * env
    return norm(out) * gain




def drone(t0, t1, notes, gain, fc0, fc1, a=4.0, r=3.0):
    i0 = int(max(0, t0) * SR)
    i1 = min(N, int((t1 + r) * SR))
    n = i1 - i0
    tt = np.arange(n) / SR + i0 / SR
    env = smoothstep(t0, t0 + a, tt) * (1 - smoothstep(t1, t1 + r, tt))
    out = Z()
    for name in notes:
        for dc, p in ((-10, -0.6), (0, 0.0), (11, 0.6)):
            v = saw_voice(hz(name), n, dc, 0.004)
            l, rr = pan(v, p)
            out[0, i0:i1] += l
            out[1, i0:i1] += rr
    for ch in range(2):
        seg = out[ch, i0:i1]
        out[ch, i0:i1] = (lowpass(seg, fc0) * np.linspace(1, 0, n) + lowpass(seg, fc1) * np.linspace(0, 1, n)) * env
    return norm(out) * gain


def kick(f0=50, dur=1.4):
    L = int(dur * SR)
    tt = np.arange(L) / SR
    f = f0 + 80 * np.exp(-tt / 0.03)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.4)


def hit(dur=4.0):
    """Golpe de susto: bombo grave, plancha de metal y un racimo disonante."""
    L = int(dur * SR)
    tt = np.arange(L) / SR
    x = kick(42, dur) * 1.4
    x += bandpass(rng.standard_normal(L), 300, 0.8) * np.exp(-tt / 0.25) * 0.6
    for f in (hz('C2'), hz('Db2'), hz('Gb2'), hz('G3')):
        x += 0.25 * saw_voice(f, L, rng.uniform(-8, 8)) * np.exp(-tt / 1.4)
    return lowpass(x, 2500)


def music():
    bus = Z()
    E = EV
    # 1) el monte: un grave casi inaudible
    bus += drone(0.0, E['pisa_suelo'], ['D1', 'A1'], 0.25, 120, 220, a=6)
    # 2) el túnel: un racimo que crece muy despacio
    bus += drone(E['pisa_suelo'] - 2, E['ruido1'], ['D1', 'Eb2', 'A2'], 0.3, 150, 500, a=8)
    # 3) el ruido: cuerdas agudas temblorosas (sul ponticello) hasta el silencio antes del grito
    bus += drone(E['ruido1'], E['grito'] - 1.6, ['D5', 'Eb5', 'A5'], 0.12, 2500, 5000, a=3, r=0.15)
    bus += drone(E['ruido1'], E['grito'] - 1.6, ['D1', 'Eb1'], 0.35, 90, 260, a=5, r=0.15)
    # latidos mientras se asoma
    tt0 = E['asoma'] + 2.0
    per = 0.75
    while tt0 < E['grito'] - 1.7:
        place(bus, kick(48, 0.5), tt0, 0.0, 0.5)
        place(bus, kick(46, 0.5), tt0 + 0.22, 0.0, 0.32)
        tt0 += per
        per = max(0.5, per * 0.985)
    # golpes de susto
    for th, g in ((E['asoma'] + 6.4, 0.8), (E['grito'], 1.0), (E['ruge'], 0.9), (E['ve_monstruo'], 0.8),
                  (E['mira_delante'] + 0.3, 0.7), (E['tren_t_tip'], 1.0), (E['grito_final'], 0.8), (T_TITLE, 1.0)):
        place(bus, hit(), th, 0.0, g)
    # 4) la persecución: ostinato grave a 150 ppm y metales que suben
    t0, t1 = E['corre'], E['tren_t_tip']
    beat = 60 / 150
    tt0 = t0
    k = 0
    while tt0 < t1:
        acc = 1.0 if k % 4 == 0 else 0.55
        place(bus, kick(55, 0.35), tt0, 0.0, 0.35 * acc)
        L = int(beat * 0.5 * SR)
        nt = ('D2', 'D2', 'Eb2', 'D2', 'D2', 'F2', 'D2', 'Eb2')[k % 8]
        v = saw_voice(hz(nt), L) * np.exp(-np.arange(L) / SR / 0.1)
        place(bus, lowpass(v, 900), tt0, 0.2 * (-1) ** k, 0.2)
        tt0 += beat / 2
        k += 1
    bus += drone(t0, E['tren_t_boca'], ['D2', 'A2', 'Eb3'], 0.3, 400, 1600, a=1.5, r=1.0)
    bus += drone(E['tren_t_boca'], t1, ['D2', 'A2', 'Eb3', 'Bb3'], 0.38, 800, 3000, a=1.0, r=0.3)
    # 5) después de la caída: un vacío grave y el final
    bus += drone(E['tren_t_impacto'] + 1.0, T_END, ['D1', 'Ab1'], 0.3, 100, 300, a=4, r=2)
    return bus


# --------------------------------------------------------------------- el golpe (primera persona)
def impact_fx():
    """Vamos dentro de la máquina: el golpe es nuestro. Hierro reventando, un pitido en los oídos
    que se apaga despacio y nada más (arriba, lejos, el monstruo)."""
    bus = np.zeros((2, N))
    rng = np.random.default_rng(71)
    ti = EV['tren_t_impacto']
    Li = int(4.0 * SR)
    xi = np.arange(Li) / SR
    boom = lowpass(rng.standard_normal(Li), 110) * np.exp(-xi / 0.9)
    crash = bandpass(rng.standard_normal(Li), 1800, 0.9) * np.exp(-xi / 0.25)
    clang = sum(np.sin(2 * np.pi * f * xi) * np.exp(-xi / d) for f, d in ((233, 0.9), (617, 0.6), (1291, 0.35)))
    place(bus, norm(norm(boom) + 0.7 * norm(crash) + 0.25 * norm(clang)), ti, 0.0, 1.0)
    Lt = int(6.5 * SR)
    xt = np.arange(Lt) / SR
    ring = np.sin(2 * np.pi * 3900 * xt) * np.minimum(1, xt / 0.3) * np.exp(-xt / 2.2)
    place(bus, ring, ti + 0.25, 0.0, 0.05)
    return bus


# --------------------------------------------------------------------- mezcla
# en el golpe se corta todo lo nuestro (la noche, la respiración, el tren); queda el pitido,
# el monstruo arriba y la música grave del final
alive = 1 - smoothstep(EV['tren_t_impacto'] - 0.01, EV['tren_t_impacto'] + 0.03, t)
mix = ((night() * 0.5 + tunnel_tone() * 0.2 + drips() * 0.55 + breathing() * 0.8 + steps() * 0.9 +
        train() * 0.9) * alive + monster() * 1.0 + music() * 0.55 + impact_fx() * 1.0)
# el silencio total antes del grito (solo la respiración contenida y el latido)
duck = 1 - 0.85 * (smoothstep(EV['grito'] - 2.2, EV['grito'] - 1.6, t) * (1 - smoothstep(EV['grito'] - 0.02, EV['grito'], t)))
mix *= duck
mix *= smoothstep(0.0, 2.0, t) * (1 - smoothstep(T_END - 0.8, DUR - 0.2, t))
# el título: todo se corta de golpe en negro, solo queda el golpe
mix *= np.where((t > T_TITLE - 0.02) & (t < T_TITLE), 0.0, 1.0)
peak = np.abs(mix).max()
mix = np.tanh(mix / peak * 1.3) / np.tanh(1.3) * 0.92
pcm = (mix.T * 32767).astype('<i2')
out = os.path.join(HERE, 'sonido.wav')
with wave.open(out, 'wb') as wf:
    wf.setnchannels(2)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes(pcm.tobytes())
print('OK', out, '%.1f s' % DUR)
