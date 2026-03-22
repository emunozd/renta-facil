"""
parsers/zip_parser.py
Analiza el ZIP con certificados del usuario.

Procesamiento LAZY: en lugar de procesar todos los archivos de golpe,
expone metodos para procesar uno a la vez. Asi el bot puede dar feedback
al usuario entre cada documento y distribuir el tiempo de espera
en la conversacion — evitando timeouts con ZIPs grandes.

Estrategia de extraccion por archivo:
  1. Vision  — PDF -> imagen -> LLM extrae valores visualmente
  2. Texto   — fallback con pdfplumber si vision falla
"""
import io
import logging
import os
import zipfile
from typing import Optional

import pdfplumber

from parsers.vision_parser import VisionParser

logger = logging.getLogger(__name__)

# Deteccion por nombre de archivo (rapida, sin leer contenido)
# El prefijo del nombre es el tipo_detectado — por eso le pedimos al usuario
# que nombre los archivos con el prefijo correcto
_PREFIJOS_TIPO = {
    "certificado_ingresos":            "certificado_ingresos_220",
    "certificado_rendimientos":        "certificado_rendimientos",
    "certificado_pension":             "certificado_pension",
    "certificado_afc":                 "certificado_afc_fpv",
    "certificado_medicina":            "certificado_medicina_prepagada",
    "certificado_hipoteca":            "certificado_credito_hipotecario",
    "certificado_icetex":              "certificado_icetex",
    "certificado_dividendos":          "certificado_dividendos",
    "certificado_pensiones_voluntarias": "certificado_pensiones_voluntarias",
    "certificado_exterior_banco":      "certificado_exterior_banco",
    "certificado_exterior_broker":     "certificado_exterior_broker",
}

# Palabras clave en el contenido para deteccion de fallback
_DETECTORES_CONTENIDO = {
    "certificado_ingresos_220": [
        "certificado de ingresos", "retencion en la fuente",
        "ingresos y retenciones", "formato 220", "articulo 378",
    ],
    "certificado_rendimientos": [
        "rendimientos financieros", "extracto", "cdt",
        "intereses", "rendimiento financiero", "cuenta de ahorros",
    ],
    "certificado_pension": [
        "pension", "colpensiones", "fondo de pensiones",
        "mesada pensional", "pension de vejez",
    ],
    "certificado_afc_fpv": [
        "cuenta afc", "ahorro para el fomento",
        "fpv", "avc", "aportes voluntarios",
        "fondo de pensiones voluntarias",
    ],
    "certificado_pensiones_voluntarias": [
        "pensiones voluntarias", "retiro", "permanencia",
        "fondo voluntario", "aporte voluntario pension",
    ],
    "certificado_medicina_prepagada": [
        "medicina prepagada", "seguro de salud",
        "plan complementario", "seguro medico",
    ],
    "certificado_credito_hipotecario": [
        "credito hipotecario", "intereses de vivienda",
        "prestamo hipotecario", "uvr", "leasing habitacional",
    ],
    "certificado_icetex": [
        "icetex", "credito educativo", "prestamo educativo",
    ],
    "certificado_dividendos": [
        "dividendos", "participacion", "utilidades repartidas",
    ],
}

_ENTIDADES_CONOCIDAS = [
    "DAVIVIENDA", "BANCOLOMBIA", "BANCO DE BOGOTA", "BBVA",
    "BANCO POPULAR", "BANCO DE OCCIDENTE", "AV VILLAS", "COLPATRIA",
    "ITAU", "SCOTIABANK", "CITIBANK", "COOMEVA", "CONFIAR",
    "COLPENSIONES", "PORVENIR", "PROTECCION", "COLFONDOS",
    "OLD MUTUAL", "SKANDIA", "FNA", "ICETEX",
]

_CASILLAS_POR_TIPO = {
    "certificado_ingresos_220":          [32, 33, 80],
    "certificado_rendimientos":          [58, 59, 81],
    "certificado_pension":               [91, 92, 83],
    "certificado_afc_fpv":               [35, 47, 63],
    "certificado_pensiones_voluntarias": [35, 47],
    "certificado_medicina_prepagada":    [39, 51, 67],
    "certificado_credito_hipotecario":   [38, 50, 66],
    "certificado_icetex":                [39, 51, 67],
    "certificado_dividendos":            [100, 101, 102],
    "certificado_exterior_banco":        [29, 58],   # patrimonio + rentas capital
    "certificado_exterior_broker":       [29, 109, 122],  # patrimonio + dividendos ext + descuento
}


