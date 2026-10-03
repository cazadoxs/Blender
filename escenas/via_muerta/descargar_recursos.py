"""
Descarga los recursos escaneados (CC0) que usa "Vía muerta":
texturas PBR, modelos de vegetación y rocas y el cielo HDRI.

Fuentes: Poly Haven (https://polyhaven.com) y, como reserva, ambientCG
(https://ambientcg.com). Todo es CC0: se puede usar sin atribución.

Cada "papel" de recursos.json tiene una lista de candidatos preferidos; si alguno
ya no existe, el script busca en el catálogo de Poly Haven por palabras clave, y
si tampoco lo encuentra prueba en ambientCG. Lo descargado queda en ./recursos/
y el resumen en ./recursos/manifiesto.json, que es lo que lee construir_escena.py.

Uso (cualquiera de las dos):
  python descargar_recursos.py
  "C:\\Program Files\\Blender Foundation\\Blender 5.0\\blender.exe" -b -P descargar_recursos.py

Opciones (después de "--" si se lanza con Blender):
  --res 2k        resolución de texturas por defecto (las de "res" en recursos.json mandan)
  --solo texturas,modelos,hdri

Se puede interrumpir y relanzar: lo ya descargado no se repite.
"""
import json, os, sys, time, re, zipfile, io, argparse
import urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'recursos')
UA = 'ViaMuerta-BlenderCorto/1.0 (proyecto personal, github.com/cazadoxs/Blender)'

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
ap = argparse.ArgumentParser()
ap.add_argument('--res', default='2k')
ap.add_argument('--solo', default='texturas,modelos,hdri')
ap.add_argument('--max-res', default=None, help='tope de resolución (p. ej. 1k para pruebas)')
A = ap.parse_known_args(argv)[0]
SOLO = set(A.solo.split(','))

CAT = json.load(open(os.path.join(HERE, 'recursos.json'), encoding='utf-8'))


# ------------------------------------------------------------------ red
def get(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            err = e
        except Exception as e:      # red inestable: reintento
            err = e
        time.sleep(2 ** (k + 1))
    raise err


def get_json(url):
    return json.loads(get(url).decode('utf-8'))


def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = get(url)
    tmp = path + '.part'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)
    print('   descargado %-60s %6.1f MB' % (os.path.relpath(path, OUT), len(data) / 1e6), flush=True)
    return path


# ------------------------------------------------------------------ Poly Haven
PH = 'https://api.polyhaven.com'
_ph_cache = {}


def ph_assets(kind):
    if kind not in _ph_cache:
        try:
            _ph_cache[kind] = get_json('%s/assets?t=%s' % (PH, kind))
        except Exception as e:
            print('  ! no se pudo leer el catálogo de Poly Haven (%s): %s' % (kind, e))
            _ph_cache[kind] = {}
    return _ph_cache[kind]


def score(aid, info, words, avoid):
    text_name = (aid + ' ' + info.get('name', '')).lower()
    tags = ' '.join(info.get('tags', []) + info.get('categories', [])).lower()
    s = 0
    for w in words:
        w = w.lower()
        if w in text_name:
            s += 3
        if w in tags:
            s += 2
    for w in avoid:
        if w.lower() in text_name or w.lower() in tags:
            s -= 6
    return s


def pick(kind, role, n):
    """Lista de ids de Poly Haven para un papel: candidatos que existan + búsqueda."""
    assets = ph_assets(kind)
    ids = [c for c in role.get('candidatos', []) if c in assets]
    if len(ids) < n and assets:
        ranked = sorted(((score(a, i, role.get('palabras', []), role.get('evitar', [])), a)
                         for a, i in assets.items()), reverse=True)
        for s, a in ranked:
            if s < 3 or len(ids) >= n:
                break
            if a not in ids:
                ids.append(a)
    return ids[:n]


