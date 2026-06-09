"""
Motor de Plano DXF Multi-Hoja — C4  v3.0
Hojas: 0-Ubicación | 1-Sótanos | 2-Planta Tipo Baja | 3-Planta Tipo Alta

Incluye:
  - Layout parametrizado según análisis real (num_dptos/piso, mezcla_tipologias)
  - Hatches por categoría: retiros, húmedo, estructural, circulación, ductos, parking
  - Leyenda de materiales y zonas en cada hoja
  - Grilla de columnas con etiquetas A/B/C y 1/2/3
  - Ductos de ventilación en baños, cocina y sótano
  - Barra de escala gráfica
  - Cotas detalladas por ambiente
  - Dimensiones RNE verificadas (A.010 / A.020)

Unidades: metros | R2010 | ZwCAD / AutoCAD / BricsCAD
"""

import io
import math
import string as _string
from dataclasses import dataclass, field
from typing import List

import ezdxf
from ezdxf.enums import TextEntityAlignment


# ─── Entrada ──────────────────────────────────────────────────────────────────

@dataclass
class EntradaPlano:
    frente: float
    fondo: float
    area_terreno: float
    retiro_frontal: float
    retiro_lateral: float
    retiro_posterior: float
    distrito: str
    fuente_normativa: str = ""
    planta_libre: float = 0.0
    pisos_vivienda: int = 0
    sotanos: int = 0
    area_construida_bruta: float = 0.0
    area_vendible_total: float = 0.0
    num_departamentos: int = 0
    estacionamientos_requeridos: int = 0
    cus_utilizado: float = 0.0
    limitante: str = ""
    area_min_depto: float = 0.0
    mezcla_tipologias: list = field(default_factory=list)
    nombre_proyecto: str = "Proyecto C4"
    direccion: str = ""
    # Grúa torre
    grua_modelo: str = ""        # ej: "Potain MC85B"
    grua_radio_m: float = 0.0    # radio de alcance en metros
    grua_base_m: float = 0.0     # lado de la base en metros (huella cuadrada)
    # Calles circundantes
    calle_frontal: str = ""      # ej: "Calle Colina 180"
    calle_lateral_izq: str = ""
    calle_lateral_der: str = ""
    calle_posterior: str = ""


# ─── Generador principal ──────────────────────────────────────────────────────

def generar_plano_dxf(e: EntradaPlano) -> bytes:
    doc = ezdxf.new(dxfversion='R2010')
    doc.header['$INSUNITS'] = 6
    doc.header['$MEASUREMENT'] = 1
    msp = doc.modelspace()

    _setup_linetypes(doc)
    _setup_layers(doc)
    _setup_textstyle(doc)

    ancho = max(e.frente - 2 * e.retiro_lateral, 4.0)
    prof  = max(e.fondo  - e.retiro_frontal - e.retiro_posterior, 4.0)
    pisos = max(e.pisos_vivienda, 1)
    GAP   = 26.0

    layout = _layout_engine(ancho, prof, e)

    # Hoja 0: Plano de Ubicacion
    _hoja_ubicacion(msp, e)
    x_next = e.frente + GAP

    # Hoja 1: Sotanos
    if e.sotanos > 0:
        _hoja_sotanos(msp, e, ancho, prof, x0=x_next, y0=0, layout=layout)
        x_next += ancho + GAP

    # Hoja 2: Planta Tipo Baja
    mid = math.ceil(pisos / 2)
    _hoja_planta_tipo(msp, e, ancho, prof, x0=x_next, y0=0,
                      p_desde=1, p_hasta=mid,
                      label='PLANTA TIPO BAJA', layout=layout)
    x_next += ancho + GAP

    # Hoja 3: Planta Tipo Alta
    if pisos > 6:
        _hoja_planta_tipo(msp, e, ancho, prof, x0=x_next, y0=0,
                          p_desde=mid + 1, p_hasta=pisos,
                          label='PLANTA TIPO ALTA', layout=layout, alta=True)

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode('utf-8')


# ─── Layout Engine ────────────────────────────────────────────────────────────

def _layout_engine(ancho: float, prof: float, e: EntradaPlano) -> dict:
    """
    Tipología: galería posterior de acceso + núcleo centrado + N unidades
    como tiras verticales que llenan TODO el ancho del edificio.

    - n_piso: departamentos por piso (del análisis de cabida)
    - apt_w : ancho de cada unidad = ancho_edificio / n_piso  (llena el footprint)
    - apt_h : profundidad de la unidad = prof - banda_galeria
    """
    if e.pisos_vivienda > 0 and e.num_departamentos > 0:
        n_piso = max(1, round(e.num_departamentos / e.pisos_vivienda))
    else:
        n_piso = 2 if ancho < 14 else 4
    # Cap de dibujo: nunca tiras más angostas que ~4.2 m (legibilidad del plano)
    n_max_legible = max(1, int(ancho / 4.2))
    n_dibujo = max(1, min(n_piso, n_max_legible, 6))

    apt_tipo = _tipo_dominante(e.mezcla_tipologias)

    # Banda posterior (galería de circulación + núcleo de escaleras/ascensor)
    banda_h = max(3.6, min(5.2, prof * 0.24))
    core_w  = max(4.0, min(6.5, ancho * 0.22))
    core_h  = banda_h

    apt_w = ancho / n_dibujo
    apt_h = prof - banda_h

    return {
        'n_piso': n_piso,          # real, del análisis (va al título)
        'n_dibujo': n_dibujo,      # cuántas tiras se grafican
        'apt_tipo': apt_tipo,
        'apt_w': apt_w, 'apt_h': apt_h,
        'banda_h': banda_h, 'core_w': core_w, 'core_h': core_h,
    }


def _tipo_dominante(mezcla: list) -> str:
    if not mezcla:
        return '2dorm'
    best = max(mezcla, key=lambda x: float(x.get('porcentaje', 0)))
    t = best.get('tipo', '2dorm').lower().replace('-', '').replace(' ', '')
    if 'studio' in t or 'monoam' in t or 'estudio' in t:
        return 'studio'
    if '1' in t:
        return '1dorm'
    if '3' in t:
        return '3dorm'
    return '2dorm'


# ─── Hoja 0: Plano de Ubicacion ───────────────────────────────────────────────

def _hoja_ubicacion(msp, e: EntradaPlano):
    f, fo = e.frente, e.fondo
    rf, rl, rp = e.retiro_frontal, e.retiro_lateral, e.retiro_posterior
    bx1, by1 = rl, rf
    bx2, by2 = f - rl, fo - rp

    msp.add_lwpolyline([(0,-2),(f,-2),(f,0),(0,0)], close=True, dxfattribs={'layer':'CALLE'})
    _text(msp, f/2, -1.1, 'VIA PUBLICA', 'CALLE', 0.35, center=True)

    _rect(msp, 0, 0, f, fo, 'TERRENO', lw=50)

    if rf > 0:
        _rect(msp, 0, 0, f, rf, 'RETIROS', lw=18)
        _hatch_any(msp, 0, 0, f, rf, 'ANSI31', 1, 0.25, 'HATCH_RET')
        if rf > 0.6: _text(msp, f/2, rf/2, f'Ret.Frontal  {rf:.1f}m', 'TEXTO_RET', 0.22, center=True)
    if rp > 0:
        _rect(msp, 0, fo-rp, f, fo, 'RETIROS', lw=18)
        _hatch_any(msp, 0, fo-rp, f, fo, 'ANSI31', 1, 0.25, 'HATCH_RET')
        if rp > 0.6: _text(msp, f/2, fo-rp/2, f'Ret.Posterior  {rp:.1f}m', 'TEXTO_RET', 0.22, center=True)
    if rl > 0:
        for x1, x2 in [(0, rl), (f-rl, f)]:
            _rect(msp, x1, rf, x2, fo-rp, 'RETIROS', lw=18)
            _hatch_any(msp, x1, rf, x2, fo-rp, 'ANSI31', 1, 0.25, 'HATCH_RET')

    _rect(msp, bx1, by1, bx2, by2, 'EDIFICACION', lw=70)
    cx, cy = (bx1+bx2)/2, (by1+by2)/2
    _text(msp, cx, cy+0.65, 'HUELLA EDIFICIO', 'TEXTO_EDIF', 0.28, center=True)
    _text(msp, cx, cy+0.10, f'{e.planta_libre:.1f} m2', 'TEXTO_EDIF', 0.42, center=True)
    if e.pisos_vivienda:
        t = f'{e.pisos_vivienda} pisos'
        if e.sotanos: t += f' + {e.sotanos} sotanos'
        _text(msp, cx, cy-0.42, t, 'TEXTO_EDIF', 0.28, center=True)

    msp.add_line((cx-0.4,cy),(cx+0.4,cy), dxfattribs={'layer':'EJES'})
    msp.add_line((cx,cy-0.4),(cx,cy+0.4), dxfattribs={'layer':'EJES'})

    D = 1.8
    _cota_h(msp, 0, fo+D, f, fo+D, 0, fo, f, fo, f'FRENTE = {f:.2f} m')
    _cota_v(msp, f+D, 0, f+D, fo, f, 0, f, fo, f'FONDO = {fo:.2f} m')
    if rf > 0.1: _cota_v(msp, -D, 0, -D, rf, 0, 0, 0, rf, f'R.F. {rf:.1f}m')
    if rp > 0.1: _cota_v(msp, -D, fo-rp, -D, fo, 0, fo-rp, 0, fo, f'R.P. {rp:.1f}m')
    if rl > 0:
        _cota_h(msp, rl, -D-1.2, f-rl, -D-1.2, rl, 0, f-rl, 0,
                f'Ancho libre = {f-2*rl:.2f} m')
    _cota_v(msp, bx2+D*0.7, by1, bx2+D*0.7, by2, bx2, by1, bx2, by2,
            f'Prof. {by2-by1:.2f}m')

    _cuadro_datos(msp, e, f+D+2.0, 0)
    _norte(msp, f+2.5, fo/2+1.5)
    _barra_escala(msp, f/2-2.5, -D-3.0)

    # Leyenda
    _leyenda(msp, f+D+2.0+11.5, 0)

    ty = fo+D+2.2
    _text(msp, f/2, ty+0.80, e.nombre_proyecto.upper(), 'TITULO', 0.65, center=True)
    dir_txt = (e.direccion.upper() + ',  ' if e.direccion else '') + f'{e.distrito.upper()}, LIMA, PERU'
    _text(msp, f/2, ty+0.10, dir_txt, 'TITULO', 0.35, center=True)
    _text(msp, f/2, ty-0.48,
          'ESC. REFERENCIAL  -  MOTOR C4  v3.0  -  SOLO PARA PRE-INVERSION',
          'DATOS', 0.20, center=True)

    # Nombres de calles alrededor del terreno
    _calles_en_plano(msp, e, 0, 0, f, fo)

    # Símbolo de grúa torre con radio de alcance (solo si se proporcionó el modelo)
    _grua_en_plano(msp, e, 0, 0)


