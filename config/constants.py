"""
config/constants.py
Constantes tributarias Colombia.

REGLA DE ORO:
  Solo hay DOS valores hardcodeados que cambian cada año: ANNO_GRAVABLE y UVT.
  Todo lo demas se expresa en UVT y se calcula desde ahi.

Año gravable : 2025  (declaracion presentada en 2026)
UVT          : $49.799 (Resolucion DIAN 000193 del 4-dic-2024)
Plazos       : Segun calendario DIAN 2026
"""

# ─────────────────────────────────────────────────────────────
# LAS UNICAS DOS LINEAS QUE CAMBIAN CADA AÑO
# ─────────────────────────────────────────────────────────────
ANNO_GRAVABLE = 2025
UVT = 49_799  # COP — Resolucion DIAN 000193 del 4-dic-2024


def uvt(n: float) -> int:
    """Convierte N UVT a pesos colombianos (redondeado al peso)."""
    return round(n * UVT)


# ─────────────────────────────────────────────────────────────
# UMBRALES DE OBLIGACION DE DECLARAR (art. 592-594 ET)
# ─────────────────────────────────────────────────────────────
UMBRAL_INGRESOS_UVT       = 1_400
UMBRAL_PATRIMONIO_UVT     = 4_500
UMBRAL_COMPRAS_UVT        = 1_400
UMBRAL_CONSIGNACIONES_UVT = 1_400

UMBRAL_INGRESOS_COP       = uvt(UMBRAL_INGRESOS_UVT)       # 69_718_600
UMBRAL_PATRIMONIO_COP     = uvt(UMBRAL_PATRIMONIO_UVT)      # 224_095_500
UMBRAL_COMPRAS_COP        = uvt(UMBRAL_COMPRAS_UVT)         # 69_718_600
UMBRAL_CONSIGNACIONES_COP = uvt(UMBRAL_CONSIGNACIONES_UVT)  # 69_718_600


# ─────────────────────────────────────────────────────────────
# LIMITES RENTAS EXENTAS Y DEDUCCIONES (art. 336 ET)
# ─────────────────────────────────────────────────────────────
LIMITE_GLOBAL_PORCENTAJE = 0.40
LIMITE_GLOBAL_UVT        = 1_340
LIMITE_GLOBAL_COP        = uvt(LIMITE_GLOBAL_UVT)       # 66_730_660

EXENTA_25_PORCENTAJE = 0.25
EXENTA_25_UVT        = 790
EXENTA_25_COP        = uvt(EXENTA_25_UVT)               # 39_341_210

AFC_FVP_AVC_PORCENTAJE = 0.30
AFC_FVP_AVC_TOPE_UVT   = 3_800
AFC_FVP_AVC_TOPE_COP   = uvt(AFC_FVP_AVC_TOPE_UVT)     # 189_236_200

INTERESES_VIVIENDA_UVT = 1_200
INTERESES_VIVIENDA_COP = uvt(INTERESES_VIVIENDA_UVT)    # 59_758_800

MEDICINA_PREPAGADA_UVT_MES   = 16
MEDICINA_PREPAGADA_COP_MES   = uvt(MEDICINA_PREPAGADA_UVT_MES)
MEDICINA_PREPAGADA_COP_ANUAL = MEDICINA_PREPAGADA_COP_MES * 12  # 9_561_408

DEPENDIENTES_PORCENTAJE_MES  = 0.10
DEPENDIENTES_MAX_UVT_MES     = 32
DEPENDIENTES_MAX_COP_MES     = uvt(DEPENDIENTES_MAX_UVT_MES)
DEPENDIENTES_UVT_POR_PERSONA = 72
DEPENDIENTES_MAX_PERSONAS    = 4
DEPENDIENTES_MAX_COP_ANUAL   = uvt(
    DEPENDIENTES_UVT_POR_PERSONA * DEPENDIENTES_MAX_PERSONAS
)  # 14_342_112

ICETEX_UVT = 100
ICETEX_COP = uvt(ICETEX_UVT)                            # 4_979_900