def best_res(d, want):
    order = ['1k', '2k', '4k', '8k', '16k']
    if A.max_res and order.index(want) > order.index(A.max_res):
        want = A.max_res
    if want in d:
        return want
    have = [r for r in order if r in d]
    lower = [r for r in have if order.index(r) <= order.index(want)]
    return (lower or have)[-1] if (lower or have) else None


MAPS = {  # nombre en Poly Haven -> nombre interno
    'Diffuse': 'color', 'nor_gl': 'normal', 'Rough': 'rough', 'Displacement': 'disp',
    'AO': 'ao', 'Metal': 'metal', 'Opacity': 'opacity', 'Mask': 'opacity',
}


def ph_texture(aid, res):
    files = get_json('%s/files/%s' % (PH, aid))
    maps = {}
    for key, name in MAPS.items():
        if key not in files:
            continue
        r = best_res(files[key], res)
        fmts = files[key][r]
        fmt = 'png' if name == 'disp' and 'png' in fmts else ('jpg' if 'jpg' in fmts else next(iter(fmts)))
        url = fmts[fmt]['url']
        p = os.path.join(OUT, 'texturas', aid, os.path.basename(urllib.parse.urlparse(url).path))
        maps[name] = download(url, p)
    if 'color' not in maps:
        raise RuntimeError('sin mapa de color')
    out = {'id': aid, 'fuente': 'polyhaven', 'mapas': maps}
    dim = ph_assets('textures').get(aid, {}).get('dimensions')
    if dim:
        out['dim_mm'] = dim       # tamaño real del mosaico (ancho, alto) en milímetros
    return out


def ph_model(aid, res):
    files = get_json('%s/files/%s' % (PH, aid))
    if 'blend' not in files:
        raise RuntimeError('sin .blend')
    r = best_res(files['blend'], res)
    entry = files['blend'][r]['blend']
    base = os.path.join(OUT, 'modelos', aid)
    path = download(entry['url'], os.path.join(base, os.path.basename(urllib.parse.urlparse(entry['url']).path)))
    for rel, inc in entry.get('include', {}).items():
        download(inc['url'], os.path.join(base, rel.replace('/', os.sep)))
    return {'id': aid, 'fuente': 'polyhaven', 'blend': path}


def ph_hdri(aid, res):
    files = get_json('%s/files/%s' % (PH, aid))
    r = best_res(files['hdri'], res)
    url = files['hdri'][r]['hdr']['url']
    return {'id': aid, 'fuente': 'polyhaven', 'path': download(url, os.path.join(OUT, 'hdri', os.path.basename(url)))}


# ------------------------------------------------------------------ ambientCG (reserva)
ACG = 'https://ambientcg.com/api/v2/full_json'
ACG_MAPS = {'Color': 'color', 'NormalGL': 'normal', 'Roughness': 'rough', 'Displacement': 'disp',
            'AmbientOcclusion': 'ao', 'Metalness': 'metal', 'Opacity': 'opacity'}


def acg_texture(aid, res):
    if A.max_res:
        res = min(res, A.max_res, key=lambda r: ['1k', '2k', '4k', '8k'].index(r))
    res = res.upper()
    folder = os.path.join(OUT, 'texturas', aid)
    if not os.path.isdir(folder) or not os.listdir(folder):
        url = None
        try:
            js = get_json('%s?id=%s&include=downloadData' % (ACG, aid))
            for d in js['foundAssets'][0]['downloadFolders']['default']['downloadFiletypeCategories']['zip']['downloads']:
                if d['attribute'] == '%s-JPG' % res:
                    url = d['downloadLink']
        except Exception:
            pass
        url = url or 'https://ambientcg.com/get?file=%s_%s-JPG.zip' % (aid, res)
        data = get(url)
        os.makedirs(folder, exist_ok=True)
        zipfile.ZipFile(io.BytesIO(data)).extractall(folder)
        print('   descargado %-60s %6.1f MB' % ('texturas/' + aid, len(data) / 1e6), flush=True)
    maps = {}
    for fn in os.listdir(folder):
        for k, name in ACG_MAPS.items():
            if re.search(r'_%s\.(jpg|png)$' % k, fn):
                maps[name] = os.path.join(folder, fn)
    if 'color' not in maps:
        raise RuntimeError('sin mapa de color')
    return {'id': aid, 'fuente': 'ambientcg', 'mapas': maps}


