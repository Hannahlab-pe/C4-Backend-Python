"""
Valores calibrados: lo que un experto confirmó o corrigió, y que reemplaza a la
constante que el motor trae por defecto.

El backend manda un diccionario {clave: numero} con lo que ya fue APROBADO en C4.
Las claves son las mismas de `c4-backend/src/calibracion/catalogo.ts`. Los numeros
llegan tal como los dijo el experto ("8" para un 8%), asi que la conversion a la
forma que usa el motor (0.08) se hace aca, que es donde vive esa convencion.

Si una clave no viene, o viene mal, se usa el valor por defecto de siempre: el
motor nunca se queda sin numero.
"""

from typing import Optional
import unicodedata


Calibracion = Optional[dict]


def _crudo(cal: Calibracion, clave: str):
    if not cal:
        return None
    v = cal.get(clave)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / infinito
        return None
    return float(v)


def num(cal: Calibracion, clave: str, defecto: float) -> float:
    """Valor tal cual (USD/m², metros, meses, un multiplicador...)."""
    v = _crudo(cal, clave)
    return defecto if v is None else v


def pct(cal: Calibracion, clave: str, defecto: float) -> float:
    """
    El experto responde en porcentaje ("8") y el motor trabaja con la fraccion (0.08).
    Se tolera que alguien haya cargado ya la fraccion: un 0.08 se deja como esta.
    """
    v = _crudo(cal, clave)
    if v is None:
        return defecto
    return v / 100.0 if v > 1 else v


def slug(texto: str) -> str:
    """'Jesús María' -> 'jesus_maria', igual que en catalogo.ts."""
    s = unicodedata.normalize("NFD", texto or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    fuera = []
    for c in s:
        fuera.append(c if c.isalnum() else "_")
    # colapsar separadores repetidos
    limpio, previo = [], ""
    for c in fuera:
        if c == "_" and previo == "_":
            continue
        limpio.append(c)
        previo = c
    return "".join(limpio).strip("_")


def por_distrito(cal: Calibracion, prefijo: str, distrito: str, defecto: float) -> float:
    """Tablas por distrito: precio_venta_jesus_maria, factor_zona_miraflores..."""
    return num(cal, f"{prefijo}_{slug(distrito)}", defecto)