class ZipParser:
    """
    Abre el ZIP y permite procesar los archivos uno a la vez.
    El bot llama a procesar_siguiente() en cada turno conversacional,
    distribuyendo el tiempo de procesamiento en la conversacion.
    """

    def __init__(self, vision_parser: Optional[VisionParser] = None) -> None:
        self._vision = vision_parser

    # ------------------------------------------------------------------
    # API principal — para el handler
    # ------------------------------------------------------------------

    def listar_archivos(self, ruta_zip: str) -> list[dict]:
        """
        Abre el ZIP y retorna el indice de archivos sin procesarlos.
        Rapido — solo lee los nombres del ZIP.
        """
        if not zipfile.is_zipfile(ruta_zip):
            raise ValueError("El archivo no es un ZIP valido.")

        archivos = []
        with zipfile.ZipFile(ruta_zip, "r") as zf:
            for nombre in zf.namelist():
                if nombre.endswith("/"):
                    continue
                archivos.append({
                    "nombre":          nombre,
                    "tipo_detectado":  self._tipo_por_nombre(nombre),
                    "entidad":         self._entidad_por_nombre(nombre),
                    "procesado":       False,
                    "datos_extraidos": {},
                    "casillas_210":    [],
                    "metodo":          None,
                    "advertencias":    [],
                })
        return archivos

    def procesar_archivo(self, ruta_zip: str, nombre_archivo: str) -> dict:
        """
        Procesa UN archivo especifico del ZIP.
        Llamado por el handler uno a la vez, despues de que el usuario
        confirma el documento anterior.
        """
        with zipfile.ZipFile(ruta_zip, "r") as zf:
            try:
                contenido = zf.read(nombre_archivo)
            except KeyError:
                return {
                    "nombre":          nombre_archivo,
                    "tipo_detectado":  "desconocido",
                    "entidad":         "desconocida",
                    "casillas_210":    [],
                    "datos_extraidos": {},
                    "metodo":          "fallido",
                    "advertencias":    [f"Archivo no encontrado en el ZIP: {nombre_archivo}"],
                }

        return self._analizar(nombre_archivo, contenido)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _analizar(self, nombre: str, contenido: bytes) -> dict:
        ext          = os.path.splitext(nombre)[1].lower()
        advertencias = []

        # Detectar tipo por nombre primero (rapido, el usuario nombro bien)
        tipo = self._tipo_por_nombre(nombre)

        # Si no se detecto, intentar por texto
        texto = ""
        if tipo == "desconocido" and ext == ".pdf":
            texto = self._extraer_texto(contenido)
            if texto:
                tipo = self._tipo_por_contenido(texto.lower())

        entidad  = self._entidad_por_nombre(nombre)
        if entidad == "desconocida" and texto:
            entidad = self._entidad_por_texto(texto.lower())

        # Extraer valores
        datos_extraidos = {}
        metodo          = "fallido"

        if ext in (".pdf", ".jpg", ".jpeg", ".png"):
            # Intentar vision primero
            if self._vision:
                res = self._con_vision(contenido, ext, tipo)
                if res and "error" not in res:
                    datos_extraidos = res
                    metodo          = "vision"
                else:
                    advertencias.append(
                        f"Vision fallo ({res.get('error', '?')}), "
                        "usando extraccion por texto."
                    )

            # Fallback texto
            if metodo == "fallido" and texto:
                datos_texto = self._extraer_valores_texto(texto, tipo)
                if datos_texto:
                    datos_extraidos = datos_texto
                    metodo          = "texto"

            if metodo == "fallido":
                advertencias.append(
                    "No se pudieron extraer valores automaticamente. "
                    "El LLM usara el contexto disponible."
                )

        elif ext in (".xlsx", ".xls"):
            datos_extraidos = self._extraer_excel(contenido)
            metodo          = "texto"

        return {
            "nombre":          nombre,
            "tipo_detectado":  tipo,
            "entidad":         entidad,
            "casillas_210":    _CASILLAS_POR_TIPO.get(tipo, []),
            "datos_extraidos": datos_extraidos,
            "metodo":          metodo,
            "advertencias":    advertencias,
        }

    def _con_vision(self, contenido: bytes, ext: str, tipo: str) -> dict:
        try:
            return self._vision.extraer_desde_bytes(contenido, tipo, ext)
        except Exception as e:
            logger.warning(f"Vision error: {e}")
            return {"error": str(e)}

    def _extraer_texto(self, contenido: bytes) -> str:
        try:
            with pdfplumber.open(io.BytesIO(contenido)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return ""

    def _extraer_excel(self, contenido: bytes) -> dict:
        import pandas as pd
        try:
            df   = pd.read_excel(io.BytesIO(contenido), dtype=str)
            datos = {}
            for col in df.columns:
                if any(k in str(col).lower() for k in ["valor", "monto", "total"]):
                    try:
                        serie = pd.to_numeric(
                            df[col].str.replace(r"[^\d\-\.]", "", regex=True),
                            errors="coerce",
                        ).dropna()
                        if not serie.empty:
                            datos[str(col)] = float(serie.sum())
                    except Exception:
                        pass
            return datos
        except Exception:
            return {}

    def _extraer_valores_texto(self, texto: str, tipo: str) -> dict:
        import re
        patron = r"\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)"
        montos = re.findall(patron, texto)
        valores = []
        for m in montos:
            try:
                v = float(m.replace(".", "").replace(",", "."))
                if v > 100:
                    valores.append(v)
            except ValueError:
                pass
        if not valores:
            return {}
        valores = sorted(set(valores), reverse=True)
        campos  = {
            "certificado_ingresos_220":
                ["ingresos_brutos_laborales", "retencion_practicada", "aportes_pension"],
            "certificado_rendimientos":
                ["rendimientos_financieros", "retencion_practicada", "gmf_pagado"],
            "certificado_pension":
                ["valor_pension_anual", "retencion_practicada"],
            "certificado_afc_fpv":
                ["total_aportes"],
            "certificado_pensiones_voluntarias":
                ["total_aportes", "valor_retiros"],
            "certificado_medicina_prepagada":
                ["valor_pagado_anual"],
            "certificado_credito_hipotecario":
                ["intereses_pagados_anual"],
            "certificado_icetex":
                ["intereses_pagados_anual"],
            "certificado_dividendos":
                ["total_dividendos", "dividendos_gravados"],
        }.get(tipo, ["valor_total"])

        return {
            campo: valores[i]
            for i, campo in enumerate(campos)
            if i < len(valores)
        }

    # ------------------------------------------------------------------
    # Deteccion de tipo y entidad
    # ------------------------------------------------------------------

    def _tipo_por_nombre(self, nombre: str) -> str:
        """
        Detecta el tipo por el prefijo del nombre del archivo.
        Si el usuario nombro bien (certificado_hipoteca_X.pdf),
        la deteccion es instantanea y precisa.
        """
        nombre_lower = nombre.lower()
        for prefijo, tipo in _PREFIJOS_TIPO.items():
            if nombre_lower.startswith(prefijo) or f"/{prefijo}" in nombre_lower:
                return tipo
        return "desconocido"

    def _tipo_por_contenido(self, texto: str) -> str:
        mejor, mejor_score = "desconocido", 0
        for tipo, palabras in _DETECTORES_CONTENIDO.items():
            score = sum(1 for kw in palabras if kw in texto)
            if score > mejor_score:
                mejor_score = score
                mejor       = tipo
        return mejor if mejor_score >= 1 else "desconocido"

    def _entidad_por_nombre(self, nombre: str) -> str:
        nombre_upper = nombre.upper()
        for entidad in _ENTIDADES_CONOCIDAS:
            if entidad in nombre_upper:
                return entidad
        return "desconocida"

    def _entidad_por_texto(self, texto: str) -> str:
        for entidad in _ENTIDADES_CONOCIDAS:
            if entidad.lower() in texto:
                return entidad
        return "desconocida"