GMF_PORCENTAJE_DEDUCIBLE = 0.50

FACTURA_ELECTRONICA_UVT = 240
FACTURA_ELECTRONICA_COP = uvt(FACTURA_ELECTRONICA_UVT)

PENSION_EXENTA_UVT_MES = 1_000
PENSION_EXENTA_COP_MES = uvt(PENSION_EXENTA_UVT_MES)

# Plazo minimo de permanencia en fondos para que el retiro sea exento (art. 126-1 ET)
FPV_PLAZO_MINIMO_AÑOS = 10


# ─────────────────────────────────────────────────────────────
# TABLA DE TARIFAS (art. 241 ET)
# ─────────────────────────────────────────────────────────────
TABLA_TARIFAS = [
    (0,        1_090, 0.00,  0),
    (1_090,    1_700, 0.19,  0),
    (1_700,    4_100, 0.28,  116),
    (4_100,    8_670, 0.33,  788),
    (8_670,   18_970, 0.35,  2_296),
    (18_970,  31_000, 0.37,  5_901),
    (31_000,  float("inf"), 0.39, 10_352),
]

TABLA_TARIFAS_DIVIDENDOS = [
    (0,   300, 0.00, 0),
    (300, float("inf"), 0.15, 0),
]

TARIFA_GANANCIAS_OCASIONALES = 0.15
TARIFA_LOTERIAS_HERENCIAS    = 0.20


# ─────────────────────────────────────────────────────────────
# FORMATOS EXOGENA
# ─────────────────────────────────────────────────────────────
FORMATOS_EXOGENA = {
    "220":  "Certificado ingresos y retenciones → Rentas de Trabajo",
    "2276": "Pagos a independientes → Rentas Trabajo no laborales",
    "1001": "Honorarios, comisiones, servicios → Rentas no laborales",
    "1007": "Ingresos recibidos de terceros",
    "1008": "Retenciones practicadas",
    "1009": "Pagos al exterior",
    "1010": "Dividendos → Cedula dividendos",
    "1012": "Saldos cuentas → Patrimonio",
    "1014": "Creditos e inversiones financieras → Patrimonio / Capital",
    "2275": "Ingresos no constitutivos de renta",
    "2278": "Rendimientos financieros → Rentas de Capital",
    "5247": "Activos fijos → Patrimonio bruto",
}

ENTIDADES_FINANCIERAS = [
    "DAVIVIENDA", "BANCOLOMBIA", "BANCO DE BOGOTA", "BBVA",
    "BANCO POPULAR", "BANCO DE OCCIDENTE", "AV VILLAS",
    "COLPATRIA", "ITAU", "SCOTIABANK", "CITIBANK",
    "COOMEVA", "CONFIAR", "COOPCENTRAL",
    "FIDUCIARIA", "FONDO", "PORVENIR", "PROTECCION",
    "COLFONDOS", "OLD MUTUAL", "SKANDIA",
]

# Alias para compatibilidad con excel_parser.py
ENTIDADES_FINANCIERAS_CONOCIDAS = ENTIDADES_FINANCIERAS

ENTIDADES_FPV = [
    "PORVENIR", "PROTECCION", "COLFONDOS", "OLD MUTUAL",
    "SKANDIA", "FIDUCOLDEX", "FIDUCOLOMBIA",
]

ENTIDADES_AFC = [
    "DAVIVIENDA AFC", "BANCOLOMBIA AFC", "AV VILLAS AFC",
    "BANCO POPULAR AFC", "FNA",
]

ENTIDADES_PENSION = [
    "COLPENSIONES", "PORVENIR", "PROTECCION", "COLFONDOS",
    "OLD MUTUAL", "SKANDIA",
]


