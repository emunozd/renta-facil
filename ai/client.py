"""
ai/client.py
Cliente HTTP para kingsrow_ai_base.py + PromptBuilder.

El cliente hace la llamada HTTP y retorna la respuesta.
El builder construye los prompts con contexto del PDF (RAG) y datos del usuario.

Division clara de trabajo:
  Codigo (handler.py) → calcula con precision
  la IA local (via este cliente) → explica, guia y conversa
"""
import logging
from typing import Optional

import httpx

from interfaces.base import (
    IAIClient, IPromptBuilder,
    RespuestaIA, ChunkRAG, ResumenExogena, AnalisisObligacion,
)
from config.constants import ANNO_GRAVABLE, UVT

logger = logging.getLogger(__name__)


class LLMClient(IAIClient):

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self._url     = f"{base_url.rstrip('/')}/v1/chat/completions"
        self._model   = model
        self._timeout = timeout_seconds
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-API-Key"] = api_key

    def completar(
        self,
        mensajes: list[dict],
        system_prompt: str,
        max_tokens: int = 4096,
    ) -> RespuestaIA:
        payload = {
            "model":      self._model,
            "messages":   [{"role": "system", "content": system_prompt}, *mensajes],
            "max_tokens": max_tokens,
            "stream":     False,
        }
        try:
            r = httpx.post(
                self._url,
                headers=self._headers,
                json=payload,
                timeout=self._timeout,
            )
            r.raise_for_status()
            data  = r.json()
            texto = data["choices"][0]["message"]["content"]
            tok   = data.get("usage", {}).get("total_tokens", 0)
            return RespuestaIA(texto=texto.strip(), tokens_usados=tok)

        except httpx.ConnectError:
            msg = (
                f"No se pudo conectar con la IA en {self._url}. "
                "Verifica que kingsrow_ai_base.py este corriendo."
            )
            logger.error(msg)
            return RespuestaIA(texto="", error=msg)

        except httpx.HTTPStatusError as e:
            msg = f"Error HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.error(msg)
            return RespuestaIA(texto="", error=msg)

        except Exception as e:
            logger.exception("Error inesperado llamando al LLM")
            return RespuestaIA(texto="", error=str(e))


