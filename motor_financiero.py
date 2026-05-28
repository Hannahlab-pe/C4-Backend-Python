"""
Motor Financiero v2 — C4
Modelo de flujo de caja con 3 fases, curva de ventas realista,
financiamiento bancario opcional y estructura de costos completa.

TIR esperada para proyectos sanos en Lima: 18–35% anual
"""

import math
from dataclasses import dataclass
from typing import Optional


# ─── Precios de mercado (USD, Lima 2026) ─────────────────────────────────────

COSTO_CONST_USD_M2: dict = {
    "San Isidro":        1350,
    "Miraflores":        1300,
    "San Borja":         1150,
    "Santiago de Surco": 1050,
    "La Molina":         1050,
    "Barranco":          1000,
    "Magdalena del Mar":  980,
    "Jesús María":        970,
    "Lince":              950,
    "San Miguel":         950,
    "default":           1000,
}

PRECIO_VENTA_USD_M2: dict = {
    "San Isidro":        3500,
    "Miraflores":        3000,
    "San Borja":         2400,
    "Santiago de Surco": 2100,
    "La Molina":         2200,
    "Barranco":          2100,
    "Magdalena del Mar": 1900,
    "Jesús María":       1800,
    "Lince":             1700,
    "San Miguel":        1700,
    "default":           1900,
}

VELOCIDAD_VENTAS: dict = {          # unidades/mes promedio por distrito
    "San Isidro":        3.0,
    "Miraflores":        4.0,
    "San Borja":         3.5,
    "Santiago de Surco": 4.5,
    "La Molina":         3.0,
    "Barranco":          4.5,
    "Magdalena del Mar": 5.0,
    "Jesús María":       5.0,
    "Lince":             5.5,
    "San Miguel":        5.5,
    "default":           4.0,
}

# ─── Ratios de costo ─────────────────────────────────────────────────────────

R_ALCABALA    = 0.025   # 2.5% del terreno (alcabala 3% - exoneración 1ra viv + notaría)
R_LICENCIAS   = 0.060   # 6% construcción (diseño arq+estructural + trámites + licencia obra)
R_SUPERVISION = 0.020   # 2% construcción (supervisión técnica + ITV)
R_GERENCIA    = 0.030   # 3% construcción (gerencia de proyecto)
R_IMPREVISTOS = 0.030   # 3% construcción (contingencias)
R_MARKETING   = 0.020   # 2% ventas (publicidad + sala de ventas + renders)
R_CORRETAJE   = 0.030   # 3% ventas (comisión inmobiliaria)
R_TITULACION  = 0.015   # 1.5% ventas (SUNARP + notaría compraventa + independización)
R_IMPUESTOS   = 0.150   # 15% utilidad bruta (IGV + IR simplificado)

COSTO_DEMO_M2    = 45.0  # USD/m² demolición estructuras existentes
TASA_BANCO_ANUAL = 0.11  # 11% anual (crédito promotor inmobiliario Lima 2026)
TASA_BANCO_MENS  = (1 + TASA_BANCO_ANUAL) ** (1 / 12) - 1
PRESALES_MIN     = 0.30  # banco exige 30% preventas para desembolsar

MESES_PREOBRA     = 3    # compra terreno + licencias + diseño
MESES_POSTENTREGA = 4    # ventas residuales + titulación + SUNARP
TASA_DESCUENTO    = 0.12 # 12% anual (costo de capital del inversor)


# ─── Tipos de datos ──────────────────────────────────────────────────────────

@dataclass
class TipologiaDepto:
    tipo: str            # "studio" | "1_dorm" | "2_dorm" | "3_dorm"
    porcentaje: float    # % de unidades (0–100)
    precio_usd_m2: float


@dataclass
class EntradaFinanciera:
    distrito: str
    area_vendible_m2: float
    area_construida_m2: float
    num_departamentos: int
    precio_terreno_usd: float = 0
    precio_venta_usd_m2: float = 0
    area_demolicion_m2: float = 0
    porcentaje_capital_propio: float = 40.0    # % del costo total que aporta el inversor
    velocidad_ventas_mensual: float = 0         # 0 = default del distrito
    mezcla_tipologias: Optional[list[TipologiaDepto]] = None