# ─────────────────────────────────────────────────────────────
# NUMERACION DE PASOS DEL FLUJO
# Centralizado aqui para que los mensajes sean consistentes
# ─────────────────────────────────────────────────────────────
PASO_EXOGENA             = 1
PASO_CONFIRMAR_DATOS     = 2
PASO_DEPENDIENTES        = 3
PASO_HIPOTECA            = 4
PASO_MEDICINA            = 5
PASO_AFC_FPV             = 6
PASO_PENSIONES_VOL       = 7
PASO_ICETEX              = 8
PASO_RESUMEN_ZIP         = 9
PASO_REVISION_DOCS       = 10
PASO_BORRADOR            = 11
TOTAL_PASOS              = 11

# Paso donde se sube el ZIP — referenciado en todos los mensajes de documentos
PASO_ZIP = PASO_RESUMEN_ZIP


# ─────────────────────────────────────────────────────────────
# MENSAJES POR PASO — cadena de preguntas una a una
# ─────────────────────────────────────────────────────────────

# Prefijo estandar para cada pregunta
def prefijo(paso: int) -> str:
    return f"Paso {paso} de {TOTAL_PASOS}"


MSG_P3_DEPENDIENTES = (
    f"Paso {PASO_DEPENDIENTES} de {TOTAL_PASOS} — Dependientes economicos\n\n"
    "Tienes personas a tu cargo economicamente? Por ejemplo:\n"
    "  • Hijos menores de 18 anos\n"
    "  • Hijos entre 18 y 23 anos que esten estudiando\n"
    "  • Conyuge o companero(a) sin ingresos propios\n"
    "  • Padres o hermanos que dependan de ti\n\n"
    "Responde SI o NO."
)

MSG_P3_CUANTOS = (
    "Cuantos dependientes tienes y de que tipo? "
    "Por ejemplo: 'dos hijos menores' o 'mi mama y un hijo de 20 anos estudiando'."
)

MSG_P4_HIPOTECA = (
    f"Paso {PASO_HIPOTECA} de {TOTAL_PASOS} — Credito hipotecario\n\n"
    "Tienes un credito hipotecario de vivienda? (SI / NO)"
)

MSG_P4_SI = (
    "Perfecto. Descargalo desde la app o pagina web de tu banco,\n"
    "seccion Certificados -> Declaracion de renta {anno}.\n\n"
    "Cuando lo tengas, renombralo exactamente asi:\n"
    "  certificado_hipoteca_NOMBRE_BANCO.pdf\n"
    "Ejemplo: certificado_hipoteca_DAVIVIENDA.pdf\n\n"
    "Tenlo listo para el Paso {paso_zip}.\n\n"
    "Escribe 'cancelar' en cualquier momento para detener el proceso."
)

MSG_P5_MEDICINA = (
    f"Paso {PASO_MEDICINA} de {TOTAL_PASOS} — Medicina prepagada\n\n"
    "Pagaste medicina prepagada o seguro de salud complementario en {anno}? "
    "(SI / NO)"
)

MSG_P5_SI = (
    "Solicítalo en la pagina web o app de tu entidad de salud,\n"
    "seccion Certificados o Documentos tributarios.\n\n"
    "Cuando lo tengas, renombralo exactamente asi:\n"
    "  certificado_medicina_NOMBRE_ENTIDAD.pdf\n"
    "Ejemplo: certificado_medicina_COLSANITAS.pdf\n\n"
    "Tenlo listo para el Paso {paso_zip}."
)

MSG_P6_AFC = (
    f"Paso {PASO_AFC_FPV} de {TOTAL_PASOS} — Cuenta AFC o fondo de pensiones voluntarias\n\n"
    "Hiciste aportes voluntarios a una cuenta AFC o a un fondo de pensiones "
    "voluntarias en {anno}? (SI / NO)"
)

MSG_P6_SI = (
    "Descargalo desde la app o pagina web de tu banco o fondo,\n"
    "seccion Certificados -> Declaracion de renta {anno}.\n\n"
    "Cuando lo tengas, renombralo exactamente asi:\n"
    "  certificado_afc_NOMBRE_ENTIDAD.pdf\n"
    "Ejemplo: certificado_afc_DAVIVIENDA.pdf o certificado_afc_PORVENIR.pdf\n\n"
    "Tenlo listo para el Paso {paso_zip}."
)

