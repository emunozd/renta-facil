"""
bot/handler.py
Coordina el flujo conversacional completo del bot.

Pasos numerados (TOTAL_PASOS = 11):
  1  Exogena
  2  Confirmar datos personales
  3  Dependientes economicos
  4  Credito hipotecario
  5  Medicina prepagada
  6  AFC / FPV
  7  Pensiones voluntarias
  8  ICETEX
  9  Resumen + solicitud ZIP
  10 Revision documento por documento (lazy — uno a la vez)
  11 Borrador + Excel

Division de responsabilidades:
  Codigo → evalua obligacion, calcula, aplica topes legales
  LLM    → explica, interpreta respuestas libres, guia la conversacion
"""
import json
import logging
import os
import re
import tempfile
import time

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

from interfaces.base import (
    IExogenaParser, IZipParser, IRAGService,
    IAIClient, IPromptBuilder, ISessionRepo, IFormGenerator,
    SesionUsuario, AnalisisObligacion, ResumenExogena,
)
from config.constants import (
    EstadoBot, MSG_BIENVENIDA, MSG_ERROR_ARCHIVO,
    ANNO_GRAVABLE, UVT, PASO_ZIP, TOTAL_PASOS,
    SESSION_TIMEOUT_HORAS, MSG_SESSION_EXPIRADA, MSG_CANCELADO,
    # Mensajes por paso
    MSG_P3_DEPENDIENTES, MSG_P3_CUANTOS,
    MSG_P4_HIPOTECA, MSG_P4_SI,
    MSG_P5_MEDICINA, MSG_P5_SI,
    MSG_P6_AFC,      MSG_P6_SI,
    MSG_P7_PENSIONES_VOL, MSG_P7_SI,
    MSG_P8_ICETEX,   MSG_P8_SI,
    msg_resumen_zip,
    # Constantes de calculo
    UMBRAL_INGRESOS_COP, UMBRAL_PATRIMONIO_COP,
    UMBRAL_CONSIGNACIONES_COP, UMBRAL_COMPRAS_COP,
    EXENTA_25_PORCENTAJE, EXENTA_25_COP,
    LIMITE_GLOBAL_PORCENTAJE, LIMITE_GLOBAL_COP,
    AFC_FVP_AVC_PORCENTAJE, AFC_FVP_AVC_TOPE_COP,
    INTERESES_VIVIENDA_COP, MEDICINA_PREPAGADA_COP_ANUAL,
    DEPENDIENTES_MAX_COP_MES, DEPENDIENTES_PORCENTAJE_MES,
    DEPENDIENTES_UVT_POR_PERSONA, DEPENDIENTES_MAX_PERSONAS,
    ICETEX_COP, GMF_PORCENTAJE_DEDUCIBLE,
    PENSION_EXENTA_COP_MES, FPV_PLAZO_MINIMO_AÑOS,
    TABLA_TARIFAS,
)
from config.settings import Settings

logger = logging.getLogger(__name__)

_EMOJI_TIPO = {
    "certificado_ingresos_220":          "📄",
    "certificado_rendimientos":          "🏦",
    "certificado_pension":               "👴",
    "certificado_afc_fpv":               "💰",
    "certificado_pensiones_voluntarias": "📈",
    "certificado_medicina_prepagada":    "🏥",
    "certificado_credito_hipotecario":   "🏠",
    "certificado_icetex":                "🎓",
    "certificado_dividendos":            "📊",
    "desconocido":                       "📎",
}

_NOMBRE_TIPO = {
    "certificado_ingresos_220":          "Certificado de ingresos y retenciones",
    "certificado_rendimientos":          "Certificado de rendimientos financieros",
    "certificado_pension":               "Certificado de pension",
    "certificado_afc_fpv":               "Certificado AFC / FPV / AVC",
    "certificado_pensiones_voluntarias": "Certificado pensiones voluntarias",
    "certificado_medicina_prepagada":    "Certificado medicina prepagada",
    "certificado_credito_hipotecario":   "Certificado intereses credito hipotecario",
    "certificado_icetex":                "Certificado intereses ICETEX",
    "certificado_dividendos":            "Certificado de dividendos",
    "desconocido":                       "Documento",
}

_NOMBRE_CAMPO = {
    "ingresos_brutos_laborales":  "Ingresos laborales brutos",
    "aportes_salud":              "Aportes a salud",
    "aportes_pension":            "Aportes a pension",
    "otros_no_constitutivos":     "Otros no constitutivos",
    "retencion_practicada":       "Retencion practicada",
    "rendimientos_financieros":   "Rendimientos financieros",
    "componente_inflacionario":   "Componente inflacionario",
    "gmf_pagado":                 "GMF pagado (4x1000)",
    "saldo_31_diciembre":         "Saldo al 31 de diciembre",
    "valor_pension_anual":        "Valor pension anual",
    "valor_pension_mensual":      "Valor pension mensual",
    "aportes_afc":                "Aportes AFC",
    "aportes_fpv":                "Aportes FPV",
    "total_aportes":              "Total aportes voluntarios",
    "valor_retiros":              "Valor retiros realizados",
    "anos_permanencia":           "Anos de permanencia en el fondo",
    "valor_pagado_anual":         "Valor pagado en el ano",
    "intereses_pagados_anual":    "Intereses pagados en el ano",
    "dividendos_gravados":        "Dividendos gravados",
    "dividendos_no_gravados":     "Dividendos no gravados",
    "total_dividendos":           "Total dividendos",
    "saldo_capital":              "Saldo capital",
}

# Campos que no se muestran al usuario (metadata)
_CAMPOS_METADATA = {
    "anno_gravable", "nombre_empleador", "nit_empleador",
    "nombre_entidad", "nit_entidad", "nombre_fondo",
    "nombre_sociedad", "tipo_documento",
}