# ─── Hoja 1: Planta Sotanos ───────────────────────────────────────────────────

def _hoja_sotanos(msp, e: EntradaPlano, ancho: float, prof: float,
                  x0: float, y0: float, layout: dict):

    # Grilla de columnas
    n_cx = max(2, round(ancho / 5.0))
    n_cy = max(2, round(prof  / 5.0))
    esp_x = ancho / n_cx
    esp_y = prof  / n_cy
    _grilla_columnas(msp, x0, y0, ancho, prof, esp_x, esp_y)

    # Contorno edificio (encima de la grilla)
    _rect(msp, x0, y0, x0+ancho, y0+prof, 'EDIFICACION', lw=70)

    # Nucleo escaleras
    nw, nh = layout['core_w'], layout['core_h']
    nx = x0 + (ancho - nw) / 2
    ny = y0 + prof - nh
    _rect(msp, nx, ny, nx+nw, ny+nh, 'ESCALERAS', lw=50)
    _hatch_any(msp, nx, ny, nx+nw, ny+nh, 'LINE', 251, 0.20, 'HATCH_ESC')
    _escalera_simbolo(msp, nx, ny, nw, nh)
    _text(msp, nx+nw/2, ny+nh*0.70, 'ESCALERA', 'HABITACIONES', 0.24, center=True)
    _text(msp, nx+nw/2, ny+nh*0.42, 'ASCENSOR',  'HABITACIONES', 0.22, center=True)
    _text(msp, nx+nw/2, ny+nh*0.18, f'{nw:.1f}x{nh:.1f}m', 'DATOS', 0.18, center=True)

    # Cisterna + cuarto bombas (esquina posterior izquierda)
    cis_w = max(2.5, min(4.0, ancho * 0.22))
    cis_h = max(2.0, min(3.5, prof  * 0.20))
    cis_x = x0 + 0.20
    cis_y = y0 + prof - nh - cis_h - 0.40
    _rect(msp, cis_x, cis_y, cis_x+cis_w, cis_y+cis_h, 'MUROS', lw=35)
    _hatch_any(msp, cis_x, cis_y, cis_x+cis_w, cis_y+cis_h, 'ANSI37', 4, 0.25, 'HATCH_CIRC')
    _text(msp, cis_x+cis_w/2, cis_y+cis_h*0.65, 'CISTERNA', 'HABITACIONES', 0.22, center=True)
    _text(msp, cis_x+cis_w/2, cis_y+cis_h*0.35, f'{cis_w:.1f}x{cis_h:.1f}m', 'DATOS', 0.18, center=True)

    # Cuarto bombas
    bomb_w = max(1.5, cis_w * 0.60)
    bomb_x = cis_x
    bomb_y = cis_y - 2.0
    if bomb_y >= y0:
        _rect(msp, bomb_x, bomb_y, bomb_x+bomb_w, bomb_y+1.8, 'MUROS', lw=25)
        _text(msp, bomb_x+bomb_w/2, bomb_y+0.9, 'C.BOMBAS', 'HABITACIONES', 0.20, center=True)

    # Rampa vehicular (frente, lado derecho del nucleo)
    ramp_w = max(3.5, min(4.5, ancho * 0.33))
    ramp_h = min(6.0, prof * 0.35)
    ramp_x = x0 + ancho - ramp_w - 0.20
    ramp_y = y0
    _rect(msp, ramp_x, ramp_y, ramp_x+ramp_w, ramp_y+ramp_h, 'SOTANO_RAMP', lw=50)
    for k in range(7):
        t = k / 6
        msp.add_line(
            (ramp_x + t * ramp_w, ramp_y),
            (ramp_x + (1-t) * ramp_w, ramp_y + ramp_h),
            dxfattribs={'layer': 'SOTANO_RAMP', 'lineweight': 9},
        )
    _text(msp, ramp_x+ramp_w/2, ramp_y+ramp_h*0.65, 'RAMPA', 'HABITACIONES', 0.30, center=True)
    _text(msp, ramp_x+ramp_w/2, ramp_y+ramp_h*0.42, f'{ramp_w:.1f}m ancho', 'DATOS', 0.22, center=True)
    _text(msp, ramp_x+ramp_w/2, ramp_y+ramp_h*0.22, 'pte. max 15%', 'DATOS', 0.18, center=True)

    # Zona estacionamientos
    pkg_w = 2.50; pkg_h = 5.00; pasillo = 6.50
    zx1 = x0 + cis_w + 0.80
    zx2 = ramp_x - 0.40
    zy1 = y0 + 0.20
    zy2 = y0 + prof - nh - 0.50
    zona_w = zx2 - zx1
    zona_h = zy2 - zy1
    n_pkg = max(1, int(zona_w / pkg_w))
    conteo = 1

    if zona_h >= pkg_h * 2 + pasillo:
        py_f1 = zy1; py_f2 = zy1 + pkg_h + pasillo
        for i in range(n_pkg):
            px = zx1 + i * pkg_w
            if px + pkg_w > zx2 + 0.01: break
            _parking_box(msp, px, py_f1, pkg_w, pkg_h, conteo); conteo += 1
        for i in range(n_pkg):
            px = zx1 + i * pkg_w
            if px + pkg_w > zx2 + 0.01: break
            _parking_box(msp, px, py_f2, pkg_w, pkg_h, conteo); conteo += 1
        pm = zx1 + zona_w/2; pp = zy1 + pkg_h + pasillo/2
        _text(msp, pm, pp+0.35, 'PASILLO CIRCULACION  6.50 m', 'HABITACIONES', 0.28, center=True)
        _text(msp, pm, pp-0.10, '(MANIOBRA 90°  -  A.010 Art.53)', 'DATOS', 0.20, center=True)
        msp.add_line((zx1, zy1+pkg_h), (zx2, zy1+pkg_h), dxfattribs={'layer':'SOTANO_PKG','lineweight':13})
        msp.add_line((zx1, zy1+pkg_h+pasillo), (zx2, zy1+pkg_h+pasillo), dxfattribs={'layer':'SOTANO_PKG','lineweight':13})
    elif zona_h >= pkg_h:
        for i in range(n_pkg):
            px = zx1 + i * pkg_w
            if px + pkg_w > zx2 + 0.01: break
            _parking_box(msp, px, zy1, pkg_w, pkg_h, conteo); conteo += 1

    # Ductos de ventilacion CO2 / monoxido (sótano)
    n_ductos = max(2, int(ancho / 8))
    ducto_s = 0.60
    for k in range(n_ductos):
        dx = x0 + (k + 0.5) * ancho / n_ductos - ducto_s / 2
        dy = y0 + prof - nh - ducto_s - 0.40
        if dx > nx - 1 and dx < nx + nw + 1: continue  # skip if over nucleo
        _ducto(msp, dx, dy, ducto_s, ducto_s, f'D{k+1}')

    # Cotas
    _cota_h(msp, x0, y0-2.5, x0+ancho, y0-2.5, x0, y0, x0+ancho, y0,
            f'ANCHO EDIFICIO = {ancho:.2f} m')
    _cota_v(msp, x0+ancho+2.5, y0, x0+ancho+2.5, y0+prof, x0+ancho, y0, x0+ancho, y0+prof,
            f'PROF. = {prof:.2f} m')
    _cota_h(msp, ramp_x, y0+prof+1.8, ramp_x+ramp_w, y0+prof+1.8,
            ramp_x, y0+prof, ramp_x+ramp_w, y0+prof, f'Rampa {ramp_w:.1f}m')
    _cota_h(msp, zx1, y0-4.2, zx1+n_pkg*pkg_w, y0-4.2, zx1, y0, zx1+n_pkg*pkg_w, y0,
            f'{conteo-1} plazas  (2.50x5.00m  altura libre 2.10m)')

    # Leyenda + barra escala + titulo
    _leyenda(msp, x0+ancho+3.0, y0)
    _barra_escala(msp, x0+ancho/2-2.5, y0-6.0)
    _norte(msp, x0+ancho+2.0, y0+prof-2.0)
    niv_txt = f'{e.sotanos} NIVEL{"ES" if e.sotanos>1 else ""}'
    _titulo_hoja(msp, x0+ancho/2, y0+prof+5.5, e.nombre_proyecto.upper(),
                 f'PLANTA SOTANO  ({niv_txt})  -  {e.distrito.upper()}',
                 f'PLAZAS REQUERIDAS: {e.estacionamientos_requeridos}  |  '
                 f'GRAFICADAS: {conteo-1}  |  {ancho:.1f}x{prof:.1f}m')


