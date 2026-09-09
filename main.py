"""
C4 — API de Motores Python
Expone los motores determinísticos como REST API para ser llamados por NestJS.

Endpoints:
  POST /cabida           → Motor de Cabida Arquitectónica
  POST /estructural      → Motor de Predimensionamiento Estructural
  POST /financiero       → Motor Financiero (TIR, VAN, flujo de caja)
  POST /analisis-completo → Los 3 en cadena (el flujo principal del MVP)
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional, List
import traceback

from motor_cabida import calcular_cabida, DatosTerreno, Normativa
from motor_estructural import predimensionar, EntradaEstructural
from motor_financiero import calcular_financiero, EntradaFinanciera, TipologiaDepto
from motor_plano import generar_plano_dxf, EntradaPlano

app = FastAPI(
    title="C4 — Motores de Análisis",
    description="Motores determinísticos de cabida, estructura y finanzas para C4",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Schemas de entrada (Pydantic) ─────────────────────────────────────────

class TerrenoInput(BaseModel):
    area_total: float = Field(..., description="Área total del terreno en m²", gt=0)
    frente: Optional[float] = Field(None, description="Frente del terreno en metros")
    fondo: Optional[float] = Field(None, description="Fondo del terreno en metros")


class NormativaInput(BaseModel):
    distrito: str
    pisos_max: int = Field(..., gt=0)
    retiro_frontal: float = Field(0.0, ge=0)
    retiro_lateral: float = Field(0.0, ge=0)
    retiro_posterior: float = Field(0.0, ge=0)
    cus: float = Field(..., gt=0)
    area_min_depto: float = Field(..., gt=0)
    estacionamientos: float = Field(1.0, ge=0)


class TipologiaInput(BaseModel):
    tipo: str
    porcentaje: float = Field(..., ge=0, le=100)
    precio_usd_m2: float = Field(default=0, ge=0)  # 0 = usar promedio del distrito — v2


class CabidaRequest(BaseModel):
    terreno: TerrenoInput
    normativa: NormativaInput
    mezcla_tipologias: Optional[List[TipologiaInput]] = None
    # Supuestos que un experto confirmó y C4 aprobó (ver calibracion.py).
    # Lo que no venga aquí usa la constante por defecto del motor.
    calibracion: Optional[dict] = None


class EstructuralRequest(BaseModel):
    area_piso: float = Field(..., gt=0, description="m² de planta libre por piso")
    num_pisos: int = Field(..., gt=0)
    luz_tipica: float = Field(5.0, gt=0, description="Luz libre entre columnas en metros")


class FinancieroRequest(BaseModel):
    distrito: str
    area_vendible_m2: float = Field(..., gt=0)
    area_construida_m2: float = Field(..., gt=0)
    num_departamentos: int = Field(..., gt=0)
    num_pisos: int = Field(8, ge=1, description="Pisos de vivienda — ajusta el costo por altura")
    precio_terreno_usd: float = Field(0, ge=0)
    precio_venta_usd_m2: float = Field(0, ge=0)
    area_demolicion_m2: float = Field(0, ge=0)
    porcentaje_capital_propio: float = Field(40.0, ge=0, le=100)
    velocidad_ventas_mensual: float = Field(0, ge=0)
    mezcla_tipologias: Optional[List[TipologiaInput]] = None
    factor_tiempo_obra: float = Field(1.0, gt=0, le=1.5, description="Multiplica meses de obra (prefab < 1 = más rápido)")
    delta_costo_construccion_pct: float = Field(0.0, ge=-50, le=50, description="% de ajuste al costo de construcción/m²")
    # Supuestos que un experto confirmó y C4 aprobó (ver calibracion.py).
    # Lo que no venga aquí usa la constante por defecto del motor.
    calibracion: Optional[dict] = None
    costo_construccion_usd_m2: float = Field(0, ge=0, description="Override del costo de construcción/m² (0 = auto)")
    area_sotano_m2: float = Field(0, ge=0, description="Área de sótanos a costear con premium")
    num_estacionamientos: int = Field(0, ge=0, description="Cajones que se venden (de la cabida)")
    num_depositos: int = Field(0, ge=0, description="Depósitos que se venden (0 = no se consideran)")


class PrecioMaxTerrenoRequest(FinancieroRequest):
    tir_objetivo: float = Field(20.0, gt=0, le=100, description="TIR anual objetivo (%) para despejar el precio máximo del terreno")


class PlanoRequest(BaseModel):
    # Terreno
    frente: float
    fondo: float
    area_terreno: float
    # Normativa
    retiro_frontal: float = 0.0
    retiro_lateral: float = 0.0
    retiro_posterior: float = 0.0
    distrito: str = ""
    fuente_normativa: str = ""
    # Cabida (resultados del motor)
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
    mezcla_tipologias: Optional[List[TipologiaInput]] = None
    nombre_proyecto: str = "Proyecto C4"
    direccion: str = ""
    # Grúa torre
    grua_modelo: str = ""
    grua_radio_m: float = 0.0
    grua_base_m: float = 0.0
    # Calles circundantes
    calle_frontal: str = ""
    calle_lateral_izq: str = ""
    calle_lateral_der: str = ""
    calle_posterior: str = ""


class AnalisisCompletoRequest(BaseModel):
    terreno: TerrenoInput
    normativa: NormativaInput
    luz_tipica: float = Field(5.0, description="Luz libre entre columnas (m)")
    precio_terreno_usd: float = Field(0, ge=0)
    precio_venta_usd_m2: float = Field(0, ge=0)
    area_demolicion_m2: float = Field(0, ge=0)
    porcentaje_capital_propio: float = Field(40.0, ge=0, le=100)
    velocidad_ventas_mensual: float = Field(0, ge=0)
    mezcla_tipologias: Optional[List[TipologiaInput]] = None
    # Supuestos que un experto confirmó y C4 aprobó (ver calibracion.py).
    calibracion: Optional[dict] = None


# ─── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "c4-motores-python"}


@app.post("/cabida")
def endpoint_cabida(req: CabidaRequest):
    try:
        terreno = DatosTerreno(
            area_total=req.terreno.area_total,
            frente=req.terreno.frente,
            fondo=req.terreno.fondo,
        )
        normativa = Normativa(
            distrito=req.normativa.distrito,
            pisos_max=req.normativa.pisos_max,
            retiro_frontal=req.normativa.retiro_frontal,
            retiro_lateral=req.normativa.retiro_lateral,
            retiro_posterior=req.normativa.retiro_posterior,
            cus=req.normativa.cus,
            area_min_depto=req.normativa.area_min_depto,
            estacionamientos=req.normativa.estacionamientos,
        )
        mezcla = [{'tipo': t.tipo, 'porcentaje': t.porcentaje} for t in req.mezcla_tipologias] if req.mezcla_tipologias else None
        resultado = calcular_cabida(terreno, normativa, mezcla_tipologias=mezcla,
                                    calibracion=req.calibracion)
        return _cabida_to_dict(resultado)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en motor cabida: {traceback.format_exc()}")


@app.post("/estructural")
def endpoint_estructural(req: EstructuralRequest):
    try:
        entrada = EntradaEstructural(
            area_piso=req.area_piso,
            num_pisos=req.num_pisos,
            luz_tipica=req.luz_tipica,
        )
        resultado = predimensionar(entrada)
        return _estructural_to_dict(resultado)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en motor estructural: {str(e)}")


@app.post("/financiero")
def endpoint_financiero(req: FinancieroRequest):
    try:
        mezcla = [TipologiaDepto(tipo=t.tipo, porcentaje=t.porcentaje, precio_usd_m2=t.precio_usd_m2)
                  for t in req.mezcla_tipologias] if req.mezcla_tipologias else None
        entrada = EntradaFinanciera(
            distrito=req.distrito,
            area_vendible_m2=req.area_vendible_m2,
            area_construida_m2=req.area_construida_m2,
            num_departamentos=req.num_departamentos,
            num_pisos=req.num_pisos,
            precio_terreno_usd=req.precio_terreno_usd,
            precio_venta_usd_m2=req.precio_venta_usd_m2,
            area_demolicion_m2=req.area_demolicion_m2,
            porcentaje_capital_propio=req.porcentaje_capital_propio,
            velocidad_ventas_mensual=req.velocidad_ventas_mensual,
            mezcla_tipologias=mezcla,
            factor_tiempo_obra=req.factor_tiempo_obra,
            delta_costo_construccion_pct=req.delta_costo_construccion_pct,
            costo_construccion_usd_m2=req.costo_construccion_usd_m2,
            area_sotano_m2=req.area_sotano_m2,
            num_estacionamientos=req.num_estacionamientos,
            num_depositos=req.num_depositos,
            calibracion=req.calibracion,
        )
        resultado = calcular_financiero(entrada)
        return _financiero_to_dict(resultado)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en motor financiero: {str(e)}")


@app.post("/precio-maximo-terreno")
def endpoint_precio_maximo_terreno(req: PrecioMaxTerrenoRequest):
    """Despeja el precio MÁXIMO del terreno que aún alcanza una TIR objetivo (valor residual)."""
    from dataclasses import replace
    try:
        mezcla = [TipologiaDepto(tipo=t.tipo, porcentaje=t.porcentaje, precio_usd_m2=t.precio_usd_m2)
                  for t in req.mezcla_tipologias] if req.mezcla_tipologias else None
        base = EntradaFinanciera(
            distrito=req.distrito,
            area_vendible_m2=req.area_vendible_m2,
            area_construida_m2=req.area_construida_m2,
            num_departamentos=req.num_departamentos,
            num_pisos=req.num_pisos,
            precio_terreno_usd=0,
            precio_venta_usd_m2=req.precio_venta_usd_m2,
            area_demolicion_m2=req.area_demolicion_m2,
            porcentaje_capital_propio=req.porcentaje_capital_propio,
            velocidad_ventas_mensual=req.velocidad_ventas_mensual,
            mezcla_tipologias=mezcla,
            calibracion=req.calibracion,
            costo_construccion_usd_m2=req.costo_construccion_usd_m2,
            area_sotano_m2=req.area_sotano_m2,
            num_estacionamientos=req.num_estacionamientos,
            num_depositos=req.num_depositos,
        )
        objetivo = req.tir_objetivo

        def tir_de(precio: float) -> float:
            return calcular_financiero(replace(base, precio_terreno_usd=precio)).tir_anual_pct

        # Con terreno casi gratis, TIR es la máxima posible. Si ni así llega al objetivo → no alcanzable.
        r0 = calcular_financiero(replace(base, precio_terreno_usd=1.0))
        if r0.tir_anual_pct < objetivo:
            return {"precio_maximo_usd": 0, "alcanzable": False, "tir_objetivo": objetivo,
                    "tir_max_posible": round(r0.tir_anual_pct, 1), "financiero": _financiero_to_dict(r0)}

        # Bisección: la TIR baja monótonamente al subir el precio del terreno.
        lo, hi = 0.0, max(r0.ingreso_total_usd, 1.0)
        for _ in range(40):
            mid = (lo + hi) / 2
            if tir_de(mid) >= objetivo:
                lo = mid
            else:
                hi = mid
        r = calcular_financiero(replace(base, precio_terreno_usd=lo))
        return {"precio_maximo_usd": round(lo, 0), "alcanzable": True, "tir_objetivo": objetivo,
                "financiero": _financiero_to_dict(r)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en precio máximo: {str(e)}")


@app.post("/analisis-completo")
def endpoint_analisis_completo(req: AnalisisCompletoRequest):
    """
    Flujo completo: Terreno + Normativa → Cabida → Estructura → Financiero
    Este es el endpoint que llama el LLM como tool calling principal.
    """
    try:
        # 1. Cabida
        terreno = DatosTerreno(area_total=req.terreno.area_total, frente=req.terreno.frente, fondo=req.terreno.fondo)
        normativa = Normativa(
            distrito=req.normativa.distrito,
            pisos_max=req.normativa.pisos_max,
            retiro_frontal=req.normativa.retiro_frontal,
            retiro_lateral=req.normativa.retiro_lateral,
            retiro_posterior=req.normativa.retiro_posterior,
            cus=req.normativa.cus,
            area_min_depto=req.normativa.area_min_depto,
            estacionamientos=req.normativa.estacionamientos,
        )
        mezcla_cabida = [{'tipo': t.tipo, 'porcentaje': t.porcentaje} for t in req.mezcla_tipologias] if req.mezcla_tipologias else None
        cabida = calcular_cabida(terreno, normativa, mezcla_tipologias=mezcla_cabida,
                                 calibracion=req.calibracion)

        # 2. Estructural (usa datos de cabida)
        estructura = predimensionar(EntradaEstructural(
            area_piso=cabida.planta_libre,
            num_pisos=cabida.pisos_vivienda,
            luz_tipica=req.luz_tipica,
        ))

        # 3. Financiero (usa datos de cabida)
        mezcla = [TipologiaDepto(tipo=t.tipo, porcentaje=t.porcentaje, precio_usd_m2=t.precio_usd_m2)
                  for t in req.mezcla_tipologias] if req.mezcla_tipologias else None
        financiero = calcular_financiero(EntradaFinanciera(
            distrito=req.normativa.distrito,
            area_vendible_m2=cabida.area_vendible_total,
            area_construida_m2=cabida.area_construida_bruta,
            num_departamentos=cabida.num_departamentos,
            num_pisos=cabida.pisos_vivienda,
            precio_terreno_usd=req.precio_terreno_usd,
            precio_venta_usd_m2=req.precio_venta_usd_m2,
            area_demolicion_m2=req.area_demolicion_m2,
            porcentaje_capital_propio=req.porcentaje_capital_propio,
            velocidad_ventas_mensual=req.velocidad_ventas_mensual,
            mezcla_tipologias=mezcla,
            # Las cocheras que exige la normativa se venden (antes se costeaba el sótano y no se vendían).
            num_estacionamientos=cabida.estacionamientos_requeridos,
            calibracion=req.calibracion,
        ))

        return {
            "cabida": _cabida_to_dict(cabida),
            "estructura": _estructural_to_dict(estructura),
            "financiero": _financiero_to_dict(financiero),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=traceback.format_exc())


# ─── Serialización ─────────────────────────────────────────────────────────
from dataclasses import asdict

def _cabida_to_dict(r) -> dict:
    d = asdict(r)
    return d

def _estructural_to_dict(r) -> dict:
    return asdict(r)

def _financiero_to_dict(r) -> dict:
    d = asdict(r)
    return d


@app.post("/plano")
def endpoint_plano(req: PlanoRequest):
    """Genera un plano DXF de ubicación y cuadro de áreas."""
    try:
        mezcla_plano = (
            [{"tipo": t.tipo, "porcentaje": t.porcentaje} for t in req.mezcla_tipologias]
            if req.mezcla_tipologias else []
        )
        entrada = EntradaPlano(
            frente=req.frente,
            fondo=req.fondo,
            area_terreno=req.area_terreno,
            retiro_frontal=req.retiro_frontal,
            retiro_lateral=req.retiro_lateral,
            retiro_posterior=req.retiro_posterior,
            distrito=req.distrito,
            fuente_normativa=req.fuente_normativa,
            planta_libre=req.planta_libre,
            pisos_vivienda=req.pisos_vivienda,
            sotanos=req.sotanos,
            area_construida_bruta=req.area_construida_bruta,
            area_vendible_total=req.area_vendible_total,
            num_departamentos=req.num_departamentos,
            estacionamientos_requeridos=req.estacionamientos_requeridos,
            cus_utilizado=req.cus_utilizado,
            limitante=req.limitante,
            area_min_depto=req.area_min_depto,
            mezcla_tipologias=mezcla_plano,
            nombre_proyecto=req.nombre_proyecto,
            direccion=req.direccion,
            grua_modelo=req.grua_modelo,
            grua_radio_m=req.grua_radio_m,
            grua_base_m=req.grua_base_m,
            calle_frontal=req.calle_frontal,
            calle_lateral_izq=req.calle_lateral_izq,
            calle_lateral_der=req.calle_lateral_der,
            calle_posterior=req.calle_posterior,
        )
        dxf_bytes = generar_plano_dxf(entrada)
        nombre_archivo = f"plano_c4_{req.distrito.lower().replace(' ', '_')}.dxf"
        return Response(
            content=dxf_bytes,
            media_type="application/dxf",
            headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Error generando plano: {traceback.format_exc()}")


class LeerPlanoRequest(BaseModel):
    dxf_base64: str


@app.post("/leer-plano")
def endpoint_leer_plano(req: LeerPlanoRequest):
    """Lee un DXF y extrae capas, textos/leyendas, bloques y dimensiones para que la IA lo interprete."""
    import base64 as _b64, tempfile, os as _os, ezdxf
    from collections import Counter
    tmp = None
    try:
        raw = _b64.b64decode(req.dxf_base64)
        fd, tmp = tempfile.mkstemp(suffix=".dxf")
        with _os.fdopen(fd, "wb") as f:
            f.write(raw)
        try:
            doc = ezdxf.readfile(tmp)
        except Exception:
            # DXF con errores: recuperar
            from ezdxf import recover
            doc, _ = recover.readfile(tmp)

        import re
        msp = doc.modelspace()
        textos, bloques, tipos = [], Counter(), Counter()  # textos = (str, altura)
        for e in msp:
            t = e.dxftype()
            tipos[t] += 1
            try:
                if t == "TEXT":
                    s = (e.dxf.text or "").strip()
                    if s:
                        textos.append((s, float(getattr(e.dxf, "height", 0) or 0)))
                elif t == "MTEXT":
                    s = e.plain_text().strip()
                    if s:
                        textos.append((s, float(getattr(e.dxf, "char_height", 0) or 0)))
                elif t == "INSERT":
                    bloques[e.dxf.name] += 1
            except Exception:
                pass

        # Niveles (sótanos/pisos/cisterna/azotea) — escanea TODOS los textos, no solo los primeros
        nivel_re = re.compile(r"(s[oó]tano|semis[oó]tano|piso|azotea|cisterna|nivel|mezz|techo|planta)", re.I)
        niveles, vist_n = [], set()
        for s, _h in textos:
            if len(s) <= 45 and nivel_re.search(s):
                k = s.lower()
                if k not in vist_n:
                    vist_n.add(k); niveles.append(s)

        # Títulos = los textos más grandes (suelen ser los rótulos de cada lámina/nivel)
        alturas = [h for _s, h in textos if h > 0]
        titulos = []
        if alturas:
            thr = max(alturas) * 0.6
            vist_t = set()
            for s, h in textos:
                if h >= thr and len(s) <= 60:
                    k = s.lower()
                    if k not in vist_t:
                        vist_t.add(k); titulos.append(s)

        capas = [l.dxf.name for l in doc.layers if l.dxf.name not in ("Defpoints",)]

        ext = None
        try:
            emin, emax = doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX")
            if emin and emax:
                w, h = abs(emax[0] - emin[0]), abs(emax[1] - emin[1])
                # ezdxf usa +/-1e20 como default cuando no hay extents reales
                if 0 < w < 1e9 and 0 < h < 1e9:
                    ext = {"ancho_u": round(w, 2), "alto_u": round(h, 2)}
        except Exception:
            pass

        # Dedup de textos preservando orden, limitar
        vistos, textos_u = set(), []
        for s, _h in textos:
            k = s.lower()
            if k not in vistos:
                vistos.add(k); textos_u.append(s)

        return {
            "ok": True,
            "capas": capas[:60],
            "niveles": niveles[:40],
            "titulos": titulos[:40],
            "textos": textos_u[:250],
            "total_textos": len(textos),
            "bloques": dict(bloques.most_common(40)),
            "conteo_entidades": dict(tipos.most_common(20)),
            "total_entidades": sum(tipos.values()),
            "extents": ext,
            "dxf_version": doc.dxfversion,
        }
    except Exception:
        raise HTTPException(status_code=500, detail=f"Error leyendo DXF: {traceback.format_exc()}")
    finally:
        if tmp and _os.path.exists(tmp):
            try: _os.remove(tmp)
            except Exception: pass


class UbicarGruaRequest(BaseModel):
    dxf_base64: str
    modelo: str = "Grúa torre"
    radio_m: float = 50
    base_m: float = 3.2
    frente_m: float = 12
    fondo_m: float = 25
    esquina: str = "posterior_izq"  # posterior_izq | posterior_der | frontal_izq | frontal_der


@app.post("/ubicar-grua")
def endpoint_ubicar_grua(req: UbicarGruaRequest):
    """Dibuja la grúa (base + radio de pluma + rótulo) sobre el DXF recibido y lo devuelve modificado."""
    import base64 as _b64, tempfile, os as _os, ezdxf
    from ezdxf import bbox
    tin = tout = None
    try:
        raw = _b64.b64decode(req.dxf_base64)
        fd, tin = tempfile.mkstemp(suffix=".dxf")
        with _os.fdopen(fd, "wb") as f:
            f.write(raw)
        try:
            doc = ezdxf.readfile(tin)
        except Exception:
            from ezdxf import recover
            doc, _ = recover.readfile(tin)
        msp = doc.modelspace()

        # Bounding box total del dibujo
        ext = bbox.extents(msp)
        if not ext.has_data:
            raise HTTPException(status_code=400, detail="No pude calcular las dimensiones del plano.")
        Sx0, Sy0, Sx1, Sy1 = ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y
        sheet_area = max((Sx1 - Sx0) * (Sy1 - Sy0), 1e-9)

        # Detectar contorno (footprint): polilínea cerrada de mayor área pero < 60% de la lámina (evita el marco)
        polys = []
        for e in msp.query("LWPOLYLINE"):
            try:
                if not e.closed:
                    continue
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) < 4:
                    continue
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                w, h = max(xs) - min(xs), max(ys) - min(ys)
                if w <= 0 or h <= 0:
                    continue
                polys.append((w * h, min(xs), min(ys), max(xs), max(ys), w, h))
            except Exception:
                pass
        cand = sorted([p for p in polys if p[0] < 0.6 * sheet_area], key=lambda p: -p[0])
        if cand:
            _, fx0, fy0, fx1, fy1, fw, fh = cand[0]
        else:
            fx0, fy0, fx1, fy1, fw, fh = Sx0, Sy0, Sx1, Sy1, Sx1 - Sx0, Sy1 - Sy0

        # Escala (unidades de dibujo por metro) a partir del lado mayor real
        real_major = max(req.frente_m, req.fondo_m, 0.1)
        fp_major = max(fw, fh, 1e-6)
        scale = fp_major / real_major
        radio_u = req.radio_m * scale
        base_u = max(req.base_m * scale, fp_major * 0.04)

        # Esquina elegida del footprint
        corners = {
            "posterior_izq": (fx0, fy1), "posterior_der": (fx1, fy1),
            "frontal_izq": (fx0, fy0), "frontal_der": (fx1, fy0),
        }
        cx, cy = corners.get(req.esquina, (fx0, fy1))
        inset = fp_major * 0.07
        cx += inset if "izq" in req.esquina else -inset
        cy += -inset if "posterior" in req.esquina else inset

        # Capa de la grúa (roja)
        if "C4-GRUA" not in doc.layers:
            doc.layers.add("C4-GRUA", color=1)
        atr = {"layer": "C4-GRUA"}
        b = base_u / 2
        msp.add_circle((cx, cy), radio_u, dxfattribs=atr)                       # radio de pluma
        msp.add_lwpolyline([(cx - b, cy - b), (cx + b, cy - b), (cx + b, cy + b), (cx - b, cy + b), (cx - b, cy - b)], dxfattribs=atr)  # base
        msp.add_line((cx - b, cy), (cx + b, cy), dxfattribs=atr)                # cruz del mástil
        msp.add_line((cx, cy - b), (cx, cy + b), dxfattribs=atr)
        th = max(fp_major * 0.03, base_u * 0.4)
        msp.add_text(f"GRUA TORRE - {req.modelo}", height=th, dxfattribs=atr).set_placement((cx + base_u, cy + base_u))
        msp.add_text(f"R={req.radio_m} m  Base={req.base_m} m", height=th * 0.8, dxfattribs=atr).set_placement((cx + base_u, cy + base_u - th * 1.5))

        fd2, tout = tempfile.mkstemp(suffix=".dxf")
        _os.close(fd2)
        doc.saveas(tout)
        with open(tout, "rb") as f:
            out_b64 = _b64.b64encode(f.read()).decode()

        return {
            "ok": True,
            "dxf_base64": out_b64,
            "posicion": {"x": round(cx, 2), "y": round(cy, 2), "esquina": req.esquina},
            "medidas": {
                "frente_m": req.frente_m, "fondo_m": req.fondo_m,
                "escala_u_por_m": round(scale, 4),
                "contorno_detectado_u": {"ancho": round(fw, 2), "alto": round(fh, 2)},
                "lamina_u": {"ancho": round(Sx1 - Sx0, 2), "alto": round(Sy1 - Sy0, 2)},
                "radio_pluma_u": round(radio_u, 2),
            },
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail=f"Error ubicando grúa: {traceback.format_exc()}")
    finally:
        for t in (tin, tout):
            if t and _os.path.exists(t):
                try: _os.remove(t)
                except Exception: pass


class MetradoDxfRequest(BaseModel):
    dxf_base64: str


@app.post("/metrado-dxf")
def endpoint_metrado_dxf(req: MetradoDxfRequest):
    """Lee un DXF y MIDE áreas por capa (polilíneas cerradas + hatch) para armar un metrado.
    Detecta la escala (unidades) de forma robusta con las cotas y sugiere una partida por capa."""
    import base64 as _b64, tempfile, os as _os, ezdxf, re
    from ezdxf import path as ezpath
    from collections import defaultdict
    tmp = None

    def shoelace(pts):
        if len(pts) < 3:
            return 0.0
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % len(pts)]
            a += x1 * y2 - x2 * y1
        return abs(a) / 2.0

    def sugerir(capa: str):
        c = capa.lower()
        if "prelosa" in c or ("losa" in c and "aligerad" in c): return "Losa aligerada (prelosa)"
        if "losa" in c or "techo" in c or "suelo" in c: return "Losa"
        if "doppel" in c or "muro" in c: return "Muro"
        if "columna" in c or "pilar" in c: return "Columna"
        if "casco" in c: return "Casco estructural"
        if "cimentac" in c or "zapata" in c or "solado" in c: return "Cimentación"
        if "viga" in c: return "Viga"
        return None

    try:
        raw = _b64.b64decode(req.dxf_base64)
        fd, tmp = tempfile.mkstemp(suffix=".dxf")
        with _os.fdopen(fd, "wb") as f:
            f.write(raw)
        try:
            doc = ezdxf.readfile(tmp)
        except Exception:
            from ezdxf import recover
            doc, _ = recover.readfile(tmp)
        msp = doc.modelspace()

        # ── Escala: unidades del dibujo → metros (las cotas mandan sobre el flag INSUNITS) ──
        insunits = int(doc.header.get("$INSUNITS", 0) or 0)
        dims = []
        for d in msp.query("DIMENSION"):
            try:
                m = d.get_measurement()
                if isinstance(m, (int, float)) and m > 0:
                    dims.append(float(m))
            except Exception:
                pass
        factor = None; unidad = None; confianza = "baja"
        if dims:
            dims.sort()
            ref = dims[min(int(len(dims) * 0.9), len(dims) - 1)]  # dimensión grande (percentil 90)
            if ref > 100: factor, unidad = 0.001, "mm"
            elif ref > 30: factor, unidad = 0.01, "cm"
            else: factor, unidad = 1.0, "m"
            confianza = "alta"
        if factor is None:
            factor = {4: 0.001, 5: 0.01, 6: 1.0}.get(insunits, 1.0)
            unidad = {4: "mm", 5: "cm", 6: "m"}.get(insunits, "m (asumido)")
        factor_area = factor * factor

        # ── Áreas por capa (polilíneas cerradas + hatch), descartando capas de apoyo ──
        SOPORTE = {"Defpoints", "FIERRO", "A-FIERRO", "ESTRIBOS", "ACERO"}
        cerr_area = defaultdict(float); cerr_n = defaultdict(int)
        hatch_area = defaultdict(float); hatch_n = defaultdict(int)
        textos = []
        n_ent = 0
        for e in msp:
            n_ent += 1
            t = e.dxftype(); capa = getattr(e.dxf, "layer", "0")
            if capa in SOPORTE:
                continue
            if t == "LWPOLYLINE" and getattr(e, "closed", False):
                try:
                    a = shoelace([(p[0], p[1]) for p in e.get_points("xy")]) * factor_area
                    if a > 0.05:
                        cerr_area[capa] += a; cerr_n[capa] += 1
                except Exception:
                    pass
            elif t == "HATCH":
                try:
                    tot = 0.0; ok = False
                    for p in ezpath.from_hatch(e):
                        pp = [(v.x, v.y) for v in p.flattening(0.1)]
                        if len(pp) >= 3:
                            tot += shoelace(pp); ok = True
                    a = tot * factor_area
                    if ok and a > 0.05:
                        hatch_area[capa] += a; hatch_n[capa] += 1
                except Exception:
                    pass
            elif t in ("TEXT", "MTEXT"):
                try:
                    s = (e.plain_text() if t == "MTEXT" else (e.dxf.text or "")).strip()
                    if s:
                        textos.append(s)
                except Exception:
                    pass

        # Una capa es "detalle" (ruido de la lámina, no obra) si su nombre lo delata,
        # tiene prefijo _ / -, o el área es muy chica (dibujitos de corte/leyenda).
        DET = re.compile(r"(detalle|detail|leyenda|cuadro|tabla|secci|corte|croquis|\bnota)", re.I)
        def es_detalle(capa: str, area: float) -> bool:
            c = (capa or "").strip()
            if DET.search(c): return True
            if c[:1] in ("_", "-"): return True
            if area < 5: return True
            return False

        capas = []
        for capa in set(list(cerr_area) + list(hatch_area)):
            area = round(cerr_area.get(capa, 0.0) + hatch_area.get(capa, 0.0), 2)
            if area <= 0:
                continue
            capas.append({
                "capa": capa,
                "area_m2": area,
                "n_cerradas": cerr_n.get(capa, 0),
                "n_hatch": hatch_n.get(capa, 0),
                "partida_sugerida": sugerir(capa),
                "es_detalle": es_detalle(capa, area),
            })
        capas.sort(key=lambda x: -x["area_m2"])

        # Textos con material / altura (para trazabilidad "de dónde salió")
        kw = re.compile(r"(muro|doppel|prelosa|losa|column|pilar|zapata|ciment|solado|viga|f.?c\s*=|h\s*=|e\s*=|npt|nfz)", re.I)
        vist, clave = set(), []
        for s in textos:
            if len(s) <= 70 and kw.search(s):
                k = s.lower()
                if k not in vist:
                    vist.add(k); clave.append(s)

        return {
            "ok": True,
            "unidad_detectada": unidad,
            "factor_a_metros": factor,
            "escala_confianza": confianza,
            "capas": capas[:40],
            "textos_clave": clave[:40],
            "total_entidades": n_ent,
        }
    except Exception:
        raise HTTPException(status_code=500, detail=f"Error midiendo DXF: {traceback.format_exc()}")
    finally:
        if tmp and _os.path.exists(tmp):
            try: _os.remove(tmp)
            except Exception: pass


# NOTA: arrancar SIEMPRE con uvicorn desde la terminal:
#     python -m uvicorn main:app --port 8000 --reload
# No usar `python main.py`: con reload=True deja un proceso huérfano
# escuchando en 0.0.0.0:8000 que intercepta las peticiones con código viejo.