class BotHandler:

    def __init__(
        self,
        settings: Settings,
        exogena_parser: IExogenaParser,
        zip_parser: IZipParser,
        rag_service: IRAGService,
        ai_client: IAIClient,
        prompt_builder: IPromptBuilder,
        session_repo: ISessionRepo,
        form_generator: IFormGenerator,
    ) -> None:
        self._settings       = settings
        self._exogena_parser = exogena_parser
        self._zip_parser     = zip_parser
        self._rag            = rag_service
        self._ai             = ai_client
        self._prompts        = prompt_builder
        self._sessions       = session_repo
        self._generator      = form_generator

    # ------------------------------------------------------------------
    # Aplicacion
    # ------------------------------------------------------------------
    def construir_aplicacion(self) -> Application:
        app = Application.builder().token(self._settings.telegram_token).build()
        app.add_handler(CommandHandler("start",     self._cmd_start))
        app.add_handler(CommandHandler("reiniciar", self._cmd_reiniciar))
        app.add_handler(CommandHandler("estado",    self._cmd_estado))
        app.add_handler(CommandHandler("ayuda",     self._cmd_ayuda))
        app.add_handler(MessageHandler(
            filters.Document.ALL, self._manejar_documento
        ))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._manejar_texto
        ))
        app.add_error_handler(self._manejar_error)
        return app

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------
    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        sesion  = self._sessions.obtener(chat_id)
        if sesion and sesion.estado not in (EstadoBot.INICIO, EstadoBot.FINALIZADO):
            await update.message.reply_text(
                f"Ya tienes una sesion activa en el paso: {sesion.estado}.\n"
                "Usa /reiniciar si deseas empezar de nuevo."
            )
            return
        sesion = SesionUsuario(chat_id=chat_id, estado=EstadoBot.ESPERANDO_EXOGENA)
        self._sessions.guardar(sesion)
        await update.message.reply_text(MSG_BIENVENIDA)

    async def _cmd_reiniciar(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        self._sessions.eliminar(update.effective_chat.id)
        sesion = SesionUsuario(
            chat_id=update.effective_chat.id,
            estado=EstadoBot.ESPERANDO_EXOGENA,
        )
        self._sessions.guardar(sesion)
        await update.message.reply_text(
            "Sesion reiniciada. "
            f"Paso 1 de {TOTAL_PASOS} — Sube tu exogena cuando quieras."
        )

    async def _cmd_estado(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        sesion = self._sessions.obtener(update.effective_chat.id)
        if not sesion:
            await update.message.reply_text("No tienes sesion activa. Usa /start.")
            return
        await update.message.reply_text(
            f"Estado: {sesion.estado} | Paso: {sesion.paso_actual} de {TOTAL_PASOS}"
        )

    async def _cmd_ayuda(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f"Asistente declaracion de renta — Formulario 210\n"
            f"Ano gravable {ANNO_GRAVABLE} | UVT ${UVT:,}\n\n"
            "/start     — Iniciar\n"
            "/reiniciar — Borrar sesion y empezar de nuevo\n"
            "/estado    — Ver en que paso vas\n"
            "/ayuda     — Esta ayuda\n\n"
            f"El proceso tiene {TOTAL_PASOS} pasos."
        )

    # ------------------------------------------------------------------
    # Documentos
    # ------------------------------------------------------------------
    async def _manejar_documento(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ):
        chat_id = update.effective_chat.id
        sesion  = self._sessions.obtener(chat_id)
        if not sesion:
            await update.message.reply_text("Usa /start para iniciar.")
            return

        doc = update.message.document
        # Verificar sesion activa y timeout
        if not await self._verificar_sesion_activa(update, sesion):
            return

        # Actualizar timestamp de actividad
        sesion.ultima_actividad = time.time()
        self._sessions.guardar(sesion)

        mb  = doc.file_size / (1024 * 1024)
        if mb > self._settings.max_file_size_mb:
            await update.message.reply_text(
                f"Archivo muy grande ({mb:.1f} MB). "
                f"Maximo: {self._settings.max_file_size_mb} MB."
            )
            return

        ext     = os.path.splitext(doc.file_name or "")[1].lower()
        archivo = await ctx.bot.get_file(doc.file_id)

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            await archivo.download_to_drive(tmp.name)
            ruta = tmp.name

        try:
            if ext in (".xlsx", ".xls"):
                await self._paso1_exogena(update, sesion, ruta)
            elif ext == ".zip":
                await self._paso9_recibir_zip(update, sesion, ruta)
            else:
                await update.message.reply_text(
                    f"Archivo no soportado: {ext}\n"
                    "Acepto .xlsx/.xls (exogena) o .zip (documentos)."
                )
        finally:
            try:
                os.unlink(ruta)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # PASO 1 — Exogena
    # ------------------------------------------------------------------
    async def _paso1_exogena(
        self, update: Update, sesion: SesionUsuario, ruta: str
    ):
        if sesion.estado not in (EstadoBot.ESPERANDO_EXOGENA, EstadoBot.INICIO):
            await update.message.reply_text(
                "Ya tengo tu exogena. Usa /reiniciar para actualizarla."
            )
            return

        await update.message.reply_text("Recibido! Analizando tu exogena...")

        try:
            resumen = self._exogena_parser.parsear(ruta)
        except ValueError as e:
            await update.message.reply_text(f"{MSG_ERROR_ARCHIVO}\nDetalle: {e}")
            return

        sesion.resumen_exogena     = resumen
        analisis                   = self._evaluar_obligacion(resumen)
        sesion.analisis_obligacion = analisis
        sesion.estado              = EstadoBot.CONFIRMANDO_DATOS
        sesion.paso_actual         = 2
        self._sessions.guardar(sesion)

        chunks    = self._rag.recuperar_contexto(
            "obligacion declarar renta umbrales ingresos patrimonio"
        )
        system    = self._prompts.construir_system_prompt(chunks, resumen)
        prompt    = self._prompts.construir_prompt_explicacion_obligacion(analisis, resumen)
        respuesta = self._ai.completar(
            mensajes=[{"role": "user", "content": prompt}],
            system_prompt=system,
        )

        if respuesta.error:
            await update.message.reply_text(
                "Error conectando con la IA. "
                "Verifica que kingsrow_ai_base.py este activo."
            )
            return

        sesion.historial_mensajes.append(
            {"role": "assistant", "content": respuesta.texto}
        )
        sesion.ultima_pregunta = "confirmacion_datos"
        self._sessions.guardar(sesion)
        await update.message.reply_text(respuesta.texto)

        if not analisis.debe_declarar:
            sesion.estado = EstadoBot.NO_OBLIGADO
            if analisis.puede_beneficiarse_voluntaria:
                sesion.ultima_pregunta = "declaracion_voluntaria"
            self._sessions.guardar(sesion)

    # ------------------------------------------------------------------
    # PASO 2 — Confirmar datos personales
    # ------------------------------------------------------------------
    async def _paso2_confirmar_datos(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        sesion.datos_confirmados["confirmacion_usuario"] = texto
        sesion.estado          = EstadoBot.PREGUNTA_DEPENDIENTES
        sesion.paso_actual     = 3
        sesion.ultima_pregunta = "p3_dependientes"
        self._sessions.guardar(sesion)
        await update.message.reply_text(MSG_P3_DEPENDIENTES)

    # ------------------------------------------------------------------
    # PASO 3 — Dependientes
    # ------------------------------------------------------------------
    async def _paso3_dependientes(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.ultima_pregunta = "p3_cuantos"
            self._sessions.guardar(sesion)
            await update.message.reply_text(MSG_P3_CUANTOS)
        else:
            sesion.datos_confirmados["num_dependientes"] = 0
            await self._paso4_iniciar(update, sesion)

    async def _paso3_cuantos(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        """El LLM interpreta la respuesta libre del usuario sobre dependientes."""
        prompt = (
            f"El usuario describe sus dependientes economicos: '{texto}'\n"
            "Extrae el numero total de dependientes como entero. "
            "Responde SOLO con el numero, sin texto adicional."
        )
        respuesta = self._ai.completar(
            mensajes=[{"role": "user", "content": prompt}],
            system_prompt="Eres un extractor de numeros. Responde solo con el digito.",
        )
        try:
            num = int(re.search(r"\d+", respuesta.texto).group())
            num = min(num, 4)  # maximo 4 dependientes segun ET
        except Exception:
            num = 1

        sesion.datos_confirmados["num_dependientes"] = num
        await update.message.reply_text(
            f"Anotado, {num} dependiente(s). Continuamos..."
        )
        await self._paso4_iniciar(update, sesion)

    # ------------------------------------------------------------------
    # PASO 4 — Credito hipotecario
    # ------------------------------------------------------------------
    async def _paso4_iniciar(self, update: Update, sesion: SesionUsuario):
        sesion.estado          = EstadoBot.PREGUNTA_HIPOTECA
        sesion.paso_actual     = 4
        sesion.ultima_pregunta = "p4_hipoteca"
        self._sessions.guardar(sesion)
        await update.message.reply_text(MSG_P4_HIPOTECA)

    async def _paso4_hipoteca(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.datos_confirmados["tiene_hipoteca"] = True
            docs_opcionales = sesion.datos_confirmados.get("docs_opcionales", [])
            docs_opcionales.append(
                ("🏠", f"certificado_hipoteca_NOMBRE_BANCO.pdf  (Paso 4)")
            )
            sesion.datos_confirmados["docs_opcionales"] = docs_opcionales
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                MSG_P4_SI.format(anno=ANNO_GRAVABLE, paso_zip=PASO_ZIP)
            )
        else:
            sesion.datos_confirmados["tiene_hipoteca"] = False
            self._sessions.guardar(sesion)

        await self._paso5_iniciar(update, sesion)

    # ------------------------------------------------------------------
    # PASO 5 — Medicina prepagada
    # ------------------------------------------------------------------
    async def _paso5_iniciar(self, update: Update, sesion: SesionUsuario):
        sesion.estado          = EstadoBot.PREGUNTA_MEDICINA
        sesion.paso_actual     = 5
        sesion.ultima_pregunta = "p5_medicina"
        self._sessions.guardar(sesion)
        await update.message.reply_text(
            MSG_P5_MEDICINA.format(anno=ANNO_GRAVABLE)
        )

    async def _paso5_medicina(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.datos_confirmados["tiene_medicina_prepagada"] = True
            docs_opcionales = sesion.datos_confirmados.get("docs_opcionales", [])
            docs_opcionales.append(
                ("🏥", f"certificado_medicina_NOMBRE_ENTIDAD.pdf  (Paso 5)")
            )
            sesion.datos_confirmados["docs_opcionales"] = docs_opcionales
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                MSG_P5_SI.format(anno=ANNO_GRAVABLE, paso_zip=PASO_ZIP)
            )
        else:
            sesion.datos_confirmados["tiene_medicina_prepagada"] = False
            self._sessions.guardar(sesion)

        await self._paso6_iniciar(update, sesion)

    # ------------------------------------------------------------------
    # PASO 6 — AFC / FPV
    # ------------------------------------------------------------------
    async def _paso6_iniciar(self, update: Update, sesion: SesionUsuario):
        sesion.estado          = EstadoBot.PREGUNTA_AFC
        sesion.paso_actual     = 6
        sesion.ultima_pregunta = "p6_afc"
        self._sessions.guardar(sesion)
        await update.message.reply_text(
            MSG_P6_AFC.format(anno=ANNO_GRAVABLE)
        )

    async def _paso6_afc(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.datos_confirmados["tiene_afc_fpv"] = True
            docs_opcionales = sesion.datos_confirmados.get("docs_opcionales", [])
            docs_opcionales.append(
                ("💰", f"certificado_afc_NOMBRE_ENTIDAD.pdf  (Paso 6)")
            )
            sesion.datos_confirmados["docs_opcionales"] = docs_opcionales
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                MSG_P6_SI.format(anno=ANNO_GRAVABLE, paso_zip=PASO_ZIP)
            )
        else:
            sesion.datos_confirmados["tiene_afc_fpv"] = False
            self._sessions.guardar(sesion)

        await self._paso7_iniciar(update, sesion)

    # ------------------------------------------------------------------
    # PASO 7 — Pensiones voluntarias
    # ------------------------------------------------------------------
    async def _paso7_iniciar(self, update: Update, sesion: SesionUsuario):
        sesion.estado          = EstadoBot.PREGUNTA_PENSIONES_VOL
        sesion.paso_actual     = 7
        sesion.ultima_pregunta = "p7_pensiones_vol"
        self._sessions.guardar(sesion)
        await update.message.reply_text(
            MSG_P7_PENSIONES_VOL.format(anno=ANNO_GRAVABLE)
        )

    async def _paso7_pensiones_vol(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.datos_confirmados["tiene_pensiones_voluntarias"] = True
            docs_opcionales = sesion.datos_confirmados.get("docs_opcionales", [])
            docs_opcionales.append(
                ("📈", f"certificado_pensiones_voluntarias_NOMBRE_FONDO.pdf  (Paso 7)")
            )
            sesion.datos_confirmados["docs_opcionales"] = docs_opcionales
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                MSG_P7_SI.format(anno=ANNO_GRAVABLE, paso_zip=PASO_ZIP)
            )
        else:
            sesion.datos_confirmados["tiene_pensiones_voluntarias"] = False
            self._sessions.guardar(sesion)

        await self._paso8_iniciar(update, sesion)

    # ------------------------------------------------------------------
    # PASO 8 — ICETEX
    # ------------------------------------------------------------------
    async def _paso8_iniciar(self, update: Update, sesion: SesionUsuario):
        sesion.estado          = EstadoBot.PREGUNTA_ICETEX
        sesion.paso_actual     = 8
        sesion.ultima_pregunta = "p8_icetex"
        self._sessions.guardar(sesion)
        await update.message.reply_text(MSG_P8_ICETEX)

    async def _paso8_icetex(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.datos_confirmados["tiene_icetex"] = True
            docs_opcionales = sesion.datos_confirmados.get("docs_opcionales", [])
            docs_opcionales.append(
                ("🎓", "certificado_icetex.pdf  (Paso 8)")
            )
            sesion.datos_confirmados["docs_opcionales"] = docs_opcionales
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                MSG_P8_SI.format(anno=ANNO_GRAVABLE, paso_zip=PASO_ZIP)
            )
        else:
            sesion.datos_confirmados["tiene_icetex"] = False
            self._sessions.guardar(sesion)

        await self._paso9_resumen(update, sesion)

    # ------------------------------------------------------------------
    # PASO 9 — Resumen + solicitud ZIP
    # ------------------------------------------------------------------
    async def _paso9_resumen(self, update: Update, sesion: SesionUsuario):
        r = sesion.resumen_exogena

        # Obligatorios: empleadores y entidades financieras de la exogena
        pagadores_laborales   = [
            p["nombre"] for p in r.pagadores
            if p["tipo"] == "trabajo_laboral"
        ]
        entidades_financieras = [
            e["nombre"] for e in r.entidades_financieras
        ]

        # Opcionales: los que el usuario confirmo en pasos 4-8
        docs_opcionales = sesion.datos_confirmados.get("docs_opcionales", [])

        mensaje = msg_resumen_zip(
            pagadores_laborales,
            entidades_financieras,
            docs_opcionales,
        )

        sesion.estado          = EstadoBot.ESPERANDO_ZIP
        sesion.paso_actual     = 9
        sesion.ultima_pregunta = ""
        self._sessions.guardar(sesion)

        await update.message.reply_text(mensaje)

    # ------------------------------------------------------------------
    # PASO 9b — Recibir el ZIP
    # ------------------------------------------------------------------
    async def _paso9_recibir_zip(
        self, update: Update, sesion: SesionUsuario, ruta: str
    ):
        if sesion.estado != EstadoBot.ESPERANDO_ZIP:
            await update.message.reply_text(
                "Aun no estamos en la etapa de documentos. "
                "Sigue el flujo desde /start."
            )
            return

        # Guardar ruta del ZIP en sesion para procesamiento lazy
        # (procesamos un archivo a la vez, no todos de golpe)
        try:
            indice = self._zip_parser.listar_archivos(ruta)
        except ValueError as e:
            await update.message.reply_text(f"Error con el ZIP: {e}")
            return

        if not indice:
            await update.message.reply_text(
                "El ZIP no contenia archivos reconocibles. "
                "Verifica el contenido e intentalo de nuevo."
            )
            return

        # Copiar el ZIP a un temporal permanente para acceso lazy
        with tempfile.NamedTemporaryFile(
            suffix=".zip", delete=False,
            dir=tempfile.gettempdir()
        ) as tmp_zip:
            import shutil
            shutil.copy2(ruta, tmp_zip.name)
            ruta_zip_sesion = tmp_zip.name

        sesion.datos_confirmados["ruta_zip"]       = ruta_zip_sesion
        sesion.datos_confirmados["zip_indice"]     = indice
        sesion.datos_confirmados["zip_idx_actual"] = 0
        sesion.datos_confirmados["docs_confirmados"] = []
        sesion.estado      = EstadoBot.REVISANDO_DOCUMENTOS
        sesion.paso_actual = 10
        self._sessions.guardar(sesion)

        total = len(indice)
        await update.message.reply_text(
            f"ZIP recibido con {total} documento(s). "
            "Vamos uno por uno — te muestro lo que encuentro "
            "en cada certificado para que lo confirmes."
        )

        await self._paso10_procesar_siguiente(update, sesion)

    # ------------------------------------------------------------------
    # PASO 10 — Revision documento por documento (LAZY)
    # ------------------------------------------------------------------
    async def _paso10_procesar_siguiente(
        self, update: Update, sesion: SesionUsuario
    ):
        """
        Procesa el siguiente archivo del ZIP y lo presenta al usuario.
        El procesamiento con vision puede tardar — el usuario ya sabe
        porque vio la conversacion paso a paso.
        """
        indice    = sesion.datos_confirmados.get("zip_indice", [])
        idx       = sesion.datos_confirmados.get("zip_idx_actual", 0)
        ruta_zip  = sesion.datos_confirmados.get("ruta_zip", "")

        if idx >= len(indice):
            # Todos procesados → calcular borrador
            await self._paso11_calcular_borrador(update, sesion)
            return

        info_archivo = indice[idx]
        nombre       = info_archivo["nombre"]
        total        = len(indice)

        await update.message.reply_text(
            f"Leyendo documento {idx+1} de {total}: {nombre}..."
        )

        # Procesar con vision (puede tardar 30-60 seg)
        resultado = self._zip_parser.procesar_archivo(ruta_zip, nombre)

        # Guardar resultado en el indice
        indice[idx] = {**info_archivo, **resultado, "procesado": True}
        sesion.datos_confirmados["zip_indice"] = indice
        sesion.estado          = EstadoBot.CONFIRMANDO_DOCUMENTO
        sesion.ultima_pregunta = f"confirmar_doc_{idx}"
        self._sessions.guardar(sesion)

        # Presentar al usuario
        await self._presentar_documento(update, sesion, resultado, idx, total)

    async def _presentar_documento(
        self,
        update: Update,
        sesion: SesionUsuario,
        resultado: dict,
        idx: int,
        total: int,
    ):
        tipo    = resultado.get("tipo_detectado", "desconocido")
        entidad = resultado.get("entidad", "")
        datos   = resultado.get("datos_extraidos", {})
        metodo  = resultado.get("metodo", "fallido")
        warns   = resultado.get("advertencias", [])
        emoji   = _EMOJI_TIPO.get(tipo, "📎")
        nombre  = _NOMBRE_TIPO.get(tipo, "Documento")

        lineas = [
            f"Paso 10 de {TOTAL_PASOS} — Documento {idx+1} de {total}",
            f"{emoji} {nombre}"
            + (f" — {entidad}" if entidad and entidad != "desconocida" else ""),
            "",
        ]

        if datos and "error" not in datos:
            lineas.append("Valores encontrados:")
            for campo, valor in datos.items():
                if campo in _CAMPOS_METADATA or valor is None:
                    continue
                nombre_campo = _NOMBRE_CAMPO.get(
                    campo, campo.replace("_", " ").capitalize()
                )
                if isinstance(valor, (int, float)) and valor > 0:
                    lineas.append(f"  • {nombre_campo}: ${valor:,.0f}")
                elif isinstance(valor, str) and valor:
                    lineas.append(f"  • {nombre_campo}: {valor}")

            if metodo == "vision":
                lineas.append("")
                lineas.append("(Valores leidos automaticamente del documento)")
            elif metodo == "texto":
                lineas.append("")
                lineas.append("(Valores extraidos del texto del documento)")

            casillas = resultado.get("casillas_210", [])
            if casillas:
                lineas.append(
                    f"Casillas del Formulario 210: "
                    f"{', '.join(str(c) for c in casillas)}"
                )
        else:
            lineas.append(
                "No pude extraer los valores automaticamente."
            )
            if warns:
                lineas.append(f"Razon: {warns[0]}")
            lineas.append(
                "Puedes indicarme los valores manualmente o "
                "escribir SALTAR si este documento no aplica."
            )

        lineas.extend([
            "",
            "Los valores son correctos?",
            "  SI — confirmar y continuar",
            "  NO, [campo] es [valor] — corregir un valor",
            "  SALTAR — omitir este documento",
        ])

        await update.message.reply_text("\n".join(lineas))

    async def _paso10_confirmar(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        idx      = sesion.datos_confirmados.get("zip_idx_actual", 0)
        indice   = sesion.datos_confirmados.get("zip_indice", [])
        texto_u  = texto.strip().upper()

        if texto_u in ("SI", "SÍ", "S"):
            # Confirmar documento y pasar al siguiente
            confirmados = sesion.datos_confirmados.get("docs_confirmados", [])
            confirmados.append(indice[idx])
            sesion.datos_confirmados["docs_confirmados"] = confirmados
            sesion.datos_confirmados["zip_idx_actual"]   = idx + 1
            self._sessions.guardar(sesion)
            await self._paso10_procesar_siguiente(update, sesion)

        elif texto_u == "SALTAR":
            sesion.datos_confirmados["zip_idx_actual"] = idx + 1
            self._sessions.guardar(sesion)
            await update.message.reply_text("Documento omitido.")
            await self._paso10_procesar_siguiente(update, sesion)

        else:
            # Correccion del usuario
            await self._corregir_documento(update, sesion, texto, idx, indice[idx])

    async def _corregir_documento(
        self,
        update: Update,
        sesion: SesionUsuario,
        texto: str,
        idx: int,
        archivo: dict,
    ):
        datos_actuales = archivo.get("datos_extraidos", {})
        prompt = (
            f"El usuario quiere corregir valores. "
            f"Valores actuales: {json.dumps(datos_actuales)}\n"
            f"El usuario dice: '{texto}'\n"
            "Retorna SOLO el JSON con los valores corregidos. "
            "Mantiene los que no se mencionaron."
        )
        respuesta = self._ai.completar(
            mensajes=[{"role": "user", "content": prompt}],
            system_prompt="Eres un extractor de correcciones. Responde SOLO con JSON.",
        )
        if not respuesta.error:
            try:
                texto_json   = re.sub(r"```json|```", "", respuesta.texto).strip()
                datos_nuevos = json.loads(texto_json)
                archivo["datos_extraidos"] = datos_nuevos
                indice = sesion.datos_confirmados.get("zip_indice", [])
                indice[idx] = archivo
                sesion.datos_confirmados["zip_indice"] = indice
                sesion.ultima_pregunta = f"confirmar_doc_{idx}"
                self._sessions.guardar(sesion)
                await update.message.reply_text("Correccion aplicada:")
                total = len(indice)
                await self._presentar_documento(update, sesion, archivo, idx, total)
                return
            except Exception as e:
                logger.warning(f"Error aplicando correccion: {e}")

        await update.message.reply_text(
            "No entendi la correccion. Indicame:\n"
            "'el [nombre del campo] es [valor]'\n"
            "Ejemplo: 'el saldo es 27000000'"
        )

    # ------------------------------------------------------------------
    # PASO 11 — Calcular borrador
    # ------------------------------------------------------------------
    async def _paso11_calcular_borrador(
        self, update: Update, sesion: SesionUsuario
    ):
        # Limpiar el ZIP temporal
        ruta_zip = sesion.datos_confirmados.get("ruta_zip", "")
        if ruta_zip and os.path.exists(ruta_zip):
            try:
                os.unlink(ruta_zip)
            except Exception:
                pass

        # Usar documentos confirmados
        docs_confirmados = sesion.datos_confirmados.get("docs_confirmados", [])
        sesion.documentos_recibidos = docs_confirmados

        await update.message.reply_text(
            "Todos los documentos revisados! Calculando tu borrador del "
            "Formulario 210..."
        )

        borrador = self._calcular_borrador(sesion)
        sesion.borrador_210 = borrador
        sesion.estado       = EstadoBot.REVISION
        sesion.paso_actual  = 11
        self._sessions.guardar(sesion)

        chunks = self._rag.recuperar_contexto(
            "cedulas rentas trabajo capital no laborales pension "
            "rentas exentas deducciones limitadas impuesto retenciones"
        )
        system = self._prompts.construir_system_prompt(
            chunks,
            sesion.resumen_exogena,
            contexto_extra=(
                f"DATOS PERSONALES:\n"
                f"- Dependientes: {sesion.datos_confirmados.get('num_dependientes', 0)}\n"
                f"BORRADOR CALCULADO:\n{self._formatear_borrador(borrador)}"
            ),
        )
        prompt = (
            f"Paso {TOTAL_PASOS} de {TOTAL_PASOS} — "
            "Explica el borrador completo del Formulario 210:\n"
            "1. Recorre cada cedula con sus valores reales.\n"
            "2. Para cada renta exenta o deduccion, cita el articulo del ET "
            "y el tope en UVT y pesos.\n"
            "3. Si hubo dependientes, explica como se calculo esa deduccion.\n"
            "4. Si hubo pensiones voluntarias, indica si son exentas o gravadas "
            "segun el plazo de permanencia del certificado.\n"
            "5. Muestra claramente si hay saldo a cargo o a favor.\n"
            "6. Recuerda verificar en el sistema oficial de la DIAN."
        )

        respuesta = self._ai.completar(
            mensajes=sesion.historial_mensajes + [{"role": "user", "content": prompt}],
            system_prompt=system,
        )

        if respuesta.error:
            await update.message.reply_text(
                "Error generando la explicacion. Puedes preguntar "
                "sobre cualquier campo directamente."
            )
            return

        sesion.historial_mensajes.append({"role": "user",      "content": prompt})
        sesion.historial_mensajes.append({"role": "assistant",  "content": respuesta.texto})
        self._sessions.guardar(sesion)

        await update.message.reply_text(respuesta.texto)
        await self._enviar_excel(update, sesion)

    # ------------------------------------------------------------------
    # Router de texto — segun estado y ultima_pregunta
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Verificaciones previas a cualquier mensaje
    # ------------------------------------------------------------------
    async def _verificar_sesion_activa(
        self, update: Update, sesion
    ) -> bool:
        """
        Retorna True si la sesion esta activa y no ha expirado.
        Si expiro o el estado es terminal, notifica al usuario y retorna False.
        """
        if not sesion:
            await update.message.reply_text("Usa /start para iniciar.")
            return False

        # Sesion en estado terminal — no hay nada que verificar
        if sesion.estado in (EstadoBot.FINALIZADO, EstadoBot.NO_OBLIGADO):
            return True

        # Verificar timeout
        horas_inactivo = (time.time() - sesion.ultima_actividad) / 3600
        if horas_inactivo >= SESSION_TIMEOUT_HORAS:
            self._sessions.eliminar(sesion.chat_id)
            await update.message.reply_text(MSG_SESSION_EXPIRADA)
            return False

        return True

    async def _es_cancelacion(self, texto: str) -> bool:
        """
        Usa el LLM para detectar si el usuario quiere cancelar el proceso,
        independientemente de como lo escriba.
        Ejemplos: 'para', 'cancela', 'no quiero seguir', 'dejalo', 'olvídalo',
                  'ya no', 'salir', 'bye', 'cancelar', 'detener', etc.
        """
        # Chequeo rapido por palabras obvias antes de llamar al LLM
        palabras_obvias = {
            "cancelar", "cancel", "cancela", "para", "parar", "parate",
            "detener", "detente", "salir", "exit", "stop", "bye",
            "adios", "chao", "no quiero", "olvida", "olvidalo", "dejalo",
            "ya no", "no mas", "no sigo", "terminar",
        }
        texto_lower = texto.lower().strip()
        if any(p in texto_lower for p in palabras_obvias):
            return True

        # Para textos ambiguos, consultar al LLM
        if len(texto_lower) > 3:
            prompt = (
                f"El usuario escribio: '{texto}'\n"
                "Quiere cancelar o detener el proceso actual? "
                "Responde SOLO con SI o NO."
            )
            respuesta = self._ai.completar(
                mensajes=[{"role": "user", "content": prompt}],
                system_prompt="Eres un clasificador. Responde SOLO con SI o NO.",
            )
            if not respuesta.error:
                return "SI" in respuesta.texto.upper()

        return False

    async def _manejar_texto(
        self, update: Update, ctx: ContextTypes.DEFAULT_TYPE
    ):
        chat_id = update.effective_chat.id
        texto   = update.message.text.strip()
        sesion  = self._sessions.obtener(chat_id)

        # Verificar sesion activa y timeout
        if not await self._verificar_sesion_activa(update, sesion):
            return

        # Actualizar timestamp de actividad
        sesion.ultima_actividad = time.time()

        # Detectar cancelacion en cualquier punto del flujo
        # (excepto en la etapa de revision libre donde puede preguntar de todo)
        if sesion.estado not in (EstadoBot.REVISION, EstadoBot.FINALIZADO,
                                  EstadoBot.NO_OBLIGADO):
            if await self._es_cancelacion(texto):
                self._sessions.eliminar(chat_id)
                await update.message.reply_text(MSG_CANCELADO)
                return

        self._sessions.guardar(sesion)

        ultima = sesion.ultima_pregunta

        if ultima == "declaracion_voluntaria":
            await self._voluntaria(update, sesion, texto)
        elif ultima == "confirmacion_datos":
            await self._paso2_confirmar_datos(update, sesion, texto)
        elif ultima == "p3_dependientes":
            await self._paso3_dependientes(update, sesion, texto)
        elif ultima == "p3_cuantos":
            await self._paso3_cuantos(update, sesion, texto)
        elif ultima == "p4_hipoteca":
            await self._paso4_hipoteca(update, sesion, texto)
        elif ultima == "p5_medicina":
            await self._paso5_medicina(update, sesion, texto)
        elif ultima == "p6_afc":
            await self._paso6_afc(update, sesion, texto)
        elif ultima == "p7_pensiones_vol":
            await self._paso7_pensiones_vol(update, sesion, texto)
        elif ultima == "p8_icetex":
            await self._paso8_icetex(update, sesion, texto)
        elif ultima and ultima.startswith("confirmar_doc_"):
            await self._paso10_confirmar(update, sesion, texto)
        else:
            await self._conversar(update, sesion, texto)

    async def _conversar(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        chunks = self._rag.recuperar_contexto(texto)
        system = self._prompts.construir_system_prompt(
            chunks,
            sesion.resumen_exogena,
            contexto_extra=(
                f"BORRADOR ACTUAL:\n{self._formatear_borrador(sesion.borrador_210)}"
                if sesion.borrador_210 else ""
            ),
        )
        sesion.historial_mensajes.append({"role": "user", "content": texto})
        respuesta = self._ai.completar(
            mensajes=sesion.historial_mensajes,
            system_prompt=system,
        )
        if respuesta.error:
            await update.message.reply_text("Error en la IA. Intenta de nuevo.")
            return
        sesion.historial_mensajes.append(
            {"role": "assistant", "content": respuesta.texto}
        )
        self._sessions.guardar(sesion)
        await update.message.reply_text(respuesta.texto)

    async def _voluntaria(
        self, update: Update, sesion: SesionUsuario, texto: str
    ):
        if any(w in texto.upper() for w in ["SI", "SÍ", "S"]):
            sesion.analisis_obligacion.debe_declarar = True
            sesion.estado          = EstadoBot.CONFIRMANDO_DATOS
            sesion.ultima_pregunta = "confirmacion_datos"
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                "Perfecto. Confirmame tu NIT o cedula y nombre completo."
            )
        else:
            sesion.estado = EstadoBot.FINALIZADO
            self._sessions.guardar(sesion)
            await update.message.reply_text(
                "Entendido. Usa /start si necesitas ayuda en el futuro."
            )

    # ------------------------------------------------------------------
    # LOGICA TRIBUTARIA — hardcodeada para precision legal
    # ------------------------------------------------------------------
    def _evaluar_obligacion(self, r: ResumenExogena) -> AnalisisObligacion:
        razones_obliga    = []
        razones_no_obliga = []
        total             = getattr(r, "total_ingresos_brutos", 0)
        patrimonio_est    = r.saldos_cuentas + r.inversiones + r.otros_activos

        if total >= UMBRAL_INGRESOS_COP:
            razones_obliga.append(
                f"Ingresos ${total:,.0f} superan "
                f"${UMBRAL_INGRESOS_COP:,.0f} (1.400 UVT — art. 592 ET)"
            )
        else:
            razones_no_obliga.append(
                f"Ingresos ${total:,.0f} no superan "
                f"${UMBRAL_INGRESOS_COP:,.0f} (1.400 UVT)"
            )

        if patrimonio_est >= UMBRAL_PATRIMONIO_COP:
            razones_obliga.append(
                f"Patrimonio estimado ${patrimonio_est:,.0f} supera "
                f"${UMBRAL_PATRIMONIO_COP:,.0f} (4.500 UVT)"
            )
        if r.total_consignaciones >= UMBRAL_CONSIGNACIONES_COP:
            razones_obliga.append(
                f"Consignaciones ${r.total_consignaciones:,.0f} superan "
                f"${UMBRAL_CONSIGNACIONES_COP:,.0f} (1.400 UVT)"
            )
        if r.total_compras >= UMBRAL_COMPRAS_COP:
            razones_obliga.append(
                f"Compras/consumos ${r.total_compras:,.0f} superan "
                f"${UMBRAL_COMPRAS_COP:,.0f} (1.400 UVT)"
            )
        if r.tiene_dividendos:
            razones_obliga.append("Tiene ingresos por dividendos")
        if r.ganancias_ocasionales > 0:
            razones_obliga.append(
                f"Tiene ganancias ocasionales de ${r.ganancias_ocasionales:,.0f}"
            )

        debe             = len(razones_obliga) > 0
        puede_voluntaria = not debe and r.total_retenciones > 0

        return AnalisisObligacion(
            debe_declarar=debe,
            razones_obliga=razones_obliga,
            razones_no_obliga=razones_no_obliga,
            puede_beneficiarse_voluntaria=puede_voluntaria,
            retenciones_recuperables=r.total_retenciones if puede_voluntaria else 0.0,
        )

    def _calcular_borrador(self, sesion: SesionUsuario) -> dict:
        r   = sesion.resumen_exogena
        doc = sesion.documentos_recibidos
        dat = sesion.datos_confirmados

        intereses_vivienda    = 0.0
        medicina_prepagada    = 0.0
        aportes_afc_fpv       = 0.0
        intereses_icetex      = 0.0
        pensiones_vol_gravadas = 0.0
        saldo_patrimonio      = 0.0

        for d in doc:
            datos = d.get("datos_extraidos", {})
            tipo  = d.get("tipo_detectado", "")

            if tipo == "certificado_credito_hipotecario":
                intereses_vivienda += datos.get("intereses_pagados_anual", 0.0) or 0.0

            elif tipo == "certificado_medicina_prepagada":
                medicina_prepagada += datos.get("valor_pagado_anual", 0.0) or 0.0

            elif tipo in ("certificado_afc_fpv",):
                aportes_afc_fpv += (
                    (datos.get("aportes_afc", 0.0) or 0.0)
                    + (datos.get("aportes_fpv", 0.0) or 0.0)
                    + (datos.get("total_aportes", 0.0) or 0.0)
                )

            elif tipo == "certificado_pensiones_voluntarias":
                # Si el plazo de permanencia es < 10 años, los retiros son gravados
                anos_perm = datos.get("anos_permanencia", 0) or 0
                retiros   = datos.get("valor_retiros", 0.0) or 0.0
                if retiros > 0 and anos_perm < FPV_PLAZO_MINIMO_AÑOS:
                    pensiones_vol_gravadas += retiros
                else:
                    # Sin retiros o con plazo cumplido → exento, igual que AFC
                    aportes_afc_fpv += (datos.get("total_aportes", 0.0) or 0.0)

            elif tipo == "certificado_icetex":
                intereses_icetex += datos.get("intereses_pagados_anual", 0.0) or 0.0

            elif tipo == "certificado_rendimientos":
                saldo_patrimonio += datos.get("saldo_31_diciembre", 0.0) or 0.0

        # Topes legales
        intereses_vivienda = min(intereses_vivienda, INTERESES_VIVIENDA_COP)
        medicina_prepagada = min(medicina_prepagada, MEDICINA_PREPAGADA_COP_ANUAL)
        intereses_icetex   = min(intereses_icetex,   ICETEX_COP)

        # Dependientes (art. 387 ET + casillas 39 y 139 del formulario 210)
        #
        # DOS componentes separados desde 2023:
        # Componente A → c39 (DENTRO del limite global 40%/1340 UVT):
        #   10% renta laboral mensual, max 32 UVT/mes
        # Componente B → c139 (FUERA del limite global, adicion directa a c92):
        #   72 UVT adicionales por dependiente, max 4
        #   Solo si hay rentas de trabajo (c42+c57 > 0)
        #   PDF cas.139 pag.18: c92 = c41+c53+c69+c86+c28+c139
        num_dep = min(int(dat.get("num_dependientes", 0)), DEPENDIENTES_MAX_PERSONAS)

        # c39: 10% mensual (dentro del limite global)
        dep_deducc_c39 = min(
            r.ingresos_laborales * DEPENDIENTES_PORCENTAJE_MES,
            DEPENDIENTES_MAX_COP_MES * 12,
        )
        # c139: 72 UVT/persona adicionales (fuera del limite global)
        dep_adicional_c139 = num_dep * (DEPENDIENTES_UVT_POR_PERSONA * UVT)

        # GMF
        gmf_deducible = r.gmf_pagado * GMF_PORCENTAJE_DEDUCIBLE

        # CEDULA GENERAL — Rentas de Trabajo
        c32 = r.ingresos_laborales
        c33 = r.ingresos_no_const
        c34 = max(0.0, c32 - c33)

        c35 = min(
            aportes_afc_fpv,
            min(c32 * AFC_FVP_AVC_PORCENTAJE, AFC_FVP_AVC_TOPE_COP),
        )
        c36 = min(c34 * EXENTA_25_PORCENTAJE, EXENTA_25_COP)
        c37 = c35 + c36
        c38 = intereses_vivienda
        # c39: sin los 72 UVT/persona (esos van a c139 fuera del limite)
        c39 = medicina_prepagada + dep_deducc_c39 + intereses_icetex + gmf_deducible
        c40 = c38 + c39

        ingreso_neto = max(0.0,
            (c32 + r.ingresos_no_laborales_trabajo
             + r.ingresos_capital + r.ingresos_no_laborales) - c33
        )
        limite_global = min(ingreso_neto * LIMITE_GLOBAL_PORCENTAJE, LIMITE_GLOBAL_COP)
        c41 = min(c37 + c40, limite_global, c34)
        c42 = max(0.0, c34 - c41)

        # Pensiones voluntarias gravadas van a rentas no laborales
        c74 = r.ingresos_no_laborales + pensiones_vol_gravadas
        c90 = max(0.0, c74)
        c43 = r.ingresos_no_laborales_trabajo
        c57 = max(0.0, c43 - r.ingresos_no_const)
        c58 = r.ingresos_capital
        c73 = max(0.0, c58)

        # cas91 formulario = renta liquida cedula general (c41+c42+c57+c73+c90)
        renta_liq_cedula_gral = c42 + c57 + c73 + c90

        # c139: tope = c42+c57 (no puede superar rentas de trabajo)
        c139 = min(dep_adicional_c139, c42 + c57)

        # c92 = c41 + c139 (simplificado perfil asalariado; sin c28 factura electronica)
        c92 = c41 + c139

        # c93 = renta liquida ordinaria cedula general
        c93 = max(0.0, renta_liq_cedula_gral - c92)

        # CEDULA DE PENSIONES (casillas 99-103 del formulario)
        cas99          = r.ingresos_pensiones
        mesada_mensual = cas99 / 12 if cas99 > 0 else 0
        cas102 = (
            cas99
            if mesada_mensual <= PENSION_EXENTA_COP_MES
            else min(cas99 * 0.25, EXENTA_25_COP)
        )
        cas103 = max(0.0, cas99 - cas102)

        c100 = r.dividendos

        # Impuesto: base = c93 (cedula general) + cas103 (pensiones)
        base_uvt_gral     = c93 / UVT
        impuesto_gral     = self._calcular_impuesto(base_uvt_gral)
        base_uvt_pension  = cas103 / UVT
        impuesto_pensiones = self._calcular_impuesto(base_uvt_pension)

        c116      = r.retenciones_trabajo
        c117      = r.retenciones_capital
        c118      = r.retenciones_no_laborales
        c119      = r.retenciones_pensiones
        total_ret = c116 + c117 + c118 + c119

        c121  = impuesto_gral + impuesto_pensiones
        saldo = c121 - total_ret

        return {
            "c29_patrimonio_bruto":         r.saldos_cuentas + r.inversiones + r.otros_activos + saldo_patrimonio,
            "c30_deudas":                   float(dat.get("deudas", 0)),
            "c32_ing_laborales":            c32,
            "c33_no_constitutivos":         c33,
            "c34_renta_liq":                c34,
            "c35_exenta_afc_fpv":           c35,
            "c36_exenta_25":                c36,
            "c37_total_exentas":            c37,
            "c38_ded_vivienda":             c38,
            "c39_otras_ded":                c39,
            "c39_det_dep_10pct":            dep_deducc_c39,
            "c39_det_num_dependientes":     num_dep,
            "c39_det_medicina":             medicina_prepagada,
            "c39_det_icetex":               intereses_icetex,
            "c39_det_gmf":                  gmf_deducible,
            "c40_total_ded":                c40,
            "c41_limitadas":                c41,
            "c42_renta_liq_ord":            c42,
            "c43_ing_no_lab_trab":          c43,
            "c57_renta_liq_no_lab_trab":    c57,
            "c58_ing_capital":              c58,
            "c73_renta_liq_capital":        c73,
            "c74_ing_no_lab":               c74,
            "c74_det_pensiones_vol_grav":   pensiones_vol_gravadas,
            "c90_renta_liq_no_lab":         c90,
            "c91_renta_liq_cedula_gral":    renta_liq_cedula_gral,
            "c92_rentas_exentas_lim":       c92,
            "c139_dep_adicionales":         c139,
            "c93_renta_liq_ord_cedula":     c93,
            "cas99_ing_pensiones":          cas99,
            "cas102_exenta_pension":        cas102,
            "cas103_renta_grav_pension":    cas103,
            "c100_dividendos":              c100,
            "impuesto_cedula_gral":         impuesto_gral,
            "impuesto_pensiones":           impuesto_pensiones,
            "c121_total_impuesto":          c121,
            "base_impuesto_uvt":            round(base_uvt_gral, 2),
            "c116_ret_trabajo":             c116,
            "c117_ret_capital":             c117,
            "c118_ret_no_lab":              c118,
            "c119_ret_pension":             c119,
            "total_retenciones":            total_ret,
            "saldo_cargo_o_favor":          saldo,
            "_anno_gravable":               ANNO_GRAVABLE,
            "_uvt":                         UVT,
            "_num_dependientes":            num_dep,
            "_limite_global":               round(limite_global, 0),
        }

    def _calcular_impuesto(self, base_uvt: float) -> float:
        for desde, hasta, tarifa, imp_base in TABLA_TARIFAS:
            if desde <= base_uvt < hasta:
                return (imp_base + (base_uvt - desde) * tarifa) * UVT
        return 0.0

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------
    async def _enviar_excel(self, update: Update, sesion: SesionUsuario):
        if not sesion.borrador_210:
            return
        ruta_excel = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                ruta_excel = tmp.name
            self._generator.generar_excel(sesion.borrador_210, ruta_excel)
            await update.message.reply_document(
                document=open(ruta_excel, "rb"),
                filename=f"Borrador_Formulario_210_{ANNO_GRAVABLE}.xlsx",
                caption=(
                    "Borrador del Formulario 210 con todos los valores confirmados.\n\n"
                    "IMPORTANTE: Este borrador es orientativo. "
                    "Verifica y presenta en el sistema oficial de la DIAN."
                ),
            )
        except Exception as e:
            logger.warning(f"No se pudo generar Excel: {e}")
        finally:
            if ruta_excel:
                try:
                    os.unlink(ruta_excel)
                except Exception:
                    pass

    def _formatear_borrador(self, borrador: dict) -> str:
        if not borrador:
            return "Sin borrador calculado aun."
        return "\n".join(
            f"  {k}: ${v:,.0f}" if isinstance(v, float) else f"  {k}: {v}"
            for k, v in borrador.items()
            if not k.startswith("_")
        )

    async def _manejar_error(
        self, update: object, ctx: ContextTypes.DEFAULT_TYPE
    ):
        logger.exception(f"Error en el bot: {ctx.error}")
        if isinstance(update, Update) and update.message:
            await update.message.reply_text(
                "Ocurrio un error inesperado. "
                "Intenta de nuevo o usa /reiniciar."
            )