# ─── Hoja 2-3: Planta Tipo Residencial ────────────────────────────────────────

def _hoja_planta_tipo(msp, e: EntradaPlano, ancho: float, prof: float,
                      x0: float, y0: float, p_desde: int, p_hasta: int,
                      label: str, layout: dict, alta: bool = False):
    """
    Planta tipo — tipología de galería posterior:
      · N unidades como tiras verticales que llenan TODO el ancho
      · banda posterior con galería de circulación (HALL) + núcleo centrado
      · cada unidad accede por una puerta desde la galería
    """
    n        = layout['n_dibujo']
    apt_w    = layout['apt_w']
    apt_h    = layout['apt_h']
    banda_h  = layout['banda_h']
    core_w   = layout['core_w']
    apt_tipo = layout['apt_tipo']
    if alta and apt_tipo == '2dorm':
        apt_tipo = '3dorm'

    gy0 = y0 + apt_h          # línea que separa unidades / galería
    gy1 = y0 + prof           # muro posterior

    # ── Grilla estructural (todo el footprint) ───────────────────────────────
    n_cx = max(2, round(ancho / 5.0)); n_cy = max(2, round(prof / 5.0))
    _grilla_columnas(msp, x0, y0, ancho, prof, ancho / n_cx, prof / n_cy)

    # ── Perímetro ────────────────────────────────────────────────────────────
    _rect(msp, x0, y0, x0 + ancho, y0 + prof, 'MUROS', lw=70)

    # ── Banda posterior: galería de circulación ──────────────────────────────
    _rect(msp, x0, gy0, x0 + ancho, gy1, 'CIRCULACION', lw=18)
    _hatch_any(msp, x0, gy0, x0 + ancho, gy1, 'DOTS', 4, 0.30, 'HATCH_CIRC')
    msp.add_line((x0, gy0), (x0 + ancho, gy0), dxfattribs={'layer': 'MUROS', 'lineweight': 35})

    # ── Núcleo centrado (escalera + ascensor) dentro de la banda ─────────────
    nx = x0 + (ancho - core_w) / 2
    ny = gy0
    _rect(msp, nx, ny, nx + core_w, gy1, 'ESCALERAS', lw=50)
    _hatch_any(msp, nx, ny, nx + core_w, gy1, 'LINE', 251, 0.20, 'HATCH_ESC')
    esc_w = core_w * 0.55
    _escalera_simbolo(msp, nx, ny, esc_w, banda_h)
    msp.add_line((nx + esc_w, ny), (nx + esc_w, gy1), dxfattribs={'layer': 'MUROS', 'lineweight': 25})
    _text(msp, nx + esc_w / 2,          ny + banda_h * 0.62, 'ESCALERA', 'HABITACIONES', 0.20, center=True)
    _text(msp, nx + esc_w + (core_w - esc_w) / 2, ny + banda_h * 0.62, 'ASCENSOR', 'HABITACIONES', 0.18, center=True)
    _text(msp, nx + core_w / 2,         ny + banda_h * 0.20, f'{core_w:.1f}x{banda_h:.1f}m', 'DATOS', 0.16, center=True)

    # Etiqueta galería (a un lado del núcleo)
    _text(msp, x0 + (nx - x0) / 2, gy0 + banda_h / 2, 'HALL', 'HABITACIONES', 0.22, center=True)
    _ducto(msp, x0 + 0.35, gy0 + banda_h * 0.55, 0.40, 0.40, 'DV')
    _ducto(msp, x0 + ancho - 0.75, gy0 + banda_h * 0.55, 0.40, 0.40, 'DV')

    # ── Unidades: N tiras que llenan el ancho ────────────────────────────────
    area_vend = round(apt_w * apt_h * 0.78, 1)
    for i in range(n):
        ux = x0 + i * apt_w
        if i > 0:  # muro divisorio entre unidades
            msp.add_line((ux, y0), (ux, gy0), dxfattribs={'layer': 'MUROS', 'lineweight': 35})
        _departamento(msp, ux, y0, apt_w, apt_h, apt_tipo, 'STD')
        # Puerta de ingreso desde la galería (muro posterior de la unidad)
        _puerta(msp, ux + apt_w / 2 - 0.45, gy0, 0.85)
        # Rótulo de la unidad (sobre la cota de fachada)
        _text(msp, ux + apt_w / 2, y0 - 0.6, f'DPTO {i+1}  ~{area_vend} m2', 'TITULO', 0.20, center=True)

    # ── Cotas exteriores ─────────────────────────────────────────────────────
    D = 2.2
    _cota_h(msp, x0, y0 - D, x0 + ancho, y0 - D, x0, y0, x0 + ancho, y0,
            f'ANCHO TOTAL = {ancho:.2f} m')
    _cota_h(msp, x0, y0 - D - 1.8, x0 + apt_w, y0 - D - 1.8, x0, y0, x0 + apt_w, y0,
            f'DPTO = {apt_w:.2f} m')
    _cota_v(msp, x0 + ancho + D, y0, x0 + ancho + D, y0 + prof, x0 + ancho, y0, x0 + ancho, y0 + prof,
            f'PROF. = {prof:.2f} m')
    _cota_v(msp, x0 + ancho + D + 2.0, y0, x0 + ancho + D + 2.0, y0 + apt_h,
            x0 + ancho, y0, x0 + ancho, y0 + apt_h, f'UNIDAD = {apt_h:.2f} m')
    _cota_v(msp, x0 + ancho + D + 2.0, gy0, x0 + ancho + D + 2.0, gy1,
            x0 + ancho, gy0, x0 + ancho, gy1, f'GALERIA = {banda_h:.2f} m')

    # ── Leyenda, escala, norte, título ───────────────────────────────────────
    _leyenda(msp, x0 + ancho + 3.0, y0)
    _barra_escala(msp, x0 + ancho / 2 - 2.5, y0 - 6.0)
    _norte(msp, x0 + ancho + 2.0, y0 + prof - 2.0)

    dptos_piso     = layout['n_piso']
    area_total_piso = round(area_vend * dptos_piso, 1)
    nota = '' if n == dptos_piso else f'  (se grafican {n} de {dptos_piso} tipo)'
    _titulo_hoja(msp, x0 + ancho / 2, y0 + prof + 5.5, e.nombre_proyecto.upper(),
                 f'{label}  -  PISOS {p_desde} AL {p_hasta}  -  {e.distrito.upper()}',
                 f'{dptos_piso} DPTOS/PISO  ({apt_tipo.upper()}){nota}  |  '
                 f'{apt_w:.1f}x{apt_h:.1f}m c/u  |  ~{area_vend} m2 VEND/DPTO  |  ~{area_total_piso} m2/PISO')


# ─── Departamento — Layout Interno ────────────────────────────────────────────

def _departamento(msp, ax0, ay0, w, h, apt_tipo: str, lado: str):
    """Layout interno de un departamento según tipología."""

    if apt_tipo == 'studio':
        _dpto_studio(msp, ax0, ay0, w, h, lado)
    elif apt_tipo == '1dorm':
        _dpto_1dorm(msp, ax0, ay0, w, h, lado)
    elif apt_tipo == '3dorm':
        _dpto_3dorm(msp, ax0, ay0, w, h, lado)
    else:
        _dpto_2dorm(msp, ax0, ay0, w, h, lado)


