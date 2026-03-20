"""
parsers/vision_parser.py
Extrae valores de certificados tributarios usando vision del LLM.

Flujo:
  PDF/imagen del certificado
      ↓
  pdftoppm convierte cada pagina a JPEG
      ↓
  Imagen en base64 → POST /v1/messages (endpoint Anthropic con soporte vision)
      ↓
  LLM lee visualmente y retorna JSON con los valores exactos
      ↓
  Dict listo para _calcular_borrador() en handler.py

El usuario nunca digita un numero — el LLM lo extrae del documento.
"""
import base64
import io
import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Prompts especificos por tipo de documento
# Cuanto mas especifico el prompt, mas fiable la extraccion
_PROMPTS_POR_TIPO = {
    "certificado_ingresos_220": """
Eres un extractor de datos tributarios. Analiza este certificado de ingresos
y retenciones (Formato 220) y extrae UNICAMENTE estos valores numericos.
Responde SOLO con JSON valido, sin texto adicional, sin markdown.

{
  "ingresos_brutos_laborales": <numero o null>,
  "aportes_salud": <numero o null>,
  "aportes_pension": <numero o null>,
  "otros_no_constitutivos": <numero o null>,
  "retencion_practicada": <numero o null>,
  "nombre_empleador": "<string o null>",
  "nit_empleador": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_rendimientos": """
Eres un extractor de datos tributarios. Analiza este certificado de
rendimientos financieros de una entidad bancaria o financiera y extrae
UNICAMENTE estos valores. Responde SOLO con JSON valido, sin texto adicional.

{
  "rendimientos_financieros": <numero o null>,
  "componente_inflacionario": <numero o null>,
  "gmf_pagado": <numero o null>,
  "retencion_practicada": <numero o null>,
  "saldo_31_diciembre": <numero o null>,
  "nombre_entidad": "<string o null>",
  "nit_entidad": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_pension": """
Eres un extractor de datos tributarios. Analiza este certificado de pension
y extrae UNICAMENTE estos valores. Responde SOLO con JSON valido, sin texto adicional.

{
  "valor_pension_anual": <numero o null>,
  "valor_pension_mensual": <numero o null>,
  "retencion_practicada": <numero o null>,
  "nombre_fondo": "<string o null>",
  "nit_fondo": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_afc_fpv": """
Eres un extractor de datos tributarios. Analiza este certificado de aportes
voluntarios AFC, FPV o AVC y extrae UNICAMENTE estos valores.
Responde SOLO con JSON valido, sin texto adicional.

{
  "aportes_afc": <numero o null>,
  "aportes_fpv": <numero o null>,
  "aportes_avc": <numero o null>,
  "total_aportes": <numero o null>,
  "nombre_entidad": "<string o null>",
  "nit_entidad": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_medicina_prepagada": """
Eres un extractor de datos tributarios. Analiza este certificado de medicina
prepagada o seguro de salud y extrae UNICAMENTE estos valores.
Responde SOLO con JSON valido, sin texto adicional.

{
  "valor_pagado_anual": <numero o null>,
  "valor_pagado_mensual": <numero o null>,
  "nombre_entidad": "<string o null>",
  "nit_entidad": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_credito_hipotecario": """
Eres un extractor de datos tributarios. Analiza este certificado de intereses
de credito hipotecario o prestamo de vivienda y extrae UNICAMENTE estos valores.
Responde SOLO con JSON valido, sin texto adicional.

{
  "intereses_pagados_anual": <numero o null>,
  "correccion_monetaria": <numero o null>,
  "saldo_capital": <numero o null>,
  "nombre_entidad": "<string o null>",
  "nit_entidad": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_icetex": """
Eres un extractor de datos tributarios. Analiza este certificado de intereses
de prestamo educativo del ICETEX y extrae UNICAMENTE estos valores.
Responde SOLO con JSON valido, sin texto adicional.

{
  "intereses_pagados_anual": <numero o null>,
  "saldo_capital": <numero o null>,
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "certificado_dividendos": """
Eres un extractor de datos tributarios. Analiza este certificado de dividendos
o participaciones y extrae UNICAMENTE estos valores.
Responde SOLO con JSON valido, sin texto adicional.

{
  "dividendos_gravados": <numero o null>,
  "dividendos_no_gravados": <numero o null>,
  "total_dividendos": <numero o null>,
  "retencion_practicada": <numero o null>,
  "nombre_sociedad": "<string o null>",
  "nit_sociedad": "<string o null>",
  "anno_gravable": <numero o null>
}

Si un valor no aparece en el documento, usa null.
Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",

    "desconocido": """
Eres un extractor de datos tributarios. Analiza este documento y extrae
todos los valores monetarios relevantes para una declaracion de renta.
Responde SOLO con JSON valido, sin texto adicional.

{
  "tipo_documento": "<descripcion breve>",
  "entidad_emisora": "<nombre o null>",
  "valores_detectados": {
    "<nombre_campo>": <numero>
  },
  "anno_gravable": <numero o null>
}

Los valores numericos deben ser en pesos colombianos sin puntos ni comas.
""",
}


class VisionParser:
    """
    Extrae valores de certificados tributarios usando vision del LLM.

    Usa el endpoint /v1/messages de kingsrow_ai_base.py que soporta imagenes
    en formato Anthropic. El endpoint /v1/chat/completions NO soporta imagenes.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_seconds: int = 120,
        max_reintentos: int = 2,
    ) -> None:
        # Vision usa /v1/messages, no /v1/chat/completions
        self._url      = f"{base_url.rstrip('/')}/v1/messages"
        self._headers  = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-API-Key"] = api_key
        self._timeout       = timeout_seconds
        self._max_reintentos = max_reintentos

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def extraer(self, ruta_archivo: str, tipo_documento: str) -> dict:
        """
        Recibe la ruta de un PDF o imagen y el tipo de documento detectado.
        Retorna un dict con los valores extraidos.
        Si falla, retorna dict vacio con clave 'error'.
        """
        imagenes = self._archivo_a_imagenes(ruta_archivo)
        if not imagenes:
            return {"error": "No se pudo convertir el archivo a imagen"}

        prompt = _PROMPTS_POR_TIPO.get(tipo_documento, _PROMPTS_POR_TIPO["desconocido"])

        # Intentar con la primera pagina — los datos relevantes suelen estar ahi
        # Si falla, intentar con la segunda pagina
        for i, imagen_b64 in enumerate(imagenes[:2]):
            resultado = self._llamar_llm(prompt, imagen_b64)
            if resultado and "error" not in resultado:
                logger.info(
                    f"Vision exitosa: {tipo_documento} pagina {i+1}, "
                    f"campos={list(resultado.keys())}"
                )
                return resultado

        return {"error": f"No se pudieron extraer datos de {ruta_archivo}"}

    def extraer_desde_bytes(self, contenido: bytes, tipo_documento: str, ext: str) -> dict:
        """
        Recibe el contenido binario del archivo directamente (desde el ZIP).
        """
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(contenido)
            ruta = tmp.name
        try:
            return self.extraer(ruta, tipo_documento)
        finally:
            try:
                os.unlink(ruta)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Conversion de archivo a imagenes
    # ------------------------------------------------------------------
    def _archivo_a_imagenes(self, ruta: str) -> list[str]:
        """
        Convierte un archivo a lista de imagenes en base64.
        Soporta: PDF, JPG, PNG, JPEG.
        Retorna lista de strings base64 (una por pagina/imagen).
        """
        ext = os.path.splitext(ruta)[1].lower()

        if ext == ".pdf":
            return self._pdf_a_imagenes(ruta)
        elif ext in (".jpg", ".jpeg", ".png"):
            return self._imagen_a_base64(ruta)
        else:
            logger.warning(f"Formato no soportado para vision: {ext}")
            return []

    def _pdf_a_imagenes(self, ruta_pdf: str) -> list[str]:
        """
        Convierte PDF a imagenes usando pdftoppm (ya disponible en el Dockerfile).
        Retorna lista de base64, una por pagina (max 3 paginas).
        """
        imagenes = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            prefijo = os.path.join(tmp_dir, "pag")
            try:
                subprocess.run(
                    [
                        "pdftoppm",
                        "-jpeg",
                        "-r", "150",    # 150 DPI — suficiente para leer texto
                        "-l", "3",      # max 3 paginas
                        ruta_pdf,
                        prefijo,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"pdftoppm falló: {e.stderr.decode()[:200]}")
                return []
            except FileNotFoundError:
                logger.error(
                    "pdftoppm no encontrado. "
                    "Verifica que poppler-utils este instalado en el contenedor."
                )
                return []

            # Buscar las imagenes generadas (pdftoppm zero-padea el nombre)
            archivos = sorted([
                f for f in os.listdir(tmp_dir)
                if f.startswith("pag") and f.endswith(".jpg")
            ])

            for nombre in archivos:
                ruta_img = os.path.join(tmp_dir, nombre)
                b64 = self._imagen_a_base64(ruta_img)
                if b64:
                    imagenes.extend(b64)

        return imagenes

    def _imagen_a_base64(self, ruta_img: str) -> list[str]:
        """Lee una imagen y la convierte a base64."""
        try:
            with open(ruta_img, "rb") as f:
                return [base64.b64encode(f.read()).decode("utf-8")]
        except Exception as e:
            logger.warning(f"Error leyendo imagen {ruta_img}: {e}")
            return []

    # ------------------------------------------------------------------
    # Llamada al LLM con vision
    # ------------------------------------------------------------------
    def _llamar_llm(self, prompt: str, imagen_b64: str) -> dict:
        """
        Llama al endpoint /v1/messages de kingsrow_ai_base.py con una imagen.
        El formato es Anthropic-compatible con bloque de imagen en base64.
        Reintenta hasta max_reintentos veces si el JSON es invalido.
        """
        payload = {
            "model":      "local",
            "max_tokens": 600,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type":       "base64",
                                "media_type": "image/jpeg",
                                "data":       imagen_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }

        for intento in range(self._max_reintentos + 1):
            try:
                r = httpx.post(
                    self._url,
                    headers=self._headers,
                    json=payload,
                    timeout=self._timeout,
                )
                r.raise_for_status()
                data = r.json()

                # Extraer texto de la respuesta Anthropic-compatible
                texto = ""
                for bloque in data.get("content", []):
                    if bloque.get("type") == "text":
                        texto += bloque.get("text", "")

                texto = texto.strip()
                resultado = self._parsear_json(texto)

                if resultado is not None:
                    return resultado

                logger.warning(
                    f"Intento {intento+1}: JSON invalido en respuesta del LLM: "
                    f"{texto[:150]}"
                )

            except httpx.ConnectError:
                logger.error(
                    f"No se pudo conectar con la IA para vision en {self._url}"
                )
                return {"error": "IA no disponible"}

            except httpx.HTTPStatusError as e:
                logger.error(f"Error HTTP {e.response.status_code} en vision")
                return {"error": f"HTTP {e.response.status_code}"}

            except Exception as e:
                logger.exception(f"Error inesperado en vision (intento {intento+1})")

        return {"error": "No se obtuvo JSON valido del LLM despues de reintentos"}

    def _parsear_json(self, texto: str) -> Optional[dict]:
        """
        Intenta parsear JSON de la respuesta del LLM.
        Limpia markdown fences si los hay.
        """
        # Limpiar fences de markdown si el LLM los incluye
        texto = re.sub(r"```json|```", "", texto).strip()

        try:
            datos = json.loads(texto)
            if isinstance(datos, dict):
                return datos
        except json.JSONDecodeError:
            pass

        # Intentar extraer el primer objeto JSON del texto
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        if match:
            try:
                datos = json.loads(match.group())
                if isinstance(datos, dict):
                    return datos
            except json.JSONDecodeError:
                pass

        return None
