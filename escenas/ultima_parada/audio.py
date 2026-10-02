"""
Banda sonora de "Última parada", sintetizada desde cero (solo numpy).

Lee timing.json (cortes de plano, la gota, la salida del túnel, los pájaros y el
título) y genera sonido.wav (48 kHz, estéreo):
  ambiente hueco del túnel, goteos con eco, la gota del primer plano, crujidos
  del metal de la locomotora, hojas al cruzar la cortina de lianas, viento del
  valle, río lejano, pájaros y una bandada que despega; y una música original en
  re menor (pads, campanas, pulso grave y un gran acorde de re mayor al salir a la luz).

Uso: python audio.py   (también vale: blender -b -P audio.py)
"""
import json, os, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000
T = json.load(open(os.path.join(HERE, 'timing.json'), encoding='utf-8'))
DUR = T['duracion'] + 2.5
N = int(SR * DUR)
t = np.arange(N) / SR
rng = np.random.default_rng(11)
SH = [p['inicio'] for p in T['planos']]          # inicio de cada plano
EXIT0, EXIT1 = T['salida_tunel']
T_EXIT = (EXIT0 + EXIT1) / 2
T_DROP = T['gotas'][0]
T_BIRDS = T['pajaros']
T_TITLE = T['titulo'][0]
T_END = T['duracion']


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


inside = 1 - smoothstep(EXIT0 - 0.5, EXIT1 + 0.5, t)      # 1 dentro del túnel, 0 fuera
outside = 1 - inside


def muffle(bus, env, fc=600):
    out = np.empty_like(bus)
    for ch in range(2):
        out[ch] = bus[ch] * (1 - env) + lowpass(bus[ch], fc) * env
    return out


# --------------------------------------------------------------------- ambientes
def tunnel_tone():
    bus = Z()
    for ch in range(2):
        b = np.cumsum(rng.standard_normal(N))
        b = highpass(b, 18)
        b = lowpass(b, 220)
        bus[ch] = norm(b)
    hollow = norm(bandpass(rng.standard_normal(N), 140, 4)) * random_ctrl(2.5, 0.4, 1.0)
    bus += hollow * 0.4
    return bus * inside * random_ctrl(3.0, 0.7, 1.0)


def valley_wind():
    bus = Z()
    gust = random_ctrl(1.8, 0.3, 1.0)
    for ch in range(2):
        w = norm(lowpass(highpass(np.cumsum(rng.standard_normal(N)), 30), 900))
        hiss = norm(bandpass(rng.standard_normal(N), 2500 + 300 * ch, 1.2))
        bus[ch] = w * gust * 0.8 + hiss * gust ** 2 * 0.15
    # el aire que entra por la boca se oye cada vez más al acercarse
    approach = smoothstep(SH[5] + 2, EXIT0, t) * inside
    return bus * (outside + approach * 0.6)


def river():
    bus = Z()
    for ch in range(2):
        x = norm(bandpass(rng.standard_normal(N), 700, 0.8)) + 0.5 * norm(bandpass(rng.standard_normal(N), 2600, 1.5))
        bus[ch] = x * random_ctrl(0.4, 0.75, 1.0)
    return bus * outside * 0.5


# --------------------------------------------------------------------- agua
def drip_sound(f_hi=2600, dur=0.12):
    L = int(dur * SR)
    tt = np.arange(L) / SR
    f = 700 + f_hi * np.minimum(1, tt / 0.025)
    d = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.022)
    click = rng.standard_normal(L) * np.exp(-tt / 0.0012) * 0.4
    return d + click


def drips():
    bus = Z()
    tt0 = 0.8
    while tt0 < EXIT0:
        place(bus, drip_sound(rng.uniform(1600, 3200)), tt0, rng.uniform(-0.8, 0.8), rng.uniform(0.08, 0.25))
        tt0 += rng.uniform(0.9, 3.5)
    return reverb(bus, 2.6, 0.7, predelay=0.05, seed=2)