def _dpto_2dorm(msp, ax0, ay0, w, h, lado):
    """Departamento 2 dormitorios — distribución RNE Lima."""
    # Proporciones target (RNE A.020): escalan proporcionalmente y suman exactamente h
    _raw = [h*0.10, h*0.30, h*0.18, h*0.21, h*0.21]
    _min = [1.20,   3.00,   1.80,   2.50,   2.80]   # mínimos RNE
    _parts = [max(mn, rv) for mn, rv in zip(_min, _raw)]
    # Escala para que sumen exactamente h (sin overflow)
    factor = h / sum(_parts)
    h_bal, h_sala, h_coc, h_d2, h_dp = [p * factor for p in _parts]

    y_bal  = ay0
    y_sala = y_bal  + h_bal
    y_coc  = y_sala + h_sala
    y_d2   = y_coc  + h_coc
    y_dp   = y_d2   + h_d2
    y_top  = ay0 + h

    # Anchos ajustados: baños más angostos para dar más espacio a ambientes principales
    w_bano   = max(1.70, min(2.00, w * 0.30))   # baño 2: 1.70-2.00m
    w_banop  = max(1.70, min(2.10, w * 0.33))   # baño ppal: 1.70-2.10m
    w_sala_d = max(w * 0.55, w - 2.20)          # sala ≥ 55% del ancho
    w_coc_d  = max(2.20, min(w * 0.55, w - 1.60))  # cocina independiente del baño

    # Muros horizontales
    for ym in [y_sala, y_coc, y_d2, y_dp]:
        msp.add_line((ax0, ym), (ax0+w, ym), dxfattribs={'layer':'MUROS','lineweight':25})

    # BALCON
    _hatch_any(msp, ax0, y_bal, ax0+w, y_sala, 'AR-SAND', 251, 0.05, 'HATCH_CIRC')
    _ventana(msp, ax0+0.30, y_bal, ax0+w-0.30, y_bal)
    _room_label(msp, ax0+w/2, y_bal, h_bal, 'BALCON', w*h_bal)

    # SALA / COMEDOR
    msp.add_line((ax0+w_sala_d, y_sala), (ax0+w_sala_d, y_coc),
                 dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+w_sala_d/2, y_sala, h_sala, 'SALA', w_sala_d*h_sala)
    _room_label(msp, ax0+w_sala_d+(w-w_sala_d)/2, y_sala, h_sala, 'COMEDOR', (w-w_sala_d)*h_sala)
    _puerta(msp, ax0+w-0.90, y_coc, 0.85)
    _cota_int_h(msp, ax0, y_sala, ax0+w_sala_d, y_sala, f'{w_sala_d:.2f}m')
    _ventana(msp, ax0+w_sala_d+(w-w_sala_d)*0.2, y_sala, ax0+w-0.2, y_sala)

    # COCINA / LAVANDERIA
    msp.add_line((ax0+w_coc_d, y_coc), (ax0+w_coc_d, y_d2),
                 dxfattribs={'layer':'MUROS','lineweight':18})
    _hatch_any(msp, ax0, y_coc, ax0+w_coc_d, y_d2, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _hatch_any(msp, ax0+w_coc_d, y_coc, ax0+w, y_d2, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w_coc_d/2, y_coc, h_coc, 'COCINA', w_coc_d*h_coc)
    _room_label(msp, ax0+w_coc_d+(w-w_coc_d)/2, y_coc, h_coc, 'LAVAN.', (w-w_coc_d)*h_coc)
    _ducto(msp, ax0+w_coc_d-0.45, y_coc+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+0.10, y_coc, 0.85)

    # DORMITORIO 2 / BANO 2
    msp.add_line((ax0+w-w_bano, y_d2), (ax0+w-w_bano, y_dp),
                 dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+(w-w_bano)/2, y_d2, h_d2, 'DORM. 2', (w-w_bano)*h_d2)
    _hatch_any(msp, ax0+w-w_bano, y_d2, ax0+w, y_dp, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w-w_bano/2, y_d2, h_d2, 'BANO 2', w_bano*h_d2)
    _ducto(msp, ax0+w-w_bano+0.10, y_d2+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+(w-w_bano)-0.90, y_d2, 0.85)
    _ventana(msp, ax0+0.40, y_d2, ax0+(w-w_bano)-0.40, y_d2)
    _cota_int_h(msp, ax0, y_d2, ax0+(w-w_bano), y_d2, f'{(w-w_bano):.2f}m')
    _cota_int_v(msp, ax0, y_d2, ax0, y_dp, f'{h_d2:.2f}m')

    # DORMITORIO PRINCIPAL / BANO PRINCIPAL
    msp.add_line((ax0+w-w_banop, y_dp), (ax0+w-w_banop, y_top),
                 dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+(w-w_banop)/2, y_dp, h_dp, 'DORM. PRINCIPAL', (w-w_banop)*h_dp)
    _hatch_any(msp, ax0+w-w_banop, y_dp, ax0+w, y_top, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w-w_banop/2, y_dp, h_dp, 'BANO PPAL.', w_banop*h_dp)
    _ducto(msp, ax0+w-w_banop+0.10, y_dp+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+0.10, y_dp, 0.85)
    _ventana(msp, ax0+0.40, y_top, ax0+(w-w_banop)-0.40, y_top)
    _cota_int_h(msp, ax0, y_dp, ax0+(w-w_banop), y_dp, f'{(w-w_banop):.2f}m')
    _cota_int_v(msp, ax0, y_dp, ax0, y_top, f'{h_dp:.2f}m')
    # Simbolo cama
    _simbolo_cama(msp, ax0, y_dp, w-w_banop, h_dp)


def _dpto_1dorm(msp, ax0, ay0, w, h, lado):
    """Departamento 1 dormitorio."""
    h_bal  = max(1.20, min(1.50, h * 0.12))
    h_sala = max(4.00, min(5.50, h * 0.42))
    h_coc  = max(2.80, min(3.20, h * 0.24))
    h_dp   = max(3.00, h - h_bal - h_sala - h_coc)

    y_bal  = ay0; y_sala = y_bal + h_bal
    y_coc  = y_sala + h_sala; y_dp = y_coc + h_coc; y_top = ay0 + h

    w_bano = max(2.00, min(2.40, w * 0.38))
    w_coc  = w - w_bano

    for ym in [y_sala, y_coc, y_dp]:
        msp.add_line((ax0, ym), (ax0+w, ym), dxfattribs={'layer':'MUROS','lineweight':25})

    _hatch_any(msp, ax0, y_bal, ax0+w, y_sala, 'AR-SAND', 251, 0.05, 'HATCH_CIRC')
    _ventana(msp, ax0+0.30, y_bal, ax0+w-0.30, y_bal)
    _room_label(msp, ax0+w/2, y_bal, h_bal, 'BALCON', w*h_bal)
    _room_label(msp, ax0+w/2, y_sala, h_sala, 'SALA / COMEDOR', w*h_sala)
    _puerta(msp, ax0+w-0.90, y_coc, 0.85)

    msp.add_line((ax0+w_coc, y_coc), (ax0+w_coc, y_dp), dxfattribs={'layer':'MUROS','lineweight':18})
    _hatch_any(msp, ax0, y_coc, ax0+w_coc, y_dp, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _hatch_any(msp, ax0+w_coc, y_coc, ax0+w, y_dp, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w_coc/2, y_coc, h_coc, 'COCINA', w_coc*h_coc)
    _room_label(msp, ax0+w_coc+w_bano/2, y_coc, h_coc, 'BANO', w_bano*h_coc)
    _ducto(msp, ax0+w-0.55, y_coc+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+0.10, y_coc, 0.85)

    _room_label(msp, ax0+w/2, y_dp, h_dp, 'DORMITORIO', w*h_dp)
    _ventana(msp, ax0+0.40, y_top, ax0+w-0.40, y_top)
    _puerta(msp, ax0+w-0.90, y_dp, 0.85)
    _simbolo_cama(msp, ax0, y_dp, w, h_dp)
    _cota_int_v(msp, ax0, y_dp, ax0, y_top, f'{h_dp:.2f}m')


def _dpto_3dorm(msp, ax0, ay0, w, h, lado):
    """Departamento 3 dormitorios."""
    h_bal  = max(1.20, min(1.80, h * 0.11))
    h_sala = max(3.80, min(5.00, h * 0.30))
    h_coc  = max(2.80, min(3.50, h * 0.22))
    h_d3   = max(2.80, min(3.20, h * 0.18))
    h_d2   = max(2.80, min(3.50, h * 0.20))
    h_dp   = max(3.00, h - h_bal - h_sala - h_coc - h_d3 - h_d2)

    y_bal  = ay0; y_sala = y_bal + h_bal; y_coc = y_sala + h_sala
    y_d3 = y_coc + h_coc; y_d2 = y_d3 + h_d3; y_dp = y_d2 + h_d2; y_top = ay0 + h

    w_bano = max(1.80, min(2.30, w * 0.33))
    w_banop = max(2.00, min(2.50, w * 0.36))

    for ym in [y_sala, y_coc, y_d3, y_d2, y_dp]:
        msp.add_line((ax0, ym), (ax0+w, ym), dxfattribs={'layer':'MUROS','lineweight':25})

    _hatch_any(msp, ax0, y_bal, ax0+w, y_sala, 'AR-SAND', 251, 0.05, 'HATCH_CIRC')
    _ventana(msp, ax0+0.30, y_bal, ax0+w-0.30, y_bal)
    _room_label(msp, ax0+w/2, y_bal, h_bal, 'BALCON', w*h_bal)

    w_sala_d = w*0.58
    msp.add_line((ax0+w_sala_d, y_sala), (ax0+w_sala_d, y_coc), dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+w_sala_d/2, y_sala, h_sala, 'SALA', w_sala_d*h_sala)
    _room_label(msp, ax0+w_sala_d+(w-w_sala_d)/2, y_sala, h_sala, 'COMEDOR', (w-w_sala_d)*h_sala)
    _puerta(msp, ax0+w-0.90, y_coc, 0.85)

    w_coc = w - w_bano
    msp.add_line((ax0+w_coc, y_coc), (ax0+w_coc, y_d3), dxfattribs={'layer':'MUROS','lineweight':18})
    _hatch_any(msp, ax0, y_coc, ax0+w_coc, y_d3, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _hatch_any(msp, ax0+w_coc, y_coc, ax0+w, y_d3, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w_coc/2, y_coc, h_coc, 'COCINA', w_coc*h_coc)
    _room_label(msp, ax0+w_coc+w_bano/2, y_coc, h_coc, 'LAVAN.', w_bano*h_coc)
    _ducto(msp, ax0+w_coc-0.45, y_coc+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+0.10, y_coc, 0.85)

    msp.add_line((ax0+w-w_bano, y_d3), (ax0+w-w_bano, y_d2), dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+(w-w_bano)/2, y_d3, h_d3, 'DORM. 3', (w-w_bano)*h_d3)
    _hatch_any(msp, ax0+w-w_bano, y_d3, ax0+w, y_d2, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w-w_bano/2, y_d3, h_d3, 'BANO 3', w_bano*h_d3)
    _ducto(msp, ax0+w-w_bano+0.10, y_d3+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+(w-w_bano)-0.90, y_d3, 0.85); _ventana(msp, ax0+0.40, y_d3, ax0+(w-w_bano)-0.40, y_d3)

    msp.add_line((ax0+w-w_bano, y_d2), (ax0+w-w_bano, y_dp), dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+(w-w_bano)/2, y_d2, h_d2, 'DORM. 2', (w-w_bano)*h_d2)
    _hatch_any(msp, ax0+w-w_bano, y_d2, ax0+w, y_dp, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w-w_bano/2, y_d2, h_d2, 'BANO 2', w_bano*h_d2)
    _ducto(msp, ax0+w-w_bano+0.10, y_d2+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+(w-w_bano)-0.90, y_d2, 0.85); _ventana(msp, ax0+0.40, y_d2, ax0+(w-w_bano)-0.40, y_d2)

    msp.add_line((ax0+w-w_banop, y_dp), (ax0+w-w_banop, y_top), dxfattribs={'layer':'MUROS','lineweight':18})
    _room_label(msp, ax0+(w-w_banop)/2, y_dp, h_dp, 'DORM. PRINCIPAL', (w-w_banop)*h_dp)
    _hatch_any(msp, ax0+w-w_banop, y_dp, ax0+w, y_top, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+w-w_banop/2, y_dp, h_dp, 'BANO PPAL.', w_banop*h_dp)
    _ducto(msp, ax0+w-w_banop+0.10, y_dp+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+0.10, y_dp, 0.85)
    _ventana(msp, ax0+0.40, y_top, ax0+(w-w_banop)-0.40, y_top)
    _simbolo_cama(msp, ax0, y_dp, w-w_banop, h_dp)


def _dpto_studio(msp, ax0, ay0, w, h, lado):
    """Studio / monoambiente."""
    h_bano = max(2.20, min(3.00, h * 0.28))
    h_coc  = max(2.00, min(2.80, h * 0.22))
    h_sala = h - h_bano - h_coc

    y_sala = ay0; y_coc = ay0 + h_sala; y_bano = y_coc + h_coc; y_top = ay0 + h

    w_bano = max(2.00, min(2.50, w * 0.40))

    for ym in [y_coc, y_bano]:
        msp.add_line((ax0, ym), (ax0+w, ym), dxfattribs={'layer':'MUROS','lineweight':25})

    _room_label(msp, ax0+w/2, y_sala, h_sala, 'SALA / DORMITORIO', w*h_sala)
    _ventana(msp, ax0+0.30, ay0, ax0+w-0.30, ay0)
    _simbolo_cama(msp, ax0, y_sala, w, h_sala)

    msp.add_line((ax0+w-w_bano, y_coc), (ax0+w-w_bano, y_top), dxfattribs={'layer':'MUROS','lineweight':18})
    _hatch_any(msp, ax0, y_coc, ax0+w-w_bano, y_bano, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _hatch_any(msp, ax0+w-w_bano, y_coc, ax0+w, y_top, 'ANSI32', 4, 0.15, 'HATCH_HUMEDO')
    _room_label(msp, ax0+(w-w_bano)/2, y_coc, h_coc, 'COCINA', (w-w_bano)*h_coc)
    _room_label(msp, ax0+w-w_bano/2, y_bano+h_bano/2-0.2, h_bano, 'BANO', w_bano*h_bano)
    _ducto(msp, ax0+w-0.55, y_bano+0.10, 0.40, 0.40, 'DV')
    _puerta(msp, ax0+0.10, y_coc, 0.85)


# ─── Setup ────────────────────────────────────────────────────────────────────

def _setup_linetypes(doc):
    linetypes = {
        'DASHED': ('Dashed __ __ __', [0.6, 0.4, -0.2]),
        'CENTER': ('Center ___ . ___', [2.0, 1.4, -0.2, 0.2, -0.2]),
        'DASHDOT': ('Dash Dot __ . __', [1.4, 1.0, -0.2, 0.0, -0.2]),
    }
    for name, (desc, pat) in linetypes.items():
        if name not in doc.linetypes:
            doc.linetypes.new(name, dxfattribs={'description': desc, 'pattern': pat})

def _setup_textstyle(doc):
    if 'C4' not in doc.styles:
        doc.styles.new('C4', dxfattribs={'font': 'Arial.ttf'})

def _setup_layers(doc):
    specs = [
        ('TERRENO',      3, 50, 'Continuous'),
        ('RETIROS',      1, 18, 'DASHED'),
        ('EDIFICACION',  5, 70, 'Continuous'),
        ('EJES',       251,  9, 'CENTER'),
        ('CALLE',      251, 18, 'Continuous'),
        ('COTAS',      251, 13, 'Continuous'),
        ('COTAS_INT',  251,  9, 'Continuous'),
        ('TEXTO_EDIF',   5, 13, 'Continuous'),
        ('TEXTO_RET',    1,  9, 'Continuous'),
        ('DATOS',      251, 13, 'Continuous'),
        ('TITULO',       7, 50, 'Continuous'),
        ('HATCH_RET',    1,  9, 'Continuous'),
        ('MUROS',        7, 70, 'Continuous'),
        ('CIRCULACION',  4, 18, 'Continuous'),
        ('HABITACIONES', 4, 13, 'Continuous'),
        ('PUERTAS',      6, 25, 'Continuous'),
        ('VENTANAS',     4, 18, 'Continuous'),
        ('COLUMNAS',     7, 50, 'Continuous'),
        ('ESCALERAS',  251, 35, 'Continuous'),
        ('SOTANO_PKG',   2, 18, 'Continuous'),
        ('SOTANO_RAMP', 30, 35, 'Continuous'),
        ('DUCTOS',      30, 25, 'Continuous'),
        ('HATCH_HUMEDO', 4,  9, 'Continuous'),
        ('HATCH_CIRC',   4,  9, 'Continuous'),
        ('HATCH_ESC',  251,  9, 'Continuous'),
        ('HATCH_ESTRUCT',7,  9, 'Continuous'),
        ('GRUA',        30, 50, 'Continuous'),   # grúa base y etiquetas
        ('GRUA_RADIO',  30, 13, 'CENTER'),        # círculo de alcance
        ('CALLES',     251, 18, 'Continuous'),    # nombres de calles
    ]
    for nombre, color, lw, lt in specs:
        layer = doc.layers.new(nombre, dxfattribs={'color': color, 'linetype': lt})
        layer.dxf.lineweight = lw


# ─── Helpers geométricos ──────────────────────────────────────────────────────

def _rect(msp, x1, y1, x2, y2, layer, lw=25):
    msp.add_lwpolyline(
        [(x1,y1),(x2,y1),(x2,y2),(x1,y2)], close=True,
        dxfattribs={'layer': layer, 'lineweight': lw},
    )

def _hatch_any(msp, x1, y1, x2, y2, pattern, color, scale, layer='HATCH_RET', angle=0):
    try:
        h = msp.add_hatch(color=color, dxfattribs={'layer': layer})
        if pattern == 'SOLID':
            h.set_solid_fill()
        else:
            h.set_pattern_fill(pattern, scale=scale, angle=angle)
        h.paths.add_polyline_path([(x1,y1),(x2,y1),(x2,y2),(x1,y2)], is_closed=True)
    except Exception:
        pass

def _text(msp, x, y, txt, layer, h=0.30, center=False, rotation=0):
    t = msp.add_text(txt, dxfattribs={'layer': layer, 'height': h, 'style': 'C4', 'rotation': rotation})
    align = TextEntityAlignment.MIDDLE_CENTER if center else TextEntityAlignment.MIDDLE_LEFT
    t.set_placement((x, y), align=align)

def _room_label(msp, cx, ybase, room_h, nombre, area_m2):
    """Etiqueta de ambiente centrada: nombre + área, con texto auto-escalado.

    Estima el ancho del ambiente (area/alto) y reduce la fuente para que el
    rótulo no se desborde ni se solape con el ambiente vecino en plantas angostas.
    """
    ancho_amb = area_m2 / room_h if room_h > 0.1 else 2.0
    # Altura de texto proporcional al menor lado del ambiente
    lado_min = min(ancho_amb, room_h)
    h_name = max(0.13, min(0.24, lado_min * 0.16))
    h_area = max(0.11, h_name * 0.82)
    # Si el nombre no cabe a esa altura (~0.62 de ancho por caracter), abreviar
    if len(nombre) * h_name * 0.62 > ancho_amb * 0.92:
        nombre = _abreviar_ambiente(nombre)
    _text(msp, cx, ybase + room_h * 0.58, nombre,            'HABITACIONES', h_name, center=True)
    _text(msp, cx, ybase + room_h * 0.33, f'{area_m2:.1f} m2', 'DATOS',        h_area, center=True)


def _abreviar_ambiente(nombre: str) -> str:
    """Abrevia nombres largos de ambientes para plantas angostas."""
    mapa = {
        'DORM. PRINCIPAL': 'DORM.PPAL', 'BANO PPAL.': 'B.PPAL', 'BANO PRINCIPAL': 'B.PPAL',
        'SALA / COMEDOR': 'SALA-COM', 'SALA / DORMITORIO': 'SALA-DORM',
        'DORMITORIO': 'DORM.', 'COMEDOR': 'COM.', 'LAVAN.': 'LAV.',
    }
    return mapa.get(nombre, nombre)

def _columna(msp, cx, cy, size=0.30):
    h = size / 2
    _rect(msp, cx-h, cy-h, cx+h, cy+h, 'COLUMNAS', lw=50)
    _hatch_any(msp, cx-h, cy-h, cx+h, cy+h, 'SOLID', 7, 0.0, 'HATCH_ESTRUCT')

def _grilla_columnas(msp, x0, y0, ancho, prof, esp_x, esp_y):
    """Grilla de columnas con etiquetas A/B/C y 1/2/3."""
    letras = list(_string.ascii_uppercase)
    nx = round(ancho / esp_x); ny = round(prof / esp_y)
    cols_x = [x0 + i * esp_x for i in range(nx + 1)]
    cols_y = [y0 + j * esp_y for j in range(ny + 1)]

    for i, cx in enumerate(cols_x):
        for j, cy in enumerate(cols_y):
            _columna(msp, cx, cy, 0.28)
        # Etiquetas letra (eje X) arriba y abajo
        letra = letras[i % 26]
        _text(msp, cx, y0 - 1.0, letra, 'EJES', 0.28, center=True)
        _text(msp, cx, y0 + prof + 0.7, letra, 'EJES', 0.28, center=True)
        msp.add_line((cx, y0-0.5), (cx, y0+prof+0.3),
                     dxfattribs={'layer':'EJES','lineweight':9,'linetype':'CENTER'})
    for j, cy in enumerate(cols_y):
        # Etiquetas número (eje Y) izquierda y derecha
        _text(msp, x0-1.0, cy, str(j+1), 'EJES', 0.28, center=True)
        _text(msp, x0+ancho+0.7, cy, str(j+1), 'EJES', 0.28, center=True)
        msp.add_line((x0-0.5, cy), (x0+ancho+0.3, cy),
                     dxfattribs={'layer':'EJES','lineweight':9,'linetype':'CENTER'})

def _escalera_simbolo(msp, x0, y0, w, h):
    n = max(4, int(h / 0.28))
    for i in range(1, n):
        y = y0 + i * h / n
        msp.add_line((x0, y), (x0+w, y), dxfattribs={'layer':'ESCALERAS','lineweight':9})

def _parking_box(msp, px, py, w, h, num):
    _rect(msp, px, py, px+w, py+h, 'SOTANO_PKG', lw=18)
    _hatch_any(msp, px+0.05, py+0.05, px+w-0.05, py+h-0.05, 'ANSI37', 2, 0.28, 'SOTANO_PKG')
    _text(msp, px+w/2, py+h*0.70, f'E-{num:02d}', 'SOTANO_PKG', 0.24, center=True)
    _text(msp, px+w/2, py+h*0.40, f'{w:.1f}x{h:.1f}m', 'DATOS', 0.18, center=True)
    _text(msp, px+w/2, py+h*0.18, 'h=2.10m', 'DATOS', 0.16, center=True)

def _ducto(msp, x0, y0, w, h, label):
    """Ducto de ventilación con hatch y etiqueta."""
    _rect(msp, x0, y0, x0+w, y0+h, 'DUCTOS', lw=25)
    _hatch_any(msp, x0, y0, x0+w, y0+h, 'ANSI33', 30, 0.12, 'DUCTOS')
    # Líneas cruzadas (X)
    msp.add_line((x0, y0), (x0+w, y0+h), dxfattribs={'layer':'DUCTOS','lineweight':9})
    msp.add_line((x0+w, y0), (x0, y0+h), dxfattribs={'layer':'DUCTOS','lineweight':9})
    _text(msp, x0+w/2, y0-0.30, label, 'DUCTOS', 0.18, center=True)

def _puerta(msp, hinge_x, hinge_y, size=0.85):
    msp.add_line((hinge_x, hinge_y), (hinge_x+size, hinge_y),
                 dxfattribs={'layer':'PUERTAS','lineweight':18})
    try:
        msp.add_arc(center=(hinge_x, hinge_y), radius=size,
                    start_angle=0, end_angle=90,
                    dxfattribs={'layer':'PUERTAS','lineweight':9})
    except Exception:
        pass

def _ventana(msp, x1, y, x2, _y2=None):
    off = 0.08
    for dy in [-off, 0, off]:
        msp.add_line((x1, y+dy), (x2, y+dy),
                     dxfattribs={'layer':'VENTANAS','lineweight':9})

def _simbolo_cama(msp, ax0, ay0, w, h):
    cw = min(1.60, (w-0.5) * 0.60); ch = min(2.00, h * 0.50)
    cx = ax0 + (w - cw) / 2; cy = ay0 + h * 0.20
    _rect(msp, cx, cy, cx+cw, cy+ch, 'DATOS', lw=9)
    msp.add_line((cx, cy+ch*0.25), (cx+cw, cy+ch*0.25),
                 dxfattribs={'layer':'DATOS','lineweight':9})

def _posicion_optima_grua(frente_libre: float, prof_libre: float,
                          ret_frontal: float, ret_lateral: float,
                          base: float) -> tuple[float, float, str]:
    """
    Calcula la posición óptima de la base de la grúa en coordenadas del TERRENO.
    Retorna (x_base_izq, y_base_inf, descripcion).
    Origen = esquina inferior izquierda del terreno.
    """
    margen = 0.30  # distancia mínima a la línea de retiro
    b = base

    # Opción A: Retiro frontal suficiente → centrado al frente del edificio
    if ret_frontal >= b + margen * 2:
        gx = (frente_libre + b) / 2 - b  # centrado en el ancho libre + retiros
        # ajuste: gx desde el borde izquierdo del terreno = ret_lateral + building_x
        gx = ret_lateral + (frente_libre - b) / 2
        gy = margen
        return gx, gy, f'Retiro frontal (R.F. {ret_frontal:.1f}m)'

    # Opción B: Retiro lateral izquierdo suficiente → costado izquierdo
    if ret_lateral >= b + margen * 2:
        gx = margen
        gy = ret_frontal + (prof_libre - b) / 2
        return gx, gy, f'Retiro lateral izquierdo (R.L. {ret_lateral:.1f}m)'

    # Opción C: Retiros insuficientes → esquina frontal-izquierda del retiro
    # Grúa visible dentro del dibujo; nota indica necesidad de análisis municipal
    gx = ret_lateral + margen
    gy = margen
    return gx, gy, f'Esquina retiro frontal (RF={ret_frontal:.1f}m < base {b:.1f}m — requiere permiso)'


def _grua_en_plano(msp, e: 'EntradaPlano', ax0: float, ay0: float):
    """Dibuja posición óptima de grúa sobre el plano de ubicación."""
    if not e.grua_modelo or e.grua_radio_m <= 0:
        return

    base  = e.grua_base_m if e.grua_base_m > 0 else 3.2
    radio = e.grua_radio_m
    frente_libre = e.frente - 2 * e.retiro_lateral
    prof_libre   = e.fondo  - e.retiro_frontal - e.retiro_posterior

    rel_x, rel_y, descripcion = _posicion_optima_grua(
        frente_libre, prof_libre, e.retiro_frontal, e.retiro_lateral, base
    )
    gx = ax0 + rel_x
    gy = ay0 + rel_y
    cx = gx + base / 2
    cy = gy + base / 2

    # ── Símbolo: base cuadrada ANSI31 + borde grueso magenta ─────────────────
    _rect(msp, gx, gy, gx + base, gy + base, 'GRUA', lw=70)
    _hatch_any(msp, gx, gy, gx + base, gy + base, 'ANSI31', 6, 0.30, 'GRUA')
    # Cruz de centrado grande (visible a zoom terreno)
    d = base * 0.55
    msp.add_line((cx-d, cy), (cx+d, cy), dxfattribs={'layer':'GRUA','lineweight':35})
    msp.add_line((cx, cy-d), (cx, cy+d), dxfattribs={'layer':'GRUA','lineweight':35})
    # Etiqueta "G" sobre la base para identificarla rápidamente
    _text(msp, cx, cy + base * 0.25, 'G', 'GRUA', base * 0.35, center=True)

    # ── Cobertura: líneas punteadas al edificio ───────────────────────────────
    ex0 = ax0 + e.retiro_lateral
    ey0 = ay0 + e.retiro_frontal
    ex1 = ex0 + frente_libre
    ey1 = ey0 + prof_libre
    corners = [(ex0,ey0),(ex1,ey0),(ex1,ey1),(ex0,ey1)]
    dist_max = max(math.sqrt((cx-px)**2+(cy-py)**2) for px,py in corners)
    cubre = dist_max <= radio * 1.02

    # Línea desde grúa hasta la esquina más lejana (muestra el alcance real necesario)
    far_corner = max(corners, key=lambda p: math.sqrt((cx-p[0])**2+(cy-p[1])**2))
    msp.add_line((cx, cy), far_corner,
                 dxfattribs={'layer':'GRUA_RADIO','lineweight':9,'linetype':'DASHED'})
    # Pequeño arco de referencia dentro del terreno (radio = distancia a esquina lejana)
    # Solo si dist_max cabe dentro del dibujo razonablemente
    r_display = min(dist_max, max(e.frente, e.fondo) * 0.85)
    try:
        msp.add_circle((cx, cy), r_display,
                       dxfattribs={'layer':'GRUA_RADIO','lineweight':13,'linetype':'DASHED'})
    except Exception:
        pass

    # ── Cuadro de info — anclado en el retiro frontal, lado derecho ──────────
    RH    = 0.55
    box_w = min(e.frente * 0.58, 11.0)
    rl    = e.retiro_lateral if e.retiro_lateral > 0 else 0.0
    # Posición: justo sobre la línea de calle, lado derecho del retiro frontal
    box_x = ax0 + e.frente - rl - box_w - 0.15
    box_y = ay0 + 0.15

    cob_txt = ('CUBRE EDIFICIO COMPLETO  (dist.max=' + f'{dist_max:.1f}m < R={radio:.0f}m)'
               if cubre else f'COBERTURA PARCIAL  (dist.max={dist_max:.1f}m > R={radio:.0f}m)')
    lineas = [
        ('GRUA TORRE — POSICION OPTIMA', True),
        (f'Modelo: {e.grua_modelo.upper()}', False),
        (f'Radio pluma: {radio:.0f} m  |  Base: {base:.1f}x{base:.1f} m', False),
        (f'Posicion: {descripcion}', False),
        (cob_txt, False),
    ]
    total_h = len(lineas) * RH + 0.25
    _rect(msp, box_x, box_y, box_x + box_w, box_y + total_h, 'GRUA', lw=40)
    msp.add_line((box_x, box_y + total_h - RH * 1.45),
                 (box_x + box_w, box_y + total_h - RH * 1.45),
                 dxfattribs={'layer':'GRUA','lineweight':18})
    yi = box_y + total_h - RH * 0.65
    for texto, es_titulo in lineas:
        h_txt = 0.25 if es_titulo else 0.20
        if es_titulo:
            _text(msp, box_x + box_w / 2, yi, texto, 'GRUA', h_txt, center=True)
        else:
            _text(msp, box_x + 0.18, yi, texto, 'GRUA', h_txt)
        yi -= RH

    # Línea desde el cuadro al símbolo
    msp.add_line((box_x, box_y + total_h * 0.5), (cx, cy),
                 dxfattribs={'layer':'GRUA','lineweight':9})


def _calles_en_plano(msp, e: 'EntradaPlano', ax0: float, ay0: float, f: float, d: float):
    """Escribe los nombres de calles alrededor del terreno."""
    margen_txt = 2.5

    if e.calle_frontal:
        # Frente del terreno (parte inferior)
        nombre = f'VIA PUBLICA  —  {e.calle_frontal.upper()}'
        _text(msp, ax0 + f/2, ay0 - margen_txt, nombre, 'CALLES', 0.40, center=True)

    if e.calle_posterior:
        nombre = f'VIA PUBLICA  —  {e.calle_posterior.upper()}'
        _text(msp, ax0 + f/2, ay0 + d + margen_txt, nombre, 'CALLES', 0.32, center=True)

    if e.calle_lateral_izq:
        nombre = f'VIA PUBLICA  —  {e.calle_lateral_izq.upper()}'
        h = msp.add_text(nombre, dxfattribs={'layer':'CALLES','height':0.28,
                          'rotation':90})
        h.set_placement((ax0 - margen_txt, ay0 + d/2))

    if e.calle_lateral_der:
        nombre = f'VIA PUBLICA  —  {e.calle_lateral_der.upper()}'
        h = msp.add_text(nombre, dxfattribs={'layer':'CALLES','height':0.28,
                          'rotation':270})
        h.set_placement((ax0 + f + margen_txt, ay0 + d/2))


def _norte(msp, x, y, size=1.0):
    msp.add_circle((x,y), size*0.5, dxfattribs={'layer':'TITULO','lineweight':25})
    msp.add_line((x, y-size*0.5), (x, y+size*0.5), dxfattribs={'layer':'TITULO','lineweight':25})
    msp.add_line((x-size*0.2, y+size*0.1), (x, y+size*0.5),
                 dxfattribs={'layer':'TITULO','lineweight':25})
    msp.add_line((x+size*0.2, y+size*0.1), (x, y+size*0.5),
                 dxfattribs={'layer':'TITULO','lineweight':25})
    _text(msp, x, y+size*0.72, 'N', 'TITULO', 0.36, center=True)

def _barra_escala(msp, x0, y0, n=5, seg=1.0):
    """Barra de escala gráfica en metros."""
    H = 0.22
    for i in range(n):
        x = x0 + i * seg
        if i % 2 == 0:
            _hatch_any(msp, x, y0, x+seg, y0+H, 'SOLID', 7, 0.0, 'DATOS')
        _rect(msp, x, y0, x+seg, y0+H, 'DATOS', lw=9)
        msp.add_line((x, y0), (x, y0-0.12), dxfattribs={'layer':'DATOS','lineweight':9})
        _text(msp, x, y0-0.30, str(i), 'DATOS', 0.18, center=True)
    xe = x0 + n * seg
    msp.add_line((xe, y0), (xe, y0-0.12), dxfattribs={'layer':'DATOS','lineweight':9})
    _text(msp, xe, y0-0.30, f'{n}m', 'DATOS', 0.18, center=True)
    _text(msp, x0+n*seg/2, y0-0.56, 'ESCALA GRAFICA  (metros)', 'DATOS', 0.17, center=True)

def _titulo_hoja(msp, cx, ty, proyecto, subtitulo, datos):
    _text(msp, cx, ty+0.80, proyecto,  'TITULO', 0.58, center=True)
    _text(msp, cx, ty+0.05, subtitulo, 'TITULO', 0.33, center=True)
    _text(msp, cx, ty-0.50, datos,     'DATOS',  0.22, center=True)
    _text(msp, cx, ty-0.90, 'MOTOR C4 v3.0  -  PRE-INVERSION  -  ESC. REFERENCIAL',
          'DATOS', 0.17, center=True)


# ─── Leyenda ──────────────────────────────────────────────────────────────────

def _leyenda(msp, lx0, ly0):
    """Cuadro de leyenda con muestras de hatch."""
    items = [
        ('ANSI31', 1,   0.25, 'ZONA DE RETIRO NORMATIVO  (RNE A.020 Art.5)'),
        ('ANSI32', 4,   0.15, 'ZONA HUMEDA  (banos, cocina, lavanderia)'),
        ('ANSI33', 30,  0.12, 'DUCTO DE VENTILACION / EXTRACCION'),
        ('ANSI37', 2,   0.28, 'ESTACIONAMIENTO VEHICULAR  (2.50x5.00m)'),
        ('AR-SAND',251, 0.05, 'TERRAZA / BALCON / AREA EXTERIOR'),
        ('LINE',  251,  0.20, 'ESCALERA DE EVACUACION / NUCLEO VERTICAL'),
        ('DOTS',   4,   0.30, 'CIRCULACION / HALL COMUN'),
        ('SOLID',  7,   0.00, 'ELEMENTO ESTRUCTURAL  (Concreto Armado f\'c=210)'),
    ]
    W = 16.0; RH = 0.85
    total_h = (len(items) + 1.8) * RH
    _rect(msp, lx0, ly0, lx0+W, ly0+total_h, 'DATOS', lw=25)
    msp.add_line((lx0, ly0+total_h-RH*1.5), (lx0+W, ly0+total_h-RH*1.5),
                 dxfattribs={'layer':'DATOS','lineweight':25})
    _text(msp, lx0+W/2, ly0+total_h-RH*0.75,
          'LEYENDA DE MATERIALES Y ZONAS', 'TITULO', 0.30, center=True)

    for i, (pat, col, scale, label) in enumerate(items):
        yi = ly0 + total_h - (i + 2.2) * RH
        sx1, sx2 = lx0+0.20, lx0+2.00
        sy1, sy2 = yi+0.12, yi+RH-0.12
        _rect(msp, sx1, sy1, sx2, sy2, 'DATOS', lw=9)
        _hatch_any(msp, sx1, sy1, sx2, sy2, pat, col, scale, 'DATOS')
        _text(msp, lx0+2.30, yi+RH/2, label, 'DATOS', h=0.22)

    # Simbolos adicionales
    y_sim = ly0 + 0.30
    _text(msp, lx0+0.20, y_sim+0.10,
          'DV = Ducto Ventilacion  |  E-00 = Estacionamiento  |  '
          'Grilla: letras=ejes X / numeros=ejes Y',
          'DATOS', 0.18)
    _text(msp, lx0+0.20, y_sim-0.25,
          'Alturas libres min: vivienda 2.30m  |  banos 2.10m  |  sotano vehicular 2.10m  (RNE A.010 Art.18)',
          'DATOS', 0.17)


# ─── Cotas ────────────────────────────────────────────────────────────────────

def _cota_h(msp, x1l, yl, x2l, y2l, xp1, yp1, xp2, yp2, label):
    y = yl
    msp.add_line((xp1, yp1), (xp1, y+0.15), dxfattribs={'layer':'COTAS','lineweight':9})
    msp.add_line((xp2, yp2), (xp2, y+0.15), dxfattribs={'layer':'COTAS','lineweight':9})
    msp.add_line((xp1, y), (xp2, y), dxfattribs={'layer':'COTAS','lineweight':9})
    dl = 0.15
    for xi in [xp1, xp2]:
        msp.add_line((xi-dl*0.5, y-dl*0.5), (xi+dl*0.5, y+dl*0.5),
                     dxfattribs={'layer':'COTAS','lineweight':25})
    _text(msp, (xp1+xp2)/2, y+0.22, label, 'COTAS', h=0.25, center=True)

def _cota_v(msp, xl, y1l, x2l, y2l, xp1, yp1, xp2, yp2, label):
    x = xl
    msp.add_line((xp1, yp1), (x-0.15, yp1), dxfattribs={'layer':'COTAS','lineweight':9})
    msp.add_line((xp2, yp2), (x-0.15, yp2), dxfattribs={'layer':'COTAS','lineweight':9})
    msp.add_line((x, yp1), (x, yp2), dxfattribs={'layer':'COTAS','lineweight':9})
    dl = 0.15
    for yi in [yp1, yp2]:
        msp.add_line((x-dl*0.5, yi-dl*0.5), (x+dl*0.5, yi+dl*0.5),
                     dxfattribs={'layer':'COTAS','lineweight':25})
    _text(msp, x+0.22, (yp1+yp2)/2, label, 'COTAS', h=0.22, rotation=90)

def _cota_int_h(msp, x1, y, x2, _y2, label):
    """Cota interior horizontal entre ambientes."""
    off = 0.35
    msp.add_line((x1, y-off), (x2, y-off), dxfattribs={'layer':'COTAS_INT','lineweight':9})
    msp.add_line((x1, y), (x1, y-off-0.08), dxfattribs={'layer':'COTAS_INT','lineweight':9})
    msp.add_line((x2, y), (x2, y-off-0.08), dxfattribs={'layer':'COTAS_INT','lineweight':9})
    dl = 0.10
    for xi in [x1, x2]:
        msp.add_line((xi-dl*0.5, y-off-dl*0.5), (xi+dl*0.5, y-off+dl*0.5),
                     dxfattribs={'layer':'COTAS_INT','lineweight':13})
    _text(msp, (x1+x2)/2, y-off-0.20, label, 'COTAS_INT', h=0.20, center=True)

def _cota_int_v(msp, x, y1, _x2, y2, label):
    """Cota interior vertical."""
    off = 0.35
    msp.add_line((x-off, y1), (x-off, y2), dxfattribs={'layer':'COTAS_INT','lineweight':9})
    msp.add_line((x, y1), (x-off-0.08, y1), dxfattribs={'layer':'COTAS_INT','lineweight':9})
    msp.add_line((x, y2), (x-off-0.08, y2), dxfattribs={'layer':'COTAS_INT','lineweight':9})
    dl = 0.10
    for yi in [y1, y2]:
        msp.add_line((x-off-dl*0.5, yi-dl*0.5), (x-off+dl*0.5, yi+dl*0.5),
                     dxfattribs={'layer':'COTAS_INT','lineweight':13})
    _text(msp, x-off-0.22, (y1+y2)/2, label, 'COTAS_INT', h=0.20, rotation=90)


# ─── Cuadro de datos ──────────────────────────────────────────────────────────

def _cuadro_datos(msp, e: EntradaPlano, x0: float, y0: float):
    W = 11.0; RH = 0.65
    from dataclasses import fields as dc_fields

    pisos_tot = e.pisos_vivienda + e.sotanos * 3
    n_piso = round(e.num_departamentos / e.pisos_vivienda) if e.pisos_vivienda > 0 else 0
    area_prom = round(e.area_vendible_total / e.num_departamentos, 1) if e.num_departamentos > 0 else 0

    filas = [
        ('CUADRO DE AREAS Y DATOS', None, True),
        (None, None, None),
        ('Proyecto',          e.nombre_proyecto),
        ('Direccion',         (e.direccion[:35] if e.direccion else e.distrito)),
        ('Distrito',          e.distrito),
        ('Normativa',         (e.fuente_normativa[:30] if e.fuente_normativa else 'N/D')),
        (None, None, None),
        ('Area terreno',      f'{e.area_terreno:.1f} m2'),
        ('Frente',            f'{e.frente:.2f} m'),
        ('Fondo',             f'{e.fondo:.2f} m'),
        (None, None, None),
        ('Retiro frontal',    f'{e.retiro_frontal:.1f} m'),
        ('Retiro lateral',    f'{e.retiro_lateral:.1f} m'),
        ('Retiro posterior',  f'{e.retiro_posterior:.1f} m'),
        (None, None, None),
        ('Planta libre',      f'{e.planta_libre:.2f} m2'),
        ('Pisos vivienda',    f'{e.pisos_vivienda}'),
        ('Sotanos',           f'{e.sotanos}'),
        ('Dptos por piso',    f'{n_piso}'),
        ('Area construida',   f'{e.area_construida_bruta:.1f} m2'),
        ('Area vendible',     f'{e.area_vendible_total:.1f} m2'),
        ('N departamentos',   f'{e.num_departamentos}'),
        ('Area prom. depto',  f'{area_prom} m2'),
        ('Estacionamientos',  f'{e.estacionamientos_requeridos}'),
        ('CUS utilizado',     f'{e.cus_utilizado:.3f}'),
        ('Limitante',         (e.limitante[:20] if e.limitante else 'N/D')),
        (None, None, None),
        ('MOTOR C4 v3.0  -  PRE-INVERSION', None, True),
    ]

    total_h = len(filas) * RH
    _rect(msp, x0, y0, x0+W, y0+total_h, 'DATOS', lw=35)
    yi = y0 + total_h - RH * 0.65
    for row in filas:
        if len(row) > 2 and row[2] is True:
            _text(msp, x0+W/2, yi, row[0], 'TITULO', h=0.30, center=True)
        elif row[0] is None:
            msp.add_line((x0+0.1, yi+RH*0.2), (x0+W-0.1, yi+RH*0.2),
                         dxfattribs={'layer':'DATOS','lineweight':9,'color':251})
        else:
            _text(msp, x0+0.25, yi, str(row[0])+':', 'DATOS', h=0.23)
            if row[1]:
                t = msp.add_text(str(row[1]),
                                 dxfattribs={'layer':'DATOS','height':0.23,'style':'C4'})
                t.set_placement((x0+W-0.25, yi), align=TextEntityAlignment.MIDDLE_RIGHT)
        yi -= RH
