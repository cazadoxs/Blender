"""
Banda sonora del recorrido, sintetizada desde cero (solo numpy).

Lee timing.json (pasos de la cámara, entrada y salida del túnel, ángulo de la
puerta que se mece) y genera sonido.wav (48 kHz, estéreo) con:
  viento con ráfagas, pasos sobre piedra sincronizados con el balanceo de la
  cámara, eco dentro del túnel de la puerta, goteo, crujido de la puerta,
  pájaros, cuervos sobre el campanario y una música ambiental oscura que se
  abre al salir al patio.

Uso: python3 audio.py   (también vale el Python de Blender: blender -b -P audio.py)
"""
import json, os, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 48000
T = json.load(open(os.path.join(HERE, 'timing.json')))
DUR = T['duracion'] + 1.5
N = int(SR * DUR)
t = np.arange(N) / SR
rng = np.random.default_rng(7)
T_IN, T_OUT = T['tunel']


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
    """Curva de control suave a partir de [(tiempo, valor), ...]."""
    ts, vs = zip(*points)
    return np.interp(np.arange(n) / SR, ts, vs)


def smoothstep(a, b, x):
    u = np.clip((x - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


def random_ctrl(step, lo, hi, n=N):
    k = int(n / SR / step) + 3
    pts = [(i * step, rng.uniform(lo, hi)) for i in range(k)]
    c = ctrl(pts, n)
    return lowpass(c, 1.0 / step)


def pan(x, p):
    a = (p + 1) * np.pi / 4
    return np.cos(a) * x, np.sin(a) * x


def place(bus, sig, t0, p=0.0, gain=1.0):
    i = int(t0 * SR)
    if i >= N:
        return
    sig = sig[:N - i] * gain
    l, r = pan(sig, p)
    bus[0, i:i + len(sig)] += l
    bus[1, i:i + len(sig)] += r


def reverb(bus, rt, wet, predelay=0.02, seed=1):
    r2 = np.random.default_rng(seed)
    n = int(rt * SR * 1.2)
    tt = np.arange(n) / SR
    out = np.zeros_like(bus)
    m = 1 << int(np.ceil(np.log2(bus.shape[1] + n)))
    for ch in range(2):
        ir = r2.standard_normal(n) * np.exp(-6.9 * tt / rt)
        ir = lowpass(ir, 5000)
        ir[: int(predelay * SR)] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        y = np.fft.irfft(np.fft.rfft(bus[ch], m) * np.fft.rfft(ir, m), m)[: bus.shape[1]]
        out[ch] = bus[ch] * (1 - wet) + y * wet
    return out


def stereo_zeros():
    return np.zeros((2, N))


# Envolvente "dentro del túnel" (0 fuera, 1 dentro)
tun = smoothstep(T_IN - 0.6, T_IN + 0.6, t) * (1 - smoothstep(T_OUT - 0.5, T_OUT + 0.9, t))


def muffle(bus, amount_env, fc=700):
    out = np.empty_like(bus)
    for ch in range(2):
        lp = lowpass(bus[ch], fc)
        out[ch] = bus[ch] * (1 - amount_env) + lp * amount_env
    return out


# --------------------------------------------------------------------- viento
def wind():
    bus = stereo_zeros()
    gust = random_ctrl(1.6, 0.35, 1.0)
    for ch in range(2):
        w = np.cumsum(rng.standard_normal(N))
        w = highpass(w, 25)
        w = lowpass(w, 450)
        w /= np.abs(w).max()
        whistle = bandpass(rng.standard_normal(N), 820 + 60 * ch, 9)
        whistle /= np.abs(whistle).max()
        bus[ch] = w * gust * 0.55 + whistle * gust ** 3 * 0.10
    hollow = bandpass(rng.standard_normal(N), 190, 3)
    hollow /= np.abs(hollow).max()
    bus += hollow * tun * 0.35
    return muffle(bus, tun * 0.6, 900)


# --------------------------------------------------------------------- pasos
def footstep(strength):
    L = int(0.3 * SR)
    tt = np.arange(L) / SR
    grit = np.zeros(L)
    for _ in range(45):
        pos = int(abs(rng.normal(0.018, 0.03)) * SR)
        cl = int(SR * 0.004)
        if pos + cl >= L:
            continue
        click = rng.standard_normal(cl) * np.exp(-np.arange(cl) / (SR * 0.0007))
        grit[pos:pos + cl] += click * rng.uniform(0.15, 0.6) * np.exp(-pos / (SR * 0.07))
    grit = highpass(grit, 900)
    clack = bandpass(rng.standard_normal(L) * np.exp(-tt / 0.012), 1900 + rng.uniform(-300, 300), 2.5)
    thud = np.sin(2 * np.pi * (62 + rng.uniform(-6, 6)) * tt) * np.exp(-tt / 0.035)
    s = grit * 0.9 + clack * 1.6 + thud * 0.7
    att = np.minimum(1, tt / 0.002)
    return s * att * strength


def steps_bus():
    dry = stereo_zeros()
    wet = stereo_zeros()
    for st in T['pasos']:
        s = footstep(st['fuerza'] * rng.uniform(0.85, 1.05))
        p = -0.12 if st['lado'] == 'izq' else 0.12
        inside = T_IN - 0.2 <= st['t'] <= T_OUT + 0.2
        place(wet if inside else dry, s, st['t'], p)
    dry = reverb(dry, 0.45, 0.18, seed=3)
    wet = reverb(wet, 1.9, 0.55, predelay=0.03, seed=4)
    return dry + wet


# --------------------------------------------------------------------- goteo en el túnel
def drips():
    bus = stereo_zeros()
    for k, dt in enumerate((0.9, 2.3, 3.4, 4.1)):
        L = int(0.12 * SR)
        tt = np.arange(L) / SR
        f = 900 + 1700 * np.minimum(1, tt / 0.03)
        ph = 2 * np.pi * np.cumsum(f) / SR
        d = np.sin(ph) * np.exp(-tt / 0.025)
        place(bus, d, T_IN + dt, p=rng.uniform(-0.6, 0.6), gain=0.25)
    return reverb(bus, 2.2, 0.75, predelay=0.04, seed=5)


# --------------------------------------------------------------------- puerta que cruje
def creak():
    ang = np.array(T['puerta_grados'])
    w = np.abs(np.gradient(ang)) * T['fps']             # grados por segundo
    w = np.interp(t, np.arange(len(ang)) / T['fps'], w)
    inten = np.clip((w - 2.0) / 4.0, 0, 1) ** 1.5
    near = np.exp(-((t - (T_IN + T_OUT) / 2) / 2.6) ** 2) * 0.9 + 0.12
    rate = 35 + 90 * inten + 15 * random_ctrl(0.07, -1, 1)
    phase = np.cumsum(rate / SR)
    imp = np.diff(np.floor(phase), prepend=0.0) * (0.6 + 0.8 * rng.random(N))
    body = (bandpass(imp, 380, 5) * 1.0 + bandpass(imp, 820, 6) * 0.8 +
            bandpass(imp, 1550, 7) * 0.5 + bandpass(imp, 2700, 8) * 0.25)
    body /= np.abs(body).max() + 1e-9
    sig = body * inten * near
    bus = np.vstack(pan(sig, 0.35))
    return reverb(bus, 1.6, 0.4, seed=6)


# --------------------------------------------------------------------- pájaros
def chirp_phrase():
    notes = rng.integers(3, 8)
    out = []
    for _ in range(notes):
        d = rng.uniform(0.04, 0.11)
        L = int(d * SR)
        tt = np.arange(L) / SR
        f0, f1 = rng.uniform(2800, 5600), rng.uniform(2600, 6200)
        f = f0 + (f1 - f0) * tt / d
        ph = 2 * np.pi * np.cumsum(f) / SR
        env = np.sin(np.pi * tt / d) ** 2
        out.append((np.sin(ph) + 0.15 * np.sin(2 * ph)) * env)
        out.append(np.zeros(int(rng.uniform(0.03, 0.09) * SR)))
    return np.concatenate(out)


def birds():
    bus = stereo_zeros()
    for b in range(3):
        tt0 = rng.uniform(0, 1.5)
        p = rng.uniform(-0.8, 0.8)
        g = rng.uniform(0.04, 0.09)
        while tt0 < DUR - 1:
            place(bus, chirp_phrase(), tt0, p, g)
            tt0 += rng.uniform(1.4, 3.8)
    for ch in range(2):
        bus[ch] = lowpass(bus[ch], 7000)
    bus = reverb(bus, 0.9, 0.35, seed=7)
    return muffle(bus, tun, 500) * (1 - 0.6 * tun)


# --------------------------------------------------------------------- cuervos
def caw():
    d = rng.uniform(0.32, 0.45)
    L = int(d * SR)
    tt = np.arange(L) / SR
    f = 560 - 140 * tt / d + 18 * np.sin(2 * np.pi * 28 * tt)
    ph = np.cumsum(f) / SR
    saw = 2 * (ph % 1.0) - 1
    rasp = 1 + 0.6 * lowpass(rng.standard_normal(L), 90) / 0.05
    x = saw * np.clip(rasp, 0, 2)
    x = bandpass(x, 1150, 2.0) + 0.8 * bandpass(x, 2300, 2.5) + 0.3 * bandpass(x, 3500, 3)
    env = np.minimum(1, tt / 0.02) * np.exp(-np.maximum(0, tt - 0.05) / (d * 0.6))
    return x / (np.abs(x).max() + 1e-9) * env


def crows():
    bus = stereo_zeros()
    for (tc, p, n) in ((2.4, -0.5, 2), (11.3, 0.3, 3), (14.6, -0.2, 2), (18.2, 0.6, 1), (20.4, -0.4, 3)):
        for k in range(n):
            place(bus, caw(), tc + k * rng.uniform(0.45, 0.6), p, 0.22 if tc > T_OUT else 0.12)
    for ch in range(2):
        bus[ch] = lowpass(bus[ch], 5000)
    bus = reverb(bus, 1.4, 0.45, seed=8)
    return muffle(bus, tun, 500)


# --------------------------------------------------------------------- música
NOTE = {'C': 0, 'Db': 1, 'D': 2, 'Eb': 3, 'E': 4, 'F': 5, 'Gb': 6, 'G': 7, 'Ab': 8, 'A': 9, 'Bb': 10, 'B': 11}


def hz(name):
    n, octv = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((NOTE[n] + 12 * (octv + 1) - 69) / 12)


def saw_voice(f, n, detune_cents=0.0, vib=0.0):
    tt = np.arange(n) / SR
    ff = f * 2 ** (detune_cents / 1200) * (1 + vib * np.sin(2 * np.pi * 4.8 * tt + rng.uniform(0, 6)))
    ph = 2 * np.pi * np.cumsum(ff) / SR + rng.uniform(0, 6.28)
    kmax = int(min(28, 5000 / f))
    s = np.zeros(n)
    for k in range(1, kmax + 1):
        s += np.sin(k * ph) / k
    return s


def pad_segment(notes, t0, t1, gain, fc, choir=False):
    a, r = 1.6, 2.0
    i0 = int(max(0, t0 - 0.2) * SR)
    i1 = min(N, int((t1 + r) * SR))
    n = i1 - i0
    tt = np.arange(n) / SR + i0 / SR
    env = smoothstep(t0, t0 + a, tt) * (1 - smoothstep(t1, t1 + r, tt))
    l = np.zeros(n)
    rr = np.zeros(n)
    for name in notes:
        f = hz(name)
        for dc, p in ((-7, -0.5), (0, 0.0), (7, 0.5)):
            v = saw_voice(f, n, dc, 0.003 if choir else 0.0015)
            ll, rv = pan(v, p)
            l += ll
            rr += rv
    out = np.zeros((2, N))
    for ch, x in enumerate((l, rr)):
        if choir:
            x = bandpass(x, 700, 2.2) + 0.7 * bandpass(x, 1220, 2.6) + 0.25 * bandpass(x, 2600, 3)
        else:
            x = lowpass(x, fc, 2)
        out[ch, i0:i1] = x * env
    m = np.abs(out).max() + 1e-9
    return out / m * gain


def music():
    bus = stereo_zeros()
    bus += pad_segment(['D2', 'A2', 'D3', 'F3'], 0.0, T_IN + 0.3, 0.30, 900)
    bus += pad_segment(['D1', 'D2', 'Ab2'], T_IN - 0.5, T_OUT, 0.26, 420)
    bus += pad_segment(['Bb1', 'F2', 'Bb2', 'D3', 'F3'], T_OUT - 0.2, T_OUT + 4.2, 0.36, 1800)
    bus += pad_segment(['G1', 'D2', 'G2', 'Bb2', 'D3'], T_OUT + 4.0, T_OUT + 8.0, 0.34, 1600)
    bus += pad_segment(['D2', 'A2', 'D3', 'E3', 'F3', 'A3'], T_OUT + 7.8, DUR - 2.0, 0.36, 1500)
    bus += pad_segment(['D4', 'F4', 'A4'], T_OUT + 0.5, T_OUT + 4.2, 0.16, 0, choir=True)
    bus += pad_segment(['D4', 'G4', 'Bb4'], T_OUT + 4.0, T_OUT + 8.0, 0.16, 0, choir=True)
    bus += pad_segment(['D4', 'F4', 'A4', 'E5'], T_OUT + 7.8, DUR - 2.0, 0.18, 0, choir=True)
    # Golpe grave y "whoosh" al revelarse el palacio
    L = int(4.0 * SR)
    tt = np.arange(L) / SR
    f = 52 * np.exp(-tt / 2.5) + 30
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 1.6)
    boom += lowpass(rng.standard_normal(L), 180) * np.exp(-tt / 0.25) * 2.0
    place(bus, boom / np.abs(boom).max(), T_OUT - 0.05, 0.0, 0.55)
    L = int(1.6 * SR)
    tt = np.arange(L) / SR
    sw = highpass(rng.standard_normal(L), 1500) * (tt / 1.6) ** 3
    sw = lowpass(sw, 9000)
    place(bus, sw / np.abs(sw).max(), T_OUT - 1.6, 0.0, 0.18)
    bus = reverb(bus, 2.8, 0.35, seed=9)
    bus = muffle(bus, tun * 0.7, 500)
    fade = 1 - smoothstep(DUR - 2.2, DUR - 0.1, t)
    return bus * fade


# --------------------------------------------------------------------- mezcla
mix = (wind() * 0.30 + steps_bus() * 0.55 + drips() * 0.5 + creak() * 0.45 +
       birds() * 1.0 + crows() * 1.0 + music() * 0.55)
mix *= smoothstep(0.0, 0.4, t)            # entrada suave
peak = np.abs(mix).max()
mix = np.tanh(mix / peak * 1.3) / np.tanh(1.3) * 0.89
pcm = (mix.T * 32767).astype('<i2')
out = os.path.join(HERE, 'sonido.wav')
with wave.open(out, 'wb') as wf:
    wf.setnchannels(2)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes(pcm.tobytes())
print('OK', out, '%.1f s' % DUR)