@dataclass
class FlujoMes:
    mes: int
    fase: str
    ingresos: float
    egresos: float
    unidades_vendidas: float
    saldo_prestamo: float
    flujo_neto: float          # flujo del proyecto (total)
    flujo_equity: float        # flujo del inversor (solo su capital)
    flujo_equity_acum: float


@dataclass
class ResultadoFinanciero:
    # Ingresos
    ingreso_total_usd: float
    precio_venta_usd_m2: float

    # Costos desglosados
    costo_terreno_usd: float
    costo_alcabala_notaria_usd: float
    costo_demolicion_usd: float
    costo_licencias_diseno_usd: float
    costo_construccion_usd: float
    costo_supervision_usd: float
    costo_gerencia_usd: float
    costo_imprevistos_usd: float
    costo_marketing_usd: float
    costo_corretaje_usd: float
    costo_titulacion_usd: float
    costo_financiamiento_usd: float
    costo_total_usd: float
    costo_usd_m2_construido: float

    # Utilidad
    utilidad_bruta_usd: float
    impuestos_estimados_usd: float
    utilidad_neta_usd: float
    margen_neto_pct: float

    # Indicadores
    tir_anual_pct: float
    van_usd: float
    payback_meses: int
    punto_equilibrio_deptos: int

    # Timeline
    meses_preobra: int
    meses_construccion: int
    meses_postentrega: int
    meses_proyecto: int
    velocidad_ventas_mensual: float

    # Financiamiento
    monto_prestamo_usd: float
    porcentaje_capital_propio: float

    # Flujo
    flujo_caja: list[FlujoMes]


# ─── Motor principal ─────────────────────────────────────────────────────────