def hero_drop():
    """La gota del primer plano: cerca, nítida, con una cola larga de túnel."""
    bus = Z()
    s = drip_sound(2900, 0.18)
    L = int(0.6 * SR)
    tt = np.arange(L) / SR
    plop = np.sin(2 * np.pi * (480 + 900 * np.exp(-tt / 0.03)) * tt) * np.exp(-tt / 0.07) * 0.5
    place(bus, s, T_DROP, 0.05, 0.9)
    place(bus, plop, T_DROP + 0.004, 0.05, 0.5)
    # gotitas secundarias que rebotan
    for k, dt in enumerate((0.11, 0.19, 0.24)):
        place(bus, drip_sound(3600, 0.05), T_DROP + dt, 0.1, 0.12 / (k + 1))
    return reverb(bus, 3.4, 0.55, predelay=0.03, seed=3)


# --------------------------------------------------------------------- metal y hojas
def metal_groan(dur, f0, f1):
    L = int(dur * SR)
    tt = np.arange(L) / SR
    f = np.geomspace(f0, f1, L) * (1 + 0.01 * np.sin(2 * np.pi * 6 * tt))
    ph = np.cumsum(f) / SR
    x = np.sin(2 * np.pi * ph) + 0.5 * np.sin(2 * np.pi * 2.01 * ph) + 0.3 * np.sin(2 * np.pi * 3.7 * ph)
    grit = bandpass(rng.standard_normal(L), f0 * 4, 2) * 0.6
    env = np.sin(np.pi * np.minimum(1, tt / dur)) ** 1.5
    rough = 1 + 0.5 * lowpass(rng.standard_normal(L), 30) / 0.1
    return (x + grit) * env * np.clip(rough, 0.2, 2)


def metal():
    bus = Z()
    events = [(SH[2] + 1.2, 2.6, 95, 70, -0.4), (SH[2] + 6.5, 1.8, 140, 120, 0.3),
              (SH[3] + 1.0, 1.4, 210, 180, -0.2), (SH[4] + 0.8, 2.2, 80, 62, 0.2), (SH[5] + 2.0, 1.5, 160, 150, 0.0)]
    for t0, d, f0, f1, p in events:
        place(bus, norm(metal_groan(d, f0, f1)), t0, p, 0.35)
    # tic-tac de chapa dilatándose con el sol
    tt0 = SH[2]
    while tt0 < SH[5]:
        L = int(0.05 * SR)
        tk = bandpass(rng.standard_normal(L) * np.exp(-np.arange(L) / (SR * 0.004)), rng.uniform(1800, 4200), 3)
        place(bus, norm(tk), tt0, rng.uniform(-0.7, 0.7), rng.uniform(0.04, 0.1))
        tt0 += rng.uniform(0.6, 2.4)
    return reverb(bus, 2.8, 0.6, seed=4)


def foliage():
    """Roce de hojas al atravesar la cortina de lianas de la boca."""
    bus = Z()
    L = int(1.6 * SR)
    tt = np.arange(L) / SR
    for ch, p in ((0, -0.6), (1, 0.6)):
        x = highpass(rng.standard_normal(L), 1800) * (0.5 + 0.5 * lowpass(rng.standard_normal(L), 25) / 0.06)
        env = np.exp(-((tt - 0.8) / 0.32) ** 2)
        place(bus, norm(x * env), EXIT0 - 1.4, p, 0.35)
    return bus


# --------------------------------------------------------------------- pájaros
def chirp_phrase(lo=2600, hi=6000):
    out = []
    for _ in range(rng.integers(3, 8)):
        d = rng.uniform(0.04, 0.12)
        L = int(d * SR)
        tt = np.arange(L) / SR
        f0, f1 = rng.uniform(lo, hi), rng.uniform(lo, hi)
        ph = 2 * np.pi * np.cumsum(f0 + (f1 - f0) * tt / d) / SR
        out.append((np.sin(ph) + 0.15 * np.sin(2 * ph)) * np.sin(np.pi * tt / d) ** 2)
        out.append(np.zeros(int(rng.uniform(0.03, 0.1) * SR)))
    return np.concatenate(out)


