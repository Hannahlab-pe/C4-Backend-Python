"""
Motor de Predimensionamiento Estructural Empírico — C4
Metodología simplificada para estimación pre-ETABS.

Fórmulas:
  Peralte viga  = L / 12   (L = luz libre entre apoyos)
  Peralte losa  = L / 30   (losa aligerada una dirección)
  Columna       = sqrt(P / (0.45 * f'c))  donde P = carga tributaria
  Acero vigas   = ρ_min × b × d  (ρ_min = 0.0033 para f'c=210)
  Concreto      = volumen estructural × 2.4 t/m³
"""

import math
from dataclasses import dataclass


# ─── Constantes ────────────────────────────────────────────────────────────
FC_KGF_CM2 = 210        # f'c resistencia concreto (kg/cm²) — estándar Lima
FY_KGF_CM2 = 4200       # fy acero corrugado grado 60
CARGA_VIVA_KGF_M2 = 200 # sobrecarga de servicio vivienda (kg/m²)
CARGA_MUERTA_KGF_M2 = 500  # carga muerta total estimada (losa + acabados + muros)
PESO_CONCRETO_TM3 = 2.4    # ton/m³


@dataclass
class EntradaEstructural:
    area_piso: float       # m² por piso (planta libre)
    num_pisos: int         # pisos sobre terreno
    luz_tipica: float = 5.0  # metros (luz libre entre columnas, típico Lima: 4-6m)


@dataclass
class ElementoEstructural:
    nombre: str
    dimension_cm: str      # descripción de la sección
    cantidad_estimada: int
    volumen_concreto_m3: float
    acero_kg: float


@dataclass
class ResultadoEstructural:
    # Vigas principales
    peralte_viga_cm: float
    base_viga_cm: float
    vigas: ElementoEstructural

    # Losas
    espesor_losa_cm: float
    losas: ElementoEstructural

    # Columnas
    lado_columna_cm: float
    columnas: ElementoEstructural

    # Totales
    concreto_total_m3: float
    acero_total_kg: float
    acero_total_ton: float

    # Metrado de materiales (estimado)
    concreto_fc210_m3: float
    acero_fy4200_kg: float


def predimensionar(entrada: EntradaEstructural) -> ResultadoEstructural:
    L = entrada.luz_tipica   # luz libre en metros
    n = entrada.num_pisos
    A = entrada.area_piso

    # ── 1. Vigas ────────────────────────────────────────────────────────────
    h_viga_m = L / 12                            # peralte viga (m)
    h_viga_cm = round(h_viga_m * 100 / 5) * 5   # redondear a múltiplo de 5cm
    b_viga_cm = max(25, round(h_viga_cm * 0.4 / 5) * 5)  # base ≈ 0.40h, mín 25cm

    # Cantidad estimada de vigas por piso
    modulos = math.ceil(math.sqrt(A) / L)        # grilla aproximada
    vigas_por_piso = modulos * 2                 # 2 direcciones
    vol_viga_piso = vigas_por_piso * L * (h_viga_cm / 100) * (b_viga_cm / 100)
    vol_vigas_total = vol_viga_piso * n

    # Acero vigas (ρ = 0.0033 min, usar 3× mín para diseño preliminar)
    rho_vigas = 0.0033 * 3
    acero_vigas_kg = rho_vigas * vol_vigas_total * 1000 * 7.85  # 7.85 kg/dm³ acero

    # ── 2. Losa aligerada ──────────────────────────────────────────────────
    h_losa_cm = max(17, round(L * 100 / 30 / 5) * 5)  # L/30, mín 17cm
    vol_losa_total = A * (h_losa_cm / 100) * n * 0.45  # losa aligerada ≈ 45% concreto
    acero_losas_kg = 0.0018 * A * n * (h_losa_cm / 100) * 1000 * 7.85

    # ── 3. Columnas ─────────────────────────────────────────────────────────
    # Carga axial en columna de la primera planta (más cargada)
    carga_total_kg = (CARGA_VIVA_KGF_M2 + CARGA_MUERTA_KGF_M2) * A * n
    num_columnas = vigas_por_piso + 4  # aproximado por grilla
    P_col_kg = carga_total_kg / num_columnas

    # Área columna por resistencia al aplastamiento
    # P = 0.45 × f'c × Ag  →  Ag = P / (0.45 × f'c)
    Ag_cm2 = P_col_kg / (0.45 * FC_KGF_CM2)
    lado_col_cm = math.ceil(math.sqrt(Ag_cm2) / 5) * 5  # cuadrada, múltiplo 5cm
    lado_col_cm = max(25, lado_col_cm)  # mínimo 25cm

    vol_columnas = (lado_col_cm / 100) ** 2 * CARGA_MUERTA_KGF_M2/1000 * n * num_columnas * 3.0
    acero_columnas_kg = 0.01 * (lado_col_cm / 100) ** 2 * n * 3.0 * num_columnas * 1000 * 7.85

    # ── 4. Totales ──────────────────────────────────────────────────────────
    concreto_total = vol_vigas_total + vol_losa_total + vol_columnas
    acero_total_kg = acero_vigas_kg + acero_losas_kg + acero_columnas_kg

    return ResultadoEstructural(
        peralte_viga_cm=h_viga_cm,
        base_viga_cm=b_viga_cm,
        vigas=ElementoEstructural(
            nombre="Viga principal",
            dimension_cm=f"{b_viga_cm}×{h_viga_cm} cm",
            cantidad_estimada=vigas_por_piso * n,
            volumen_concreto_m3=round(vol_vigas_total, 2),
            acero_kg=round(acero_vigas_kg, 1),
        ),
        espesor_losa_cm=h_losa_cm,
        losas=ElementoEstructural(
            nombre="Losa aligerada",
            dimension_cm=f"h={h_losa_cm} cm",
            cantidad_estimada=n,
            volumen_concreto_m3=round(vol_losa_total, 2),
            acero_kg=round(acero_losas_kg, 1),
        ),
        lado_columna_cm=lado_col_cm,
        columnas=ElementoEstructural(
            nombre="Columna cuadrada",
            dimension_cm=f"{lado_col_cm}×{lado_col_cm} cm",
            cantidad_estimada=num_columnas * n,
            volumen_concreto_m3=round(vol_columnas, 2),
            acero_kg=round(acero_columnas_kg, 1),
        ),
        concreto_total_m3=round(concreto_total, 2),
        acero_total_kg=round(acero_total_kg, 1),
        acero_total_ton=round(acero_total_kg / 1000, 2),
        concreto_fc210_m3=round(concreto_total, 2),
        acero_fy4200_kg=round(acero_total_kg, 1),
    )