def calcular_financiero(entrada: EntradaFinanciera) -> ResultadoFinanciero:
    d = entrada.distrito

    costo_m2  = COSTO_CONST_USD_M2.get(d, COSTO_CONST_USD_M2["default"])
    precio_m2 = entrada.precio_venta_usd_m2 or _precio_ponderado(d, entrada.mezcla_tipologias)
    vel_ventas = entrada.velocidad_ventas_mensual or VELOCIDAD_VENTAS.get(d, VELOCIDAD_VENTAS["default"])

    meses_obra  = _estimar_meses_obra(entrada.area_construida_m2)
    meses_total = MESES_PREOBRA + meses_obra + MESES_POSTENTREGA

    # ── Costos ────────────────────────────────────────────────────────────────
    costo_terreno     = entrada.precio_terreno_usd or (entrada.area_vendible_m2 * precio_m2 * 0.18)
    costo_alcabala    = costo_terreno * R_ALCABALA
    costo_demolicion  = entrada.area_demolicion_m2 * COSTO_DEMO_M2
    costo_construccion = entrada.area_construida_m2 * costo_m2
    costo_licencias   = costo_construccion * R_LICENCIAS
    costo_supervision = costo_construccion * R_SUPERVISION
    costo_gerencia    = costo_construccion * R_GERENCIA
    costo_imprevistos = costo_construccion * R_IMPREVISTOS

    ingreso_total   = entrada.area_vendible_m2 * precio_m2
    costo_marketing = ingreso_total * R_MARKETING
    costo_corretaje = ingreso_total * R_CORRETAJE
    costo_titulacion = ingreso_total * R_TITULACION

    costo_operativo = (
        costo_terreno + costo_alcabala + costo_demolicion +
        costo_licencias + costo_construccion +
        costo_supervision + costo_gerencia + costo_imprevistos +
        costo_marketing + costo_corretaje + costo_titulacion
    )

    # ── Financiamiento bancario ────────────────────────────────────────────────
    # Banco solo financia la parte de construcción (no terreno ni pre-obra)
    capital_pct = entrada.porcentaje_capital_propio / 100.0
    monto_banco = max(0.0, costo_construccion * (1.0 - capital_pct))

    # ── Curva de ventas ────────────────────────────────────────────────────────
    ventas_por_mes = _distribuir_ventas(
        num_departamentos=entrada.num_departamentos,
        vel_ventas=vel_ventas,
        meses_preobra=MESES_PREOBRA,
        meses_obra=meses_obra,
        meses_postentrega=MESES_POSTENTREGA,
    )
    ingreso_por_depto = ingreso_total / entrada.num_departamentos if entrada.num_departamentos > 0 else 0

    # ── Flujo mensual ──────────────────────────────────────────────────────────
    flujo, costo_financiamiento = _construir_flujo(
        meses_preobra=MESES_PREOBRA,
        meses_obra=meses_obra,
        meses_postentrega=MESES_POSTENTREGA,
        costo_terreno=costo_terreno,
        costo_alcabala=costo_alcabala,
        costo_demolicion=costo_demolicion,
        costo_licencias=costo_licencias,
        costo_construccion=costo_construccion,
        costo_supervision=costo_supervision,
        costo_gerencia=costo_gerencia,
        costo_imprevistos=costo_imprevistos,
        costo_marketing=costo_marketing,
        costo_corretaje=costo_corretaje,
        costo_titulacion=costo_titulacion,
        ventas_por_mes=ventas_por_mes,
        ingreso_por_depto=ingreso_por_depto,
        monto_banco=monto_banco,
        ingreso_total=ingreso_total,
    )

    costo_total = costo_operativo + costo_financiamiento

    # ── Indicadores ───────────────────────────────────────────────────────────
    utilidad_bruta = ingreso_total - costo_total
    impuestos      = max(0.0, utilidad_bruta * R_IMPUESTOS)
    utilidad_neta  = utilidad_bruta - impuestos
    margen_neto    = (utilidad_neta / ingreso_total * 100) if ingreso_total > 0 else 0

    flujos_equity = [f.flujo_equity for f in flujo]
    tir_mensual   = _tir(flujos_equity)
    tir_anual     = ((1 + tir_mensual) ** 12 - 1) * 100 if tir_mensual else 0

    tasa_m = (1 + TASA_DESCUENTO) ** (1 / 12) - 1
    van = sum(f / (1 + tasa_m) ** (i + 1) for i, f in enumerate(flujos_equity))

    payback     = next((f.mes for f in flujo if f.flujo_equity_acum >= 0), meses_total)
    ing_x_depto = ingreso_total / entrada.num_departamentos if entrada.num_departamentos > 0 else 1
    punto_eq    = math.ceil(costo_total / ing_x_depto) if ing_x_depto > 0 else 0

    return ResultadoFinanciero(
        ingreso_total_usd          = round(ingreso_total, 0),
        precio_venta_usd_m2        = round(precio_m2, 0),
        costo_terreno_usd          = round(costo_terreno, 0),
        costo_alcabala_notaria_usd = round(costo_alcabala, 0),
        costo_demolicion_usd       = round(costo_demolicion, 0),
        costo_licencias_diseno_usd = round(costo_licencias, 0),
        costo_construccion_usd     = round(costo_construccion, 0),
        costo_supervision_usd      = round(costo_supervision, 0),
        costo_gerencia_usd         = round(costo_gerencia, 0),
        costo_imprevistos_usd      = round(costo_imprevistos, 0),
        costo_marketing_usd        = round(costo_marketing, 0),
        costo_corretaje_usd        = round(costo_corretaje, 0),
        costo_titulacion_usd       = round(costo_titulacion, 0),
        costo_financiamiento_usd   = round(costo_financiamiento, 0),
        costo_total_usd            = round(costo_total, 0),
        costo_usd_m2_construido    = round(costo_total / entrada.area_construida_m2, 0) if entrada.area_construida_m2 > 0 else 0,
        utilidad_bruta_usd         = round(utilidad_bruta, 0),
        impuestos_estimados_usd    = round(impuestos, 0),
        utilidad_neta_usd          = round(utilidad_neta, 0),
        margen_neto_pct            = round(margen_neto, 1),
        tir_anual_pct              = round(tir_anual, 1),
        van_usd                    = round(van, 0),
        payback_meses              = payback,
        punto_equilibrio_deptos    = punto_eq,
        meses_preobra              = MESES_PREOBRA,
        meses_construccion         = meses_obra,
        meses_postentrega          = MESES_POSTENTREGA,
        meses_proyecto             = meses_total,
        velocidad_ventas_mensual   = vel_ventas,
        monto_prestamo_usd         = round(monto_banco, 0),
        porcentaje_capital_propio  = entrada.porcentaje_capital_propio,
        flujo_caja                 = flujo,
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _precio_ponderado(distrito: str, mezcla: Optional[list[TipologiaDepto]]) -> float:
    base = PRECIO_VENTA_USD_M2.get(distrito, PRECIO_VENTA_USD_M2["default"])
    if not mezcla:
        return base
    total_pct = sum(t.porcentaje for t in mezcla)
    if total_pct <= 0:
        return base
    return sum(t.precio_usd_m2 * (t.porcentaje / total_pct) for t in mezcla)


def _estimar_meses_obra(area_construida: float) -> int:
    """Lima promedio: ~280 m² de área construida por mes de avance."""
    return max(12, min(math.ceil(area_construida / 280), 30))


def _distribuir_ventas(
    num_departamentos: int,
    vel_ventas: float,
    meses_preobra: int,
    meses_obra: int,
    meses_postentrega: int,
) -> list[float]:
    """
    Distribuye unidades vendidas por mes — curva realista Lima:
      Pre-obra (preventa):  50% de la velocidad, máx 25% del total
      Construcción:         velocidad normal
      Post-entrega:         40% de la velocidad (difícil vender sin entrega)
    """
    meses_total = meses_preobra + meses_obra + meses_postentrega
    ventas = [0.0] * meses_total
    vendidas = 0.0

    for i in range(meses_total):
        if vendidas >= num_departamentos:
            break

        if i < meses_preobra:
            # Preventa limitada — banco exige acumular 30% antes de desembolsar
            vel = vel_ventas * 0.5
            tope_preventa = num_departamentos * 0.25
            unidades = min(vel, max(0, tope_preventa - vendidas), num_departamentos - vendidas)
        elif i < meses_preobra + meses_obra:
            vel = vel_ventas
            unidades = min(vel, num_departamentos - vendidas)
        else:
            vel = vel_ventas * 0.4
            unidades = min(vel, num_departamentos - vendidas)

        ventas[i] = round(unidades, 3)
        vendidas += unidades

    return ventas


def _scurve(mes_obra: int, total_meses: int, costo_total: float) -> float:
    """Distribución S-curve del costo de construcción mensual."""
    x      = (mes_obra / total_meses - 0.5) * 10
    acum   = 1 / (1 + math.exp(-x))
    x_prev = ((mes_obra - 1) / total_meses - 0.5) * 10 if mes_obra > 1 else None
    acum_p = 1 / (1 + math.exp(-x_prev)) if x_prev is not None else 0.0
    return (acum - acum_p) * costo_total


def _construir_flujo(
    meses_preobra: int,
    meses_obra: int,
    meses_postentrega: int,
    costo_terreno: float,
    costo_alcabala: float,
    costo_demolicion: float,
    costo_licencias: float,
    costo_construccion: float,
    costo_supervision: float,
    costo_gerencia: float,
    costo_imprevistos: float,
    costo_marketing: float,
    costo_corretaje: float,
    costo_titulacion: float,
    ventas_por_mes: list[float],
    ingreso_por_depto: float,
    monto_banco: float,
    ingreso_total: float,
) -> tuple[list[FlujoMes], float]:
    meses_total       = meses_preobra + meses_obra + meses_postentrega
    flujo             = []
    acum_equity       = 0.0
    saldo_banco       = 0.0
    banco_desembolsado = 0.0
    acum_ingresos     = 0.0
    banco_habilitado  = False
    total_intereses   = 0.0

    for i in range(meses_total):
        mes  = i + 1
        fase = ("Pre-obra" if mes <= meses_preobra
                else "Construcción" if mes <= meses_preobra + meses_obra
                else "Post-entrega")

        egreso = 0.0
        ingreso = 0.0

        # ── Egresos ────────────────────────────────────────────────────────
        if mes == 1:
            egreso += costo_terreno + costo_alcabala + costo_demolicion

        if mes <= meses_preobra:
            egreso += costo_licencias / meses_preobra

        if meses_preobra < mes <= meses_preobra + meses_obra:
            mes_obra = mes - meses_preobra
            egreso += _scurve(mes_obra, meses_obra, costo_construccion)
            egreso += (costo_supervision + costo_gerencia + costo_imprevistos) / meses_obra

        # ── Ingresos ───────────────────────────────────────────────────────
        unidades_mes = ventas_por_mes[i]
        ingreso_mes  = unidades_mes * ingreso_por_depto
        ingreso     += ingreso_mes
        acum_ingresos += ingreso_mes

        # Marketing + corretaje proporcional a ventas del mes
        if ingreso_mes > 0 and ingreso_total > 0:
            ratio = ingreso_mes / ingreso_total
            egreso += (costo_marketing + costo_corretaje) * ratio

        # Titulación en post-entrega proporcional
        if fase == "Post-entrega" and ingreso_mes > 0 and ingreso_total > 0:
            egreso += costo_titulacion * (ingreso_mes / ingreso_total)
        # También titulación de entregas al final de obra
        if fase == "Construcción" and mes == meses_preobra + meses_obra and ingreso_total > 0:
            ventas_previas = sum(ventas_por_mes[:i]) * ingreso_por_depto
            if ventas_previas > 0:
                egreso += costo_titulacion * (ventas_previas / ingreso_total) * 0.5

        # ── Banco ──────────────────────────────────────────────────────────
        desembolso_banco = 0.0
        repago_banco     = 0.0
        interes_mes      = 0.0

        if monto_banco > 0:
            if not banco_habilitado and ingreso_total > 0:
                if acum_ingresos >= ingreso_total * PRESALES_MIN:
                    banco_habilitado = True

            # Desembolso en tractos durante la obra
            if banco_habilitado and fase == "Construcción":
                mes_obra = mes - meses_preobra
                avance_acum   = sum(_scurve(k, meses_obra, 1.0) for k in range(1, mes_obra + 1))
                avance_target = avance_acum * monto_banco
                desembolso_banco = max(0.0, avance_target - banco_desembolsado)
                desembolso_banco = min(desembolso_banco, monto_banco - banco_desembolsado)
                banco_desembolsado += desembolso_banco
                saldo_banco        += desembolso_banco

            # Interés sobre saldo vivo
            if saldo_banco > 0:
                interes_mes      = saldo_banco * TASA_BANCO_MENS
                total_intereses += interes_mes
                egreso          += interes_mes

            # Repago con ingresos post-entrega
            if fase == "Post-entrega" and saldo_banco > 0:
                repago_banco = min(saldo_banco, max(0.0, ingreso - egreso + interes_mes))
                saldo_banco  = max(0.0, saldo_banco - repago_banco)
                egreso      += repago_banco

        # ── Flujo del inversor ─────────────────────────────────────────────
        aporte_inv    = egreso - desembolso_banco - repago_banco
        flujo_equity  = ingreso - max(0.0, aporte_inv)
        acum_equity  += flujo_equity

        flujo.append(FlujoMes(
            mes=mes,
            fase=fase,
            ingresos=round(ingreso, 0),
            egresos=round(egreso, 0),
            unidades_vendidas=round(unidades_mes, 2),
            saldo_prestamo=round(saldo_banco, 0),
            flujo_neto=round(ingreso - egreso, 0),
            flujo_equity=round(flujo_equity, 0),
            flujo_equity_acum=round(acum_equity, 0),
        ))

    return flujo, round(total_intereses, 0)


def _tir(flujos: list[float], max_iter: int = 1000, tol: float = 1e-7) -> float:
    """TIR mensual por Newton-Raphson."""
    if not any(f > 0 for f in flujos) or not any(f < 0 for f in flujos):
        return 0.0

    tasa = 0.02
    for _ in range(max_iter):
        van   = sum(f / (1 + tasa) ** (i + 1) for i, f in enumerate(flujos))
        d_van = sum(-(i + 1) * f / (1 + tasa) ** (i + 2) for i, f in enumerate(flujos))
        if abs(d_van) < tol:
            break
        nueva = tasa - van / d_van
        if abs(nueva - tasa) < tol:
            tasa = nueva
            break
        tasa = nueva

    return tasa if -0.5 < tasa < 1.0 else 0.0