def birds():
    bus = Z()
    for b in range(6):
        tt0 = rng.uniform(0, 3)
        p = rng.uniform(-0.9, 0.9)
        while tt0 < DUR - 1:
            g = 0.02 if tt0 < EXIT0 else rng.uniform(0.05, 0.11)
            place(bus, chirp_phrase(), tt0, p, g)
            tt0 += rng.uniform(1.2, 4.0) if tt0 > EXIT0 else rng.uniform(3, 7)
    for ch in range(2):
        bus[ch] = lowpass(bus[ch], 8000)
    bus = reverb(bus, 1.2, 0.3, seed=5)
    return muffle(bus, inside, 900)


def flock():
    """La bandada que despega del bosque: aleteos y algunos graznidos."""
    bus = Z()
    for k in range(22):
        t0 = T_BIRDS + rng.uniform(0, 1.6)
        n = int(rng.integers(5, 10))
        per = rng.uniform(0.09, 0.14)
        p = rng.uniform(-0.8, 0.8)
        for i in range(n):
            L = int(0.07 * SR)
            tt = np.arange(L) / SR
            flap = bandpass(rng.standard_normal(L), rng.uniform(500, 1100), 1.4) * np.sin(np.pi * tt / 0.07) ** 2
            place(bus, norm(flap), t0 + i * per, p, 0.09 * (1 - i / n) ** 0.5)
    return reverb(bus, 1.0, 0.25, seed=6)


# --------------------------------------------------------------------- música
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


def bell(name, dur=4.5):
    f = hz(name)
    L = int(dur * SR)
    tt = np.arange(L) / SR
    x = np.zeros(L)
    for k, (ratio, amp, dec) in enumerate(((1, 1.0, 1.6), (2.0, 0.5, 0.9), (3.01, 0.25, 0.5), (4.2, 0.12, 0.3), (5.4, 0.08, 0.2))):
        x += amp * np.sin(2 * np.pi * f * ratio * tt + k) * np.exp(-tt / dec)
    hammer = lowpass(rng.standard_normal(L), 3000) * np.exp(-tt / 0.004) * 0.3
    return (x + hammer) * np.minimum(1, tt / 0.003)


def melody(bus, notes, t0, step, gain, p=0.15):
    tt = t0
    for nm, d in notes:
        if nm:
            place(bus, bell(nm), tt, p * rng.uniform(-1, 1), gain)
        tt += d * step


def kick(f0=55, dur=1.2):
    L = int(dur * SR)
    tt = np.arange(L) / SR
    f = f0 + 90 * np.exp(-tt / 0.03)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.35)


