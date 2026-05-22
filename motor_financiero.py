"""
Motor Financiero — C4
Dado el resultado de cabida + precios del mercado → TIR, VAN, flujo de caja.

Parámetros de mercado por defecto (Lima 2026, actualizar según distrito):
  Costo construcción:  $800–1,200 USD/m² construido
  Precio venta:        $1,500–3,500 USD/m² vendible (varía mucho por distrito)
  Tiempo construcción: 18–24 meses según pisos
"""

import math
from dataclasses import dataclass, field


# ─── Precios por defecto (USD, mayo 2026) ──────────────────────────────────
COSTOS_CONSTRUCCION_USD_M2 = {
    "San Isidro":       1200,
    "Miraflores":       1150,
    "San Borja":        1000,
    "Santiago de Surco": 950,
    "La Molina":         950,
    "Barranco":          950,
    "Magdalena del Mar": 900,
    "Jesús María":       900,
    "Lince":             880,
    "San Miguel":        880,
    "default":           950,
}

PRECIOS_VENTA_USD_M2 = {
    "San Isidro":        3200,
    "Miraflores":        2800,
    "San Borja":         2200,
    "Santiago de Surco": 2000,
    "La Molina":         2100,
    "Barranco":          2000,
    "Magdalena del Mar": 1800,
    "Jesús María":       1700,
    "Lince":             1600,
    "San Miguel":        1600,
    "default":           1800,
}

# Costos adicionales como % del costo de construcción
COSTO_TERRENO_RATIO = 0.30        # 30% del costo total (variable, aquí como estimado)
COSTO_PROYECTOS_RATIO = 0.04      # 4% (arquitectura, ingeniería, licencias)
COSTO_VENTAS_RATIO = 0.03         # 3% comisión vendedores
COSTO_ADMIN_RATIO = 0.02          # 2% gerencia de proyecto
IGV = 0.18                        # 18% IGV sobre utilidad (simplificado)
TASA_DESCUENTO_ANUAL = 0.12       # 12% TDR (costo del capital)


@dataclass
class EntradaFinanciera:
    distrito: str
    area_vendible_m2: float
    area_construida_m2: float
    num_departamentos: int
    meses_construccion: int = 0    # 0 = calculado automáticamente
    precio_terreno_usd: float = 0  # 0 = estimado como % del costo construcción
    # Overrides opcionales
    costo_construccion_usd_m2: float = 0
    precio_venta_usd_m2: float = 0


@dataclass
class FlujoMes:
    mes: int
    ingresos: float
    egresos: float
    flujo_neto: float
    flujo_acumulado: float


@dataclass
class ResultadoFinanciero:
    # Ingresos
    ingreso_total_ventas_usd: float
    precio_venta_usd_m2: float

    # Costos
    costo_construccion_usd: float
    costo_terreno_usd: float
    costo_proyectos_usd: float
    costo_ventas_usd: float
    costo_admin_usd: float
    costo_total_usd: float
    costo_usd_m2_construido: float

    # Indicadores
    utilidad_bruta_usd: float
    utilidad_neta_usd: float        # después de IGV
    margen_bruto_pct: float
    tir_anual_pct: float
    van_usd: float                  # al 12% anual
    payback_meses: int

    # Flujo de caja
    meses_proyecto: int
    flujo_caja: list[FlujoMes]

    # Contexto
    punto_equilibrio_deptos: int    # departamentos mínimos a vender para cubrir costos


def calcular_financiero(entrada: EntradaFinanciera) -> ResultadoFinanciero:
    distrito = entrada.distrito

    # Precios
    costo_m2 = entrada.costo_construccion_usd_m2 or COSTOS_CONSTRUCCION_USD_M2.get(
        distrito, COSTOS_CONSTRUCCION_USD_M2["default"]
    )
    precio_m2 = entrada.precio_venta_usd_m2 or PRECIOS_VENTA_USD_M2.get(
        distrito, PRECIOS_VENTA_USD_M2["default"]
    )

    # Duración del proyecto
    meses_obra = entrada.meses_construccion or _estimar_meses(entrada.area_construida_m2)
    meses_preventa = 6     # preventa antes de iniciar obra
    meses_postventa = 3    # tiempo para vender después de terminado
    meses_total = meses_preventa + meses_obra + meses_postventa

    # Ingresos
    ingreso_ventas = entrada.area_vendible_m2 * precio_m2

    # Costos
    costo_construccion = entrada.area_construida_m2 * costo_m2
    costo_terreno = (
        entrada.precio_terreno_usd if entrada.precio_terreno_usd > 0
        else costo_construccion * COSTO_TERRENO_RATIO
    )
    costo_proyectos = costo_construccion * COSTO_PROYECTOS_RATIO
    costo_ventas = ingreso_ventas * COSTO_VENTAS_RATIO
    costo_admin = costo_construccion * COSTO_ADMIN_RATIO
    costo_total = costo_construccion + costo_terreno + costo_proyectos + costo_ventas + costo_admin

    # Utilidades
    utilidad_bruta = ingreso_ventas - costo_total
    igv_estimado = max(0, utilidad_bruta * IGV)
    utilidad_neta = utilidad_bruta - igv_estimado
    margen_bruto = (utilidad_bruta / ingreso_ventas * 100) if ingreso_ventas > 0 else 0

    # Flujo de caja mensual
    flujo = _construir_flujo(
        ingreso_ventas=ingreso_ventas,
        costo_terreno=costo_terreno,
        costo_construccion=costo_construccion,
        costo_proyectos=costo_proyectos,
        costo_ventas=costo_ventas,
        costo_admin=costo_admin,
        meses_preventa=meses_preventa,
        meses_obra=meses_obra,
        meses_postventa=meses_postventa,
    )

    # TIR y VAN
    flujos_netos = [f.flujo_neto for f in flujo]
    tir_mensual = _calcular_tir(flujos_netos)
    tir_anual = ((1 + tir_mensual) ** 12 - 1) * 100 if tir_mensual else 0

    tasa_mensual = (1 + TASA_DESCUENTO_ANUAL) ** (1 / 12) - 1
    van = sum(f / (1 + tasa_mensual) ** (i + 1) for i, f in enumerate(flujos_netos))

    # Payback
    payback = next(
        (f.mes for f in flujo if f.flujo_acumulado >= 0),
        meses_total
    )

    # Punto de equilibrio
    ingreso_por_depto = ingreso_ventas / entrada.num_departamentos if entrada.num_departamentos > 0 else 0
    punto_equilibrio = math.ceil(costo_total / ingreso_por_depto) if ingreso_por_depto > 0 else 0

    return ResultadoFinanciero(
        ingreso_total_ventas_usd=round(ingreso_ventas, 0),
        precio_venta_usd_m2=precio_m2,
        costo_construccion_usd=round(costo_construccion, 0),
        costo_terreno_usd=round(costo_terreno, 0),
        costo_proyectos_usd=round(costo_proyectos, 0),
        costo_ventas_usd=round(costo_ventas, 0),
        costo_admin_usd=round(costo_admin, 0),
        costo_total_usd=round(costo_total, 0),
        costo_usd_m2_construido=round(costo_total / entrada.area_construida_m2, 0) if entrada.area_construida_m2 > 0 else 0,
        utilidad_bruta_usd=round(utilidad_bruta, 0),
        utilidad_neta_usd=round(utilidad_neta, 0),
        margen_bruto_pct=round(margen_bruto, 1),
        tir_anual_pct=round(tir_anual, 1),
        van_usd=round(van, 0),
        payback_meses=payback,
        meses_proyecto=meses_total,
        flujo_caja=flujo,
        punto_equilibrio_deptos=punto_equilibrio,
    )


