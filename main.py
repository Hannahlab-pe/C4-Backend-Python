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
from pydantic import BaseModel, Field
from typing import Optional
import traceback

from motor_cabida import calcular_cabida, DatosTerreno, Normativa
from motor_estructural import predimensionar, EntradaEstructural
from motor_financiero import calcular_financiero, EntradaFinanciera

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


class CabidaRequest(BaseModel):
    terreno: TerrenoInput
    normativa: NormativaInput


class EstructuralRequest(BaseModel):
    area_piso: float = Field(..., gt=0, description="m² de planta libre por piso")
    num_pisos: int = Field(..., gt=0)
    luz_tipica: float = Field(5.0, gt=0, description="Luz libre entre columnas en metros")


class FinancieroRequest(BaseModel):
    distrito: str
    area_vendible_m2: float = Field(..., gt=0)
    area_construida_m2: float = Field(..., gt=0)
    num_departamentos: int = Field(..., gt=0)
    meses_construccion: int = Field(0, ge=0)
    precio_terreno_usd: float = Field(0, ge=0)
    costo_construccion_usd_m2: float = Field(0, ge=0)
    precio_venta_usd_m2: float = Field(0, ge=0)


class AnalisisCompletoRequest(BaseModel):
    terreno: TerrenoInput
    normativa: NormativaInput
    luz_tipica: float = Field(5.0, description="Luz libre entre columnas (m)")
    precio_terreno_usd: float = Field(0, ge=0)
    precio_venta_usd_m2: float = Field(0, ge=0)


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
        resultado = calcular_cabida(terreno, normativa)
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
        entrada = EntradaFinanciera(
            distrito=req.distrito,
            area_vendible_m2=req.area_vendible_m2,
            area_construida_m2=req.area_construida_m2,
            num_departamentos=req.num_departamentos,
            meses_construccion=req.meses_construccion,
            precio_terreno_usd=req.precio_terreno_usd,
            costo_construccion_usd_m2=req.costo_construccion_usd_m2,
            precio_venta_usd_m2=req.precio_venta_usd_m2,
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
        cabida = calcular_cabida(terreno, normativa)

        # 2. Estructural (usa datos de cabida)
        estructura = predimensionar(EntradaEstructural(
            area_piso=cabida.planta_libre,
            num_pisos=cabida.pisos_vivienda,
            luz_tipica=req.luz_tipica,
        ))

        # 3. Financiero (usa datos de cabida)
        financiero = calcular_financiero(EntradaFinanciera(
            distrito=req.normativa.distrito,
            area_vendible_m2=cabida.area_vendible_total,
            area_construida_m2=cabida.area_construida_bruta,
            num_departamentos=cabida.num_departamentos,
            precio_terreno_usd=req.precio_terreno_usd,
            precio_venta_usd_m2=req.precio_venta_usd_m2,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