def music():
    bus = Z()
    s = SH
    # túnel: re menor oscuro que se va abriendo
    bus += pad(['D2', 'A2', 'F3'], 1.5, s[1] + 2, 0.22, 380)
    bus += pad(['D2', 'A2', 'D3', 'F3'], s[1], s[2] + 1, 0.28, 650)
    bus += pad(['Bb1', 'F2', 'D3', 'F3'], s[2], s[3] + 1, 0.30, 800)
    bus += pad(['G1', 'D2', 'Bb2', 'D3'], s[3], s[4] + 0.5, 0.30, 800)
    bus += pad(['A1', 'E2', 'A2', 'C#3', 'E3'], s[4], s[5] + 1, 0.30, 900)
    # crescendo hacia la luz: el filtro se abre, sube la tensión
    bus += pad(['D2', 'A2', 'D3', 'F3', 'A3'], s[5], s[5] + 4.0, 0.32, 700, fc_end=1500)
    bus += pad(['Bb1', 'F2', 'Bb2', 'D3', 'F3'], s[5] + 3.8, s[5] + 7.0, 0.36, 1500, fc_end=2400)
    bus += pad(['C2', 'G2', 'C3', 'E3', 'G3'], s[5] + 6.8, EXIT0 + 0.6, 0.40, 2400, fc_end=4200)
    # ¡fuera!: re mayor enorme con coro
    bus += pad(['D1', 'D2', 'A2', 'D3', 'F#3', 'A3'], T_EXIT - 0.3, T_EXIT + 7.5, 0.62, 3200, a=0.25)
    bus += pad(['D4', 'F#4', 'A4'], T_EXIT, T_EXIT + 7.5, 0.24, 0, a=0.6, choir=True)
    bus += pad(['G1', 'G2', 'D3', 'G3', 'B3'], T_EXIT + 7.3, s[6] + 0.5, 0.5, 2600)
    bus += pad(['D4', 'G4', 'B4'], T_EXIT + 7.3, s[6] + 0.5, 0.2, 0, choir=True)
    # final: re con novena, sereno, y se apaga
    bus += pad(['D2', 'A2', 'D3', 'E3', 'F#3', 'A3'], s[6], T_END - 1.0, 0.46, 1800, r=3.5)
    bus += pad(['A4', 'D5', 'E5'], s[6] + 0.5, T_END - 1.0, 0.16, 0, choir=True, r=3.5)
    # campanas: el motivo (menor en el túnel, mayor al final)
    motif_m = [('A4', 2), ('F4', 1), ('E4', 1), ('D4', 3), (None, 1), ('E4', 1), ('F4', 1), ('G4', 1), ('E4', 3)]
    motif_M = [('A4', 2), ('F#4', 1), ('E4', 1), ('D4', 2), ('E4', 1), ('F#4', 1), ('A4', 4)]
    melody(bus, motif_m, s[1] + 3.0, 0.55, 0.11)
    melody(bus, motif_m, s[2] + 2.0, 0.55, 0.12)
    melody(bus, [('D5', 2), ('C#5', 1), ('A4', 3)], s[4] + 0.8, 0.5, 0.11)
    melody(bus, motif_M, s[6] + 1.5, 0.62, 0.14)
    # pulso grave que acelera hacia la salida
    tt = s[5] + 1.0
    period = 1.05
    while tt < EXIT0 - 0.2:
        place(bus, kick(), tt, 0.0, 0.42 * (0.5 + 0.5 * (tt - s[5]) / (EXIT0 - s[5])))
        tt += period
        period = max(0.42, period * 0.93)
    # golpe y "whoosh" al salir
    L = int(5.0 * SR)
    tt_ = np.arange(L) / SR
    boom = np.sin(2 * np.pi * np.cumsum(30 + 45 * np.exp(-tt_ / 1.8)) / SR) * np.exp(-tt_ / 1.9)
    boom += lowpass(rng.standard_normal(L), 160) * np.exp(-tt_ / 0.3) * 1.5
    place(bus, norm(boom), T_EXIT - 0.25, 0.0, 0.75)
    L = int(3.5 * SR)
    tt_ = np.arange(L) / SR
    sw = lowpass(highpass(rng.standard_normal(L), 1200), 9000) * (tt_ / 3.5) ** 3
    place(bus, norm(sw), T_EXIT - 3.6, 0.0, 0.3)
    cym = highpass(rng.standard_normal(int(6 * SR)), 4000) * np.exp(-np.arange(int(6 * SR)) / SR / 1.8)
    place(bus, norm(cym), T_EXIT - 0.2, 0.0, 0.08)
    # golpe suave con el título
    place(bus, norm(kick(42, 3.0)), T_TITLE, 0.0, 0.35)
    bus = reverb(bus, 3.2, 0.38, seed=9)
    bus = muffle(bus, inside * 0.35, 1400)
    return bus * (1 - smoothstep(T_END - 2.5, T_END + 1.5, t))


# --------------------------------------------------------------------- mezcla
mix = (tunnel_tone() * 0.22 + valley_wind() * 0.26 + river() * 0.12 + drips() * 0.6 + hero_drop() * 0.9 +
       metal() * 0.55 + foliage() * 0.7 + birds() * 1.0 + flock() * 0.9 + music() * 0.62)
mix *= smoothstep(0.0, 1.5, t) * (1 - smoothstep(T_END - 1.0, DUR - 0.2, t))
peak = np.abs(mix).max()
mix = np.tanh(mix / peak * 1.25) / np.tanh(1.25) * 0.9
pcm = (mix.T * 32767).astype('<i2')
out = os.path.join(HERE, 'sonido.wav')
with wave.open(out, 'wb') as wf:
    wf.setnchannels(2)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes(pcm.tobytes())
print('OK', out, '%.1f s' % DUR)
