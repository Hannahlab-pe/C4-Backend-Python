"""
Motor de Cabida Arquitectónica — C4
Dado un terreno + normativa municipal → calcula máxima área vendible y distribución por pisos.

Lógica:
  1. Planta libre = terreno descontando retiros
  2. Pisos posibles = min(pisos_max_normativa, pisos_por_CUS)
  3. Área construida bruta = planta_libre × pisos
  4. Área vendible ≈ área bruta × 0.78  (circulación, muros, ductos)
  5. Departamentos = floor(área_vendible / área_min_depto)
  6. Estacionamientos = ceil(deptos × ratio_estac) → en sótano si no caben en PB
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# ─── Constantes del oficio ─────────────────────────────────────────────────
FACTOR_VENDIBLE = 0.78          # 78% del bruto es vendible (promedio Lima)
M2_POR_ESTACIONAMIENTO = 12.5   # 2.5m × 5m por cajón
ALTURA_PISO_ML = 3.0            # metros por piso (piso a piso)
ALTURA_SOTANO_ML = 3.5          # mayor por instalaciones
MAX_SOTANOS = 2                 # máximo razonable de sótanos

# Área típica neta por tipología (m²) — usado para calcular cantidad real de deptos
AREA_POR_TIPO: dict[str, float] = {
    'studio': 35.0, 'monoambiente': 35.0, 'estudio': 35.0,
    '1dorm': 50.0,  '1_dorm': 50.0,
    '2dorm': 70.0,  '2_dorm': 70.0,
    '3dorm': 100.0, '3_dorm': 100.0,
}


# ─── Tipos de entrada ──────────────────────────────────────────────────────
@dataclass
class DatosTerreno:
    area_total: float               # m²
    frente: Optional[float] = None  # metros lineales (calle)
    fondo: Optional[float] = None   # metros lineales (interior)
    # Si no se dan frente/fondo se asume proporción 1:1.5 (frente:fondo)


@dataclass
class Normativa:
    distrito: str
    pisos_max: int
    retiro_frontal: float    # metros
    retiro_lateral: float    # metros (cada lado)
    retiro_posterior: float  # metros
    cus: float               # coeficiente de uso del suelo
    area_min_depto: float    # m² por departamento
    estacionamientos: float  # cajones por departamento (puede ser fracción: 1 cada 3 deptos)


# ─── Tipos de salida ───────────────────────────────────────────────────────
@dataclass
class PlantaPiso:
    numero_piso: int         # 1 = primer piso, 0 = planta baja, -1 = sótano
    uso: str                 # "vivienda" | "estacionamiento" | "lobby"
    area_bruta: float        # m²
    area_vendible: float     # m²
    num_departamentos: int


@dataclass
class ResultadoCabida:
    # Terreno
    area_terreno: float
    frente: float
    fondo: float

    # Geometría resultante
    planta_libre: float          # m² de huella libre tras retiros
    pisos_vivienda: int          # pisos de departamentos
    sotanos: int                 # sótanos para estacionamiento

    # Áreas
    area_construida_bruta: float  # m² totales construidos
    area_vendible_total: float    # m² vendibles
    area_no_vendible: float       # circulación, muros, ductos

    # Programa
    num_departamentos: int
    estacionamientos_requeridos: int
    estacionamientos_en_sotano: int
    estacionamientos_en_pb: int

    # Distribución por pisos
    pisos: list[PlantaPiso]

    # Restricciones aplicadas
    limitante: str               # "pisos_normativa" | "cus" (cuál fue el factor limitante)
    cumple_cus: bool
    cus_utilizado: float


# ─── Motor principal ───────────────────────────────────────────────────────
def _area_efectiva_depto(mezcla: list, area_min: float) -> float:
    """Área promedio ponderada según mezcla de tipologías. Nunca baja del mínimo normativo."""
    if not mezcla:
        return area_min
    total_pct = sum(float(t.get('porcentaje', 0)) for t in mezcla)
    if total_pct <= 0:
        return area_min
    def _norm(s: str) -> str:
        return s.lower().replace('-', '').replace(' ', '').replace('_', '')
    avg = sum(
        AREA_POR_TIPO.get(_norm(t.get('tipo', '')), 70.0) * float(t.get('porcentaje', 0))
        for t in mezcla
    ) / total_pct
    return max(area_min, round(avg, 1))


def calcular_cabida(terreno: DatosTerreno, normativa: Normativa, mezcla_tipologias: list = None) -> ResultadoCabida:
    # 1. Dimensiones del terreno
    frente, fondo = _inferir_dimensiones(terreno)

    # 2. Planta libre (huella disponible para construir)
    ancho_libre = max(0.0, frente - 2 * normativa.retiro_lateral)
    fondo_libre = max(0.0, fondo - normativa.retiro_frontal - normativa.retiro_posterior)
    planta_libre = ancho_libre * fondo_libre

    if planta_libre <= 0:
        raise ValueError(
            f"Terreno {frente}×{fondo}m insuficiente para aplicar retiros "
            f"(frontal {normativa.retiro_frontal}m + posterior {normativa.retiro_posterior}m "
            f"+ lateral {normativa.retiro_lateral}m c/lado)"
        )

    # 3. Pisos máximos por CUS
    area_max_por_cus = normativa.cus * terreno.area_total
    pisos_por_cus = math.floor(area_max_por_cus / planta_libre)

    # 4. Pisos finales (el más restrictivo)
    pisos_vivienda = min(normativa.pisos_max, pisos_por_cus)
    pisos_vivienda = max(1, pisos_vivienda)  # mínimo 1 piso
    limitante = "pisos_normativa" if normativa.pisos_max <= pisos_por_cus else "cus"

    # 5. Áreas totales
    area_construida_bruta = planta_libre * pisos_vivienda
    area_vendible_total = area_construida_bruta * FACTOR_VENDIBLE
    area_no_vendible = area_construida_bruta - area_vendible_total

    # 6. Departamentos — usa área efectiva de la mezcla si el usuario la definió
    area_depto_efectiva = _area_efectiva_depto(mezcla_tipologias or [], normativa.area_min_depto)
    num_departamentos = math.floor(area_vendible_total / area_depto_efectiva)

    # 7. Estacionamientos
    estacionamientos_requeridos = math.ceil(num_departamentos * normativa.estacionamientos)
    m2_estacionamiento = estacionamientos_requeridos * M2_POR_ESTACIONAMIENTO

    # ¿Caben en planta baja?
    estac_en_pb = min(
        estacionamientos_requeridos,
        math.floor(planta_libre * 0.85 / M2_POR_ESTACIONAMIENTO)  # 85% de PB para estac.
    )
    estac_en_sotano = estacionamientos_requeridos - estac_en_pb

    # ¿Cuántos sótanos necesitamos?
    estac_por_sotano = math.floor(planta_libre * 0.85 / M2_POR_ESTACIONAMIENTO)
    sotanos_necesarios = math.ceil(estac_en_sotano / estac_por_sotano) if estac_por_sotano > 0 else 0
    sotanos = min(sotanos_necesarios, MAX_SOTANOS)

    # 8. Distribución por pisos
    pisos_detalle = _distribuir_pisos(
        pisos_vivienda=pisos_vivienda,
        planta_libre=planta_libre,
        sotanos=sotanos,
        estac_en_pb=estac_en_pb,
        estac_en_sotano=estac_en_sotano,
        area_min_depto=area_depto_efectiva,
        estac_por_sotano=estac_por_sotano,
    )

    # 9. CUS utilizado
    cus_utilizado = round(area_construida_bruta / terreno.area_total, 3)

    return ResultadoCabida(
        area_terreno=terreno.area_total,
        frente=frente,
        fondo=fondo,
        planta_libre=round(planta_libre, 2),
        pisos_vivienda=pisos_vivienda,
        sotanos=sotanos,
        area_construida_bruta=round(area_construida_bruta, 2),
        area_vendible_total=round(area_vendible_total, 2),
        area_no_vendible=round(area_no_vendible, 2),
        num_departamentos=num_departamentos,
        estacionamientos_requeridos=estacionamientos_requeridos,
        estacionamientos_en_sotano=estac_en_sotano,
        estacionamientos_en_pb=estac_en_pb,
        pisos=pisos_detalle,
        limitante=limitante,
        cumple_cus=cus_utilizado <= normativa.cus,
        cus_utilizado=cus_utilizado,
    )


# ─── Helpers ───────────────────────────────────────────────────────────────
def _inferir_dimensiones(terreno: DatosTerreno) -> tuple[float, float]:
    if terreno.frente and terreno.fondo:
        return terreno.frente, terreno.fondo

    # Sin dimensiones: asume proporción 1:1.5 (frente más corto, fondo más largo)
    # Proporción típica de lotes en Lima
    fondo = math.sqrt(terreno.area_total * 1.5)
    frente = terreno.area_total / fondo
    return round(frente, 2), round(fondo, 2)


def _distribuir_pisos(
    pisos_vivienda: int,
    planta_libre: float,
    sotanos: int,
    estac_en_pb: int,
    estac_en_sotano: int,
    area_min_depto: float,
    estac_por_sotano: int,
) -> list[PlantaPiso]:
    resultado = []

    # Sótanos
    for s in range(sotanos, 0, -1):
        estac_este_sotano = min(estac_en_sotano, estac_por_sotano)
        estac_en_sotano -= estac_este_sotano
        resultado.append(PlantaPiso(
            numero_piso=-s,
            uso="estacionamiento",
            area_bruta=round(planta_libre, 2),
            area_vendible=0.0,
            num_departamentos=0,
        ))

    # Planta baja
    if estac_en_pb > 0:
        area_estac = estac_en_pb * M2_POR_ESTACIONAMIENTO
        area_lobby = planta_libre * 0.15
        resultado.append(PlantaPiso(
            numero_piso=0,
            uso="lobby + estacionamiento",
            area_bruta=round(planta_libre, 2),
            area_vendible=0.0,
            num_departamentos=0,
        ))
    else:
        resultado.append(PlantaPiso(
            numero_piso=0,
            uso="lobby + hall",
            area_bruta=round(planta_libre * 0.20, 2),
            area_vendible=0.0,
            num_departamentos=0,
        ))

    # Pisos de vivienda
    for p in range(1, pisos_vivienda + 1):
        area_bruta_piso = planta_libre
        area_vendible_piso = area_bruta_piso * FACTOR_VENDIBLE
        deptos_piso = math.floor(area_vendible_piso / area_min_depto)
        resultado.append(PlantaPiso(
            numero_piso=p,
            uso="vivienda",
            area_bruta=round(area_bruta_piso, 2),
            area_vendible=round(area_vendible_piso, 2),
            num_departamentos=deptos_piso,
        ))

    return resultado