class PromptBuilder210(IPromptBuilder):
    """
    Construye los prompts para el LLM.

    El LLM no calcula — explica. Los calculos ya vienen hechos del handler.
    El PDF via RAG es la fuente de verdad para las explicaciones.
    """

    _ROL = (
        f"Eres un experto tributario colombiano especializado en el "
        f"Formulario 210 de la DIAN para personas naturales residentes.\n\n"
        f"Ano gravable: {ANNO_GRAVABLE} (declaracion presentada en {ANNO_GRAVABLE + 1})\n"
        f"UVT vigente : ${UVT:,}\n\n"
        "DIVISION DE RESPONSABILIDADES:\n"
        "- Los calculos numericos ya fueron realizados por el sistema con "
        "precision legal. Tu tarea es EXPLICARLOS al usuario en lenguaje claro.\n"
        "- Usa el instructivo del Formulario 210 (que se te proporciona) "
        "para fundamentar tus explicaciones y citar los articulos del ET.\n"
        "- Si el usuario hace preguntas, responde con base en el instructivo.\n"
        "- Cuando menciones un tope, siempre incluye el valor en UVT y en pesos.\n"
        "- Usa lenguaje cercano y claro. Evita jerga legal sin explicacion.\n"
        "- Siempre indica el SIGUIENTE PASO concreto al final de tu respuesta.\n"
        "- NUNCA inventes cifras. Si no tienes el dato, dilo."
    )

    def construir_system_prompt(
        self,
        chunks_210: list[ChunkRAG],
        resumen_exogena: Optional[ResumenExogena] = None,
        contexto_extra: str = "",
    ) -> str:
        partes = [self._ROL]

        if chunks_210:
            partes.append("\n\n=== INSTRUCTIVO FORMULARIO 210 (FUENTE OFICIAL) ===")
            for chunk in chunks_210:
                partes.append(
                    f"\n[Seccion: {chunk.seccion} | Casillas: {chunk.casillas}]\n"
                    f"{chunk.texto}"
                )
            partes.append("\n=== FIN INSTRUCTIVO ===")

        if resumen_exogena:
            partes.append(self._formatear_exogena(resumen_exogena))

        if contexto_extra:
            partes.append(f"\n\n=== CONTEXTO ===\n{contexto_extra}")

        prompt   = "\n".join(partes)
        palabras = prompt.split()
        if len(palabras) > 9_000:
            logger.warning(f"System prompt largo ({len(palabras)} palabras), truncando.")
            prompt = " ".join(palabras[:9_000])

        return prompt

    def construir_prompt_analisis(self, resumen: ResumenExogena) -> str:
        """Alias mantenido por compatibilidad — usar construir_prompt_explicacion_obligacion."""
        return self.construir_prompt_explicacion_obligacion(None, resumen)

    def construir_prompt_explicacion_obligacion(
        self,
        analisis: Optional[AnalisisObligacion],
        resumen: ResumenExogena,
    ) -> str:
        """
        Le pide al LLM que EXPLIQUE (no que calcule) el resultado
        de la evaluacion de obligacion que ya hizo el handler.
        """
        if analisis and analisis.debe_declarar:
            razones = "\n".join(f"  - {r}" for r in analisis.razones_obliga)
            return (
                f"El sistema determino que el contribuyente DEBE declarar renta "
                f"para el ano gravable {ANNO_GRAVABLE}.\n\n"
                f"Razones:\n{razones}\n\n"
                "Explica esto al usuario en lenguaje sencillo, confirma sus datos "
                "personales detectados en la exogena y pide que los verifique."
            )
        elif analisis and not analisis.debe_declarar:
            razones = "\n".join(f"  - {r}" for r in analisis.razones_no_obliga)
            voluntaria = (
                f"\n\nSin embargo, tiene retenciones de "
                f"${analisis.retenciones_recuperables:,.0f} que podria recuperar "
                "declarando voluntariamente. Pregunta si desea continuar."
                if analisis.puede_beneficiarse_voluntaria else ""
            )
            return (
                f"El sistema determino que el contribuyente NO esta obligado a "
                f"declarar renta para el ano gravable {ANNO_GRAVABLE}.\n\n"
                f"Razones:\n{razones}{voluntaria}\n\n"
                "Explica esto al usuario de forma clara y amable."
            )
        else:
            # Sin analisis previo — el LLM orienta con el contexto disponible
            total = getattr(resumen, "total_ingresos_brutos", 0)
            return (
                f"Analiza la exogena del contribuyente y orientalo sobre "
                f"si debe declarar renta para el ano gravable {ANNO_GRAVABLE}.\n"
                f"Total ingresos detectados: ${total:,.0f}\n"
                f"UVT {ANNO_GRAVABLE}: ${UVT:,}\n"
                "Usa el instructivo del Formulario 210 para fundamentar tu respuesta."
            )

    def construir_prompt_campo(
        self,
        casillas: list[int],
        datos_disponibles: dict,
        sesion,
    ) -> str:
        import json
        return (
            f"Explica las casillas {', '.join(str(c) for c in casillas)} "
            f"del Formulario 210 con los siguientes datos calculados:\n\n"
            f"{json.dumps(datos_disponibles, ensure_ascii=False, indent=2)}\n\n"
            "Muestra el calculo, cita el articulo del ET y menciona los topes "
            "en UVT y en pesos."
        )

    def _formatear_exogena(self, r: ResumenExogena) -> str:
        lineas = ["\n\n=== DATOS EXOGENA DEL CONTRIBUYENTE ==="]
        if r.nit_usuario:
            lineas.append(f"NIT/Cedula : {r.nit_usuario}")
        if r.nombre_usuario:
            lineas.append(f"Nombre     : {r.nombre_usuario}")

        lineas.append("\nINGRESOS DETECTADOS:")
        campos = [
            ("ingresos_laborales",             "Rentas Trabajo laborales   "),
            ("ingresos_no_laborales_trabajo",   "Rentas Trabajo no lab.     "),
            ("ingresos_capital",                "Rentas de Capital          "),
            ("ingresos_no_laborales",           "Rentas No Laborales        "),
            ("ingresos_pensiones",              "Pensiones                  "),
            ("dividendos",                      "Dividendos                 "),
            ("ganancias_ocasionales",           "Ganancias ocasionales      "),
        ]
        for attr, label in campos:
            v = getattr(r, attr, 0)
            if v:
                lineas.append(f"  {label}: ${v:>18,.0f}")

        lineas.append("\nRETENCIONES:")
        ret_campos = [
            ("retenciones_trabajo",      "Laboral     "),
            ("retenciones_capital",      "Capital     "),
            ("retenciones_no_laborales", "No laborales"),
            ("retenciones_pensiones",    "Pensiones   "),
        ]
        for attr, label in ret_campos:
            v = getattr(r, attr, 0)
            if v:
                lineas.append(f"  {label}: ${v:>18,.0f}")

        if r.gmf_pagado:
            lineas.append(
                f"\nGMF pagado (50% deducible): ${r.gmf_pagado:,.0f} "
                f"→ deduccion: ${r.gmf_pagado * 0.5:,.0f}"
            )

        if r.pagadores:
            lineas.append(f"\nPAGADORES/ENTIDADES ({len(r.pagadores)}):")
            for p in r.pagadores[:15]:
                lineas.append(
                    f"  {p['nombre']:<35} | ${p['valor']:>14,.0f} "
                    f"| ret: ${p['retencion']:>10,.0f} | {p['tipo']}"
                )
            if len(r.pagadores) > 15:
                lineas.append(f"  ... y {len(r.pagadores) - 15} mas.")

        lineas.append("=== FIN DATOS EXOGENA ===")
        return "\n".join(lineas)