MSG_P7_PENSIONES_VOL = (
    f"Paso {PASO_PENSIONES_VOL} de {TOTAL_PASOS} — Fondo de pensiones voluntarias\n\n"
    "Recibiste pagos en tu fondo de pensiones voluntarias durante {anno}? "
    "(SI / NO)"
)

MSG_P7_SI = (
    "Solicítalo a tu fondo. El documento debe incluir las fechas de aportes\n"
    "y los montos de cualquier retiro que hayas hecho durante el ano.\n\n"
    "Cuando lo tengas, renombralo exactamente asi:\n"
    "  certificado_pensiones_voluntarias_NOMBRE_FONDO.pdf\n"
    "Ejemplo: certificado_pensiones_voluntarias_PORVENIR.pdf\n\n"
    "Tenlo listo para el Paso {paso_zip}."
)

MSG_P8_ICETEX = (
    f"Paso {PASO_ICETEX} de {TOTAL_PASOS} — Credito educativo ICETEX\n\n"
    "Tienes un credito educativo con el ICETEX? (SI / NO)"
)

MSG_P8_SI = (
    "Descargalo desde la pagina del ICETEX,\n"
    "seccion Mi ICETEX -> Certificados.\n\n"
    "Cuando lo tengas, renombralo exactamente asi:\n"
    "  certificado_icetex.pdf\n\n"
    "Tenlo listo para el Paso {paso_zip}."
)


def _nombre_entidad_corto(nombre: str, limite: int = 70) -> str:
    """
    Convierte un nombre de entidad en un token apto para nombre de archivo,
    truncando sin cortar palabras a la mitad si supera el limite de caracteres.

    Ejemplo con limite=40:
      'SCOTIABANK COLPATRIA S.A. Y PODRA UTILIZAR...' → 'SCOTIABANK_COLPATRIA_S.A._Y_PODRA'
      'BANCO DAVIVIENDA S.A.'                         → 'BANCO_DAVIVIENDA_S.A.'  (sin truncar)
    """
    token = nombre.upper().replace(" ", "_")
    if len(token) <= limite:
        return token
    # Truncar sin cortar a mitad de palabra
    recortado = token[:limite]
    ultimo_sep = recortado.rfind("_")
    if ultimo_sep > 0:
        recortado = recortado[:ultimo_sep]
    return recortado


def msg_resumen_zip(
    pagadores_laborales: list,
    entidades_financieras: list,
    docs_opcionales: list,
    docs_obligatorios_extra: list = None,
) -> str:
    """
    Construye el mensaje del Paso 9 (resumen + solicitud del ZIP)
    con los documentos obligatorios y opcionales personalizados.

    pagadores_laborales     : lista de nombres de empleadores de la exogena
    entidades_financieras   : lista de nombres de bancos de la exogena
    docs_obligatorios_extra : lista de tuplas (emoji, nombre_archivo) detectados
                              automaticamente en la exogena (ej. fondo pension vol)
    docs_opcionales         : lista de tuplas (emoji, nombre_archivo) confirmados
                              por el usuario en los pasos anteriores
    """
    lineas = [
        f"Paso {PASO_RESUMEN_ZIP} de {TOTAL_PASOS} — Armar el ZIP con tus documentos\n",
        "Ya tengo todo lo que necesito saber. Ahora arma UN SOLO archivo ZIP "
        "con los siguientes documentos.\n",
        "El nombre de cada archivo importa — usalo exactamente como se indica "
        "para que pueda leerlos correctamente:\n",
        "OBLIGATORIOS:\n",
    ]

    for empleador in pagadores_laborales:
        nombre_archivo = "certificado_ingresos_" + _nombre_entidad_corto(empleador) + ".pdf"
        lineas.append(f"📄 {nombre_archivo}\n")

    for entidad in entidades_financieras:
        nombre_archivo = "certificado_rendimientos_" + _nombre_entidad_corto(entidad) + ".pdf"
        lineas.append(f"🏦 {nombre_archivo}\n")

    for emoji, nombre_archivo in (docs_obligatorios_extra or []):
        lineas.append(f"{emoji} {nombre_archivo}\n")

    if docs_opcionales:
        lineas.append("\nOPCIONALES:\n")
        for emoji, descripcion in docs_opcionales:
            lineas.append(f"{emoji} {descripcion}\n")

    lineas.append(
        f"\nCuando tengas todos los archivos renombrados correctamente, "
        f"comprímelos en un ZIP y subelo aqui.\n"
        f"Voy leyendo cada documento contigo uno por uno."
    )

    return "\n".join(lineas)