def acg_search(words):
    for w in words:
        try:
            js = get_json('%s?q=%s&type=Material&sort=Popular&limit=3' % (ACG, urllib.parse.quote(w)))
            for a in js.get('foundAssets', []):
                yield a['assetId']
        except Exception:
            continue


# ------------------------------------------------------------------ main
def rel(o):
    """Rutas relativas a esta carpeta, para que el manifiesto valga en cualquier PC."""
    if isinstance(o, dict):
        return {k: rel(v) for k, v in o.items()}
    if isinstance(o, list):
        return [rel(v) for v in o]
    if isinstance(o, str) and os.path.isabs(o):
        return os.path.relpath(o, HERE).replace(os.sep, '/')
    return o


def main():
    os.makedirs(OUT, exist_ok=True)
    man_path = os.path.join(OUT, 'manifiesto.json')
    man = json.load(open(man_path, encoding='utf-8')) if os.path.exists(man_path) else {}
    man.setdefault('texturas', {})
    man.setdefault('modelos', {})
    fallos = []

    def save():
        json.dump(rel(man), open(man_path, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)

    if 'texturas' in SOLO:
        # catálogo de texturas (nombre, categorías, etiquetas y tamaño real) para elegir con criterio
        cat = {a: {'cat': i.get('categories', []), 'tags': i.get('tags', []), 'dim_mm': i.get('dimensions')}
               for a, i in ph_assets('textures').items()}
        if cat:
            json.dump(cat, open(os.path.join(OUT, 'catalogo_texturas.json'), 'w', encoding='utf-8'), indent=0)
        for name, role in CAT['texturas'].items():
            res = role.get('res', A.res)
            print('Textura [%s]' % name, flush=True)
            got = None
            for aid in pick('textures', role, 4):
                try:
                    got = ph_texture(aid, res)
                    break
                except Exception as e:
                    print('  ! %s: %s' % (aid, e))
            if not got:
                for aid in role.get('ambientcg', []) + list(acg_search(role.get('palabras', [])[:2])):
                    try:
                        got = acg_texture(aid, res)
                        break
                    except Exception as e:
                        print('  ! ambientCG %s: %s' % (aid, e))
            if got:
                man['texturas'][name] = got
                print('  -> %s (%s)' % (got['id'], got['fuente']))
            else:
                fallos.append('textura ' + name)
            save()

    if 'modelos' in SOLO:
        for name, role in CAT['modelos'].items():
            print('Modelos [%s]' % name, flush=True)
            lst = []
            for aid in pick('models', role, role.get('n', 2) + 2):
                if len(lst) >= role.get('n', 2):
                    break
                try:
                    lst.append(ph_model(aid, role.get('res', '2k')))
                    print('  -> %s' % aid)
                except Exception as e:
                    print('  ! %s: %s' % (aid, e))
            if lst:
                man['modelos'][name] = lst
            else:
                fallos.append('modelo ' + name)
            save()

    if 'hdri' in SOLO:
        role = CAT['hdri']
        print('Cielo HDRI', flush=True)
        for aid in pick('hdris', role, 4):
            try:
                man['hdri'] = ph_hdri(aid, role.get('res', '8k'))
                print('  -> %s' % aid)
                break
            except Exception as e:
                print('  ! %s: %s' % (aid, e))
        else:
            fallos.append('hdri')
        save()

    total = 0
    for root, _, fs in os.walk(OUT):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in fs)
    print('\nListo. %.2f GB en %s' % (total / 1e9, OUT))
    if fallos:
        print('Sin descargar (la escena usará materiales procedurales para esto): ' + ', '.join(fallos))


main()