# ─── Helpers ───────────────────────────────────────────────────────────────
def _estimar_meses(area_construida: float) -> int:
    """Estimación empírica basada en área: ~1 mes por cada 300m² construidos."""
    meses = max(12, math.ceil(area_construida / 300))
    return min(meses, 36)  # cap en 36 meses


def _construir_flujo(
    ingreso_ventas: float,
    costo_terreno: float,
    costo_construccion: float,
    costo_proyectos: float,
    costo_ventas: float,
    costo_admin: float,
    meses_preventa: int,
    meses_obra: int,
    meses_postventa: int,
) -> list[FlujoMes]:
    meses_total = meses_preventa + meses_obra + meses_postventa
    flujo = []
    acumulado = 0.0

    for mes in range(1, meses_total + 1):
        egreso = 0.0
        ingreso = 0.0

        # Terreno: se paga al inicio
        if mes == 1:
            egreso += costo_terreno
            egreso += costo_proyectos

        # Construcción: distribuida en la fase de obra (S-curve simplificada)
        if meses_preventa < mes <= meses_preventa + meses_obra:
            mes_obra = mes - meses_preventa
            egreso += _scurve(mes_obra, meses_obra, costo_construccion)
            egreso += costo_admin / meses_obra

        # Ingresos: 30% en preventa, 70% al entregar
        if mes <= meses_preventa:
            ingreso += (0.30 * ingreso_ventas) / meses_preventa
        elif mes > meses_preventa + meses_obra:
            ingreso += (0.70 * ingreso_ventas) / meses_postventa

        # Costo de ventas: proporcional a ingresos
        if ingreso > 0:
            egreso += costo_ventas * (ingreso / ingreso_ventas)

        neto = ingreso - egreso
        acumulado += neto

        flujo.append(FlujoMes(
            mes=mes,
            ingresos=round(ingreso, 0),
            egresos=round(egreso, 0),
            flujo_neto=round(neto, 0),
            flujo_acumulado=round(acumulado, 0),
        ))

    return flujo


def _scurve(mes_obra: int, total_meses: int, costo_total: float) -> float:
    """Distribución S-curve del costo de construcción por mes."""
    # Función logística normalizada: más gasto en el medio del proyecto
    x = (mes_obra / total_meses - 0.5) * 10
    peso = 1 / (1 + math.exp(-x))
    # Derivada normalizada para dar la distribución mensual
    if mes_obra == 1:
        acum_prev = 0.0
    else:
        x_prev = ((mes_obra - 1) / total_meses - 0.5) * 10
        acum_prev = 1 / (1 + math.exp(-x_prev))
    return (peso - acum_prev) * costo_total


def _calcular_tir(flujos: list[float], max_iter: int = 1000, tol: float = 1e-6) -> float:
    """Calcula TIR mensual por método Newton-Raphson."""
    if not any(f > 0 for f in flujos) or not any(f < 0 for f in flujos):
        return 0.0

    tasa = 0.01  # estimado inicial: 1% mensual
    for _ in range(max_iter):
        van = sum(f / (1 + tasa) ** (i + 1) for i, f in enumerate(flujos))
        d_van = sum(-(i + 1) * f / (1 + tasa) ** (i + 2) for i, f in enumerate(flujos))
        if abs(d_van) < tol:
            break
        tasa_nueva = tasa - van / d_van
        if abs(tasa_nueva - tasa) < tol:
            tasa = tasa_nueva
            break
        tasa = tasa_nueva

    return tasa if -0.5 < tasa < 2.0 else 0.0
