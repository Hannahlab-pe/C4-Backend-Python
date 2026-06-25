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
        resultado = calcular_cabida(terreno, normativa, mezcla_tipologias=mezcla)
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
        )
        resultado = calcular_financiero(entrada)
        return _financiero_to_dict(resultado)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en motor financiero: {str(e)}")


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
        cabida = calcular_cabida(terreno, normativa, mezcla_tipologias=mezcla_cabida)

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

        msp = doc.modelspace()
        textos, bloques, tipos = [], Counter(), Counter()
        for e in msp:
            t = e.dxftype()
            tipos[t] += 1
            try:
                if t == "TEXT":
                    s = (e.dxf.text or "").strip()
                    if s:
                        textos.append(s)
                elif t == "MTEXT":
                    s = e.plain_text().strip()
                    if s:
                        textos.append(s)
                elif t == "INSERT":
                    bloques[e.dxf.name] += 1
            except Exception:
                pass

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
        for s in textos:
            k = s.lower()
            if k not in vistos:
                vistos.add(k); textos_u.append(s)

        return {
            "ok": True,
            "capas": capas[:60],
            "textos": textos_u[:200],
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


# NOTA: arrancar SIEMPRE con uvicorn desde la terminal:
#     python -m uvicorn main:app --port 8000 --reload
# No usar `python main.py`: con reload=True deja un proceso huérfano
# escuchando en 0.0.0.0:8000 que intercepta las peticiones con código viejo.