# ─────────────────────────────────────────────────────────────
# TIMEOUT Y CANCELACION
# ─────────────────────────────────────────────────────────────
SESSION_TIMEOUT_HORAS = 5  # sesion expira despues de N horas sin actividad

MSG_SESSION_EXPIRADA = (
    "Tu sesion expiro por inactividad (mas de 5 horas sin actividad).\n\n"
    "No te preocupes, puedes empezar de nuevo cuando quieras con /start."
)

MSG_CANCELADO = (
    "Proceso cancelado. Cuando quieras retomarlo usa /start."
)

# Aviso de cancelacion que se agrega al primer SI de cada paso
AVISO_CANCELAR = "\n\nEscribe 'cancelar' en cualquier momento para detener el proceso."


# ─────────────────────────────────────────────────────────────
# ESTADOS DEL FLUJO CONVERSACIONAL
# ─────────────────────────────────────────────────────────────
class EstadoBot:
    INICIO                  = "inicio"
    ESPERANDO_EXOGENA       = "esperando_exogena"
    ANALIZANDO              = "analizando"
    NO_OBLIGADO             = "no_obligado"
    CONFIRMANDO_DATOS       = "confirmando_datos"          # Paso 2
    PREGUNTA_DEPENDIENTES   = "pregunta_dependientes"      # Paso 3
    PREGUNTA_CUANTOS_DEP    = "pregunta_cuantos_dep"       # Paso 3b
    PREGUNTA_HIPOTECA       = "pregunta_hipoteca"          # Paso 4
    PREGUNTA_MEDICINA       = "pregunta_medicina"          # Paso 5
    PREGUNTA_AFC            = "pregunta_afc"               # Paso 6
    PREGUNTA_PENSIONES_VOL  = "pregunta_pensiones_vol"     # Paso 7
    PREGUNTA_ICETEX         = "pregunta_icetex"            # Paso 8
    RESUMEN_ZIP             = "resumen_zip"                # Paso 9
    ESPERANDO_ZIP           = "esperando_zip"
    REVISANDO_DOCUMENTOS    = "revisando_documentos"       # Paso 10
    CONFIRMANDO_DOCUMENTO   = "confirmando_documento"      # Paso 10
    GENERANDO_BORRADOR      = "generando_borrador"         # Paso 11
    REVISION                = "revision"
    FINALIZADO              = "finalizado"


# ─────────────────────────────────────────────────────────────
# MENSAJES GENERALES
# ─────────────────────────────────────────────────────────────
MSG_BIENVENIDA = (
    f"Hola! Soy tu asistente para la declaracion de renta en Colombia, "
    f"formulario 210 ano gravable {ANNO_GRAVABLE}.\n\n"
    "Voy a ayudarte a determinar si debes declarar y, si es asi, a "
    "diligenciar cada campo correctamente segun tu informacion real.\n\n"
    f"El proceso tiene {TOTAL_PASOS} pasos y vamos uno a uno.\n\n"
    f"Paso {PASO_EXOGENA} de {TOTAL_PASOS} — Para comenzar, sube tu archivo "
    "de exogena en formato Excel (.xlsx o .xls) descargado del portal de la DIAN."
)

MSG_ERROR_ARCHIVO = (
    "No pude leer el archivo. Asegurate de que sea un Excel valido "
    "(.xlsx o .xls) exportado del portal de la DIAN e intentalo de nuevo."
)