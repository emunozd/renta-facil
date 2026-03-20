"""
parsers/excel_parser.py
Lee el archivo Excel de exogena descargado del portal DIAN.
Mapea cada formato a la cedula y casilla correspondiente del 210.
Principio S: solo sabe leer Excel y mapear al dominio.
"""
import re
import logging
from typing import Optional
import pandas as pd

from interfaces.base import IExogenaParser, ResumenExogena
from config.constants import (
    ENTIDADES_FINANCIERAS_CONOCIDAS,
    ENTIDADES_PENSION,
    ENTIDADES_FPV,
    ENTIDADES_AFC,
    FORMATOS_EXOGENA,
)

logger = logging.getLogger(__name__)


# Columnas estandar que busca el parser (los nombres varian segun version DIAN)
_ALIAS_COLUMNAS = {
    "nit_informante":   ["nit", "nit informante", "nit_informante", "identificacion"],
    "nombre_informante":["nombre", "razon social", "nombre informante", "razon_social"],
    "concepto":         ["concepto", "codigo concepto", "cod concepto"],
    "valor":            ["valor", "monto", "valor pagado", "valor bruto"],
    "valor_retencion":  ["retencion", "valor retencion", "retenido", "valor_retencion"],
    "formato":          ["formato", "tipo reporte", "formato reporte"],
    "nit_receptor":     ["nit receptor", "nit beneficiario", "cedula"],
    "nombre_receptor":  ["nombre receptor", "nombre beneficiario"],
}

# Conceptos de la exogena y su mapeo al 210
_CONCEPTOS_TRABAJO = {
    "5001", "5002", "5003", "5004", "5005",  # salarios, primas, cesantias
    "5009", "5011", "5012", "5013",            # vacaciones, bonificaciones
    "22",   "23",   "24",                      # pagos laborales varios
}

_CONCEPTOS_INDEPENDIENTE = {
    "1001", "1002", "1003",  # honorarios
    "1004", "1005",          # comisiones
    "1006", "1007",          # servicios
    "1008",                  # arrendamientos pagados
}

_CONCEPTOS_RENDIMIENTOS = {
    "1404", "1405",  # intereses y rendimientos
    "1406",          # componente inflacionario
    "1403",          # dividendos
}

_CONCEPTOS_PENSION = {
    "5004", "5051", "5052",  # pensiones
}

_CONCEPTOS_NO_CONSTITUTIVOS = {
    "2204", "2205", "2206",  # aportes salud y pension
    "2207",                   # aportes voluntarios
}

_CONCEPTOS_GMF = {
    "1115",  # gravamen movimientos financieros
}


class ExogenaParser(IExogenaParser):
    """
    Lee el Excel de exogena y extrae toda la informacion relevante
    para el Formulario 210.

    La exogena DIAN no tiene un formato unico y rigido: puede venir con
    hojas distintas por formato (220, 1001, etc.) o como una sola hoja
    consolidada. El parser intenta detectar ambas estructuras.
    """

    def parsear(self, ruta_archivo: str) -> ResumenExogena:
        logger.info(f"Parseando exogena: {ruta_archivo}")
        resultado = ResumenExogena()

        try:
            xls = pd.ExcelFile(ruta_archivo)
        except Exception as e:
            raise ValueError(f"No se pudo abrir el archivo Excel: {e}")

        hojas_procesadas = 0
        for hoja in xls.sheet_names:
            try:
                df = pd.read_excel(ruta_archivo, sheet_name=hoja, dtype=str)
                df.columns = [str(c).strip().lower() for c in df.columns]
                df = df.fillna("0")

                if self._es_hoja_relevante(df):
                    self._procesar_hoja(df, hoja, resultado)
                    hojas_procesadas += 1
            except Exception as e:
                logger.warning(f"Error procesando hoja '{hoja}': {e}")
                resultado.advertencias.append(f"Hoja '{hoja}' no pudo procesarse: {e}")

        if hojas_procesadas == 0:
            raise ValueError(
                "El archivo no tiene hojas con datos reconocibles de exogena DIAN. "
                "Verifica que sea el archivo correcto descargado del portal."
            )

        self._calcular_totales(resultado)
        logger.info(
            f"Exogena procesada: ingresos laborales={resultado.ingresos_laborales:,.0f}, "
            f"ingresos capital={resultado.ingresos_capital:,.0f}, "
            f"pagadores={len(resultado.pagadores)}"
        )
        return resultado

    # ------------------------------------------------------------------
    def _es_hoja_relevante(self, df: pd.DataFrame) -> bool:
        """Detecta si la hoja tiene estructura de exogena."""
        columnas = set(df.columns)
        # Necesita al menos una columna de valor y una de identificacion
        tiene_valor = any(
            any(alias in c for alias in ["valor", "monto"])
            for c in columnas
        )
        tiene_id = any(
            any(alias in c for alias in ["nit", "cedula", "identificacion"])
            for c in columnas
        )
        return tiene_valor and tiene_id and len(df) > 0

    def _normalizar_col(self, df: pd.DataFrame, campo: str) -> Optional[str]:
        """Busca la columna real usando los aliases definidos."""
        aliases = _ALIAS_COLUMNAS.get(campo, [])
        for alias in aliases:
            for col in df.columns:
                if alias in col:
                    return col
        return None

    def _limpiar_valor(self, v: str) -> float:
        """Convierte string a float limpiando formato colombiano."""
        if not v or v in ("0", "", "nan", "none"):
            return 0.0
        v = str(v).replace("$", "").replace(",", "").replace(".", "")
        # Si tiene punto decimal estilo 1.234.567,89 → quitar puntos de miles
        v = re.sub(r"[^\d\-]", "", v)
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    def _nombre_upper(self, nombre: str) -> str:
        return str(nombre).strip().upper()

    def _es_entidad_financiera(self, nombre: str) -> bool:
        n = self._nombre_upper(nombre)
        return any(ent in n for ent in ENTIDADES_FINANCIERAS_CONOCIDAS)

    def _es_fondo_pension(self, nombre: str) -> bool:
        n = self._nombre_upper(nombre)
        return any(ent in n for ent in ENTIDADES_PENSION)

    def _es_fondo_fpv_afc(self, nombre: str) -> bool:
        n = self._nombre_upper(nombre)
        return any(ent in n for ent in ENTIDADES_FPV + ENTIDADES_AFC)

    # ------------------------------------------------------------------
    def _procesar_hoja(
        self, df: pd.DataFrame, nombre_hoja: str, resultado: ResumenExogena
    ) -> None:
        col_nombre   = self._normalizar_col(df, "nombre_informante")
        col_nit      = self._normalizar_col(df, "nit_informante")
        col_valor    = self._normalizar_col(df, "valor")
        col_reten    = self._normalizar_col(df, "valor_retencion")
        col_concepto = self._normalizar_col(df, "concepto")
        col_formato  = self._normalizar_col(df, "formato")

        if not col_valor:
            return

        for _, fila in df.iterrows():
            nombre   = self._nombre_upper(fila.get(col_nombre, "")) if col_nombre else ""
            nit      = str(fila.get(col_nit, "")).strip()           if col_nit    else ""
            valor    = self._limpiar_valor(fila.get(col_valor, "0"))
            retencion = self._limpiar_valor(fila.get(col_reten, "0")) if col_reten else 0.0
            concepto = str(fila.get(col_concepto, "")).strip()         if col_concepto else ""
            formato  = str(fila.get(col_formato, "")).strip()          if col_formato  else ""

            if valor == 0.0:
                continue

            # Detectar datos del receptor (el propio usuario)
            if not resultado.nit_usuario and col_nit:
                col_nit_rec = self._normalizar_col(df, "nit_receptor")
                if col_nit_rec:
                    resultado.nit_usuario = str(fila.get(col_nit_rec, "")).strip()
            if not resultado.nombre_usuario:
                col_nom_rec = self._normalizar_col(df, "nombre_receptor")
                if col_nom_rec:
                    resultado.nombre_usuario = self._nombre_upper(
                        fila.get(col_nom_rec, "")
                    )

            # Clasificar por formato o concepto
            tipo = self._clasificar_tipo(
                nombre, nit, valor, concepto, formato, nombre_hoja
            )

            # Acumular segun tipo detectado
            if tipo == "trabajo_laboral":
                resultado.ingresos_laborales += valor
                resultado.retenciones_trabajo += retencion
            elif tipo == "trabajo_no_laboral":
                resultado.ingresos_no_laborales_trabajo += valor
                resultado.retenciones_no_laborales += retencion
            elif tipo == "capital":
                resultado.ingresos_capital += valor
                resultado.retenciones_capital += retencion
            elif tipo == "no_laboral":
                resultado.ingresos_no_laborales += valor
                resultado.retenciones_no_laborales += retencion
            elif tipo == "pension":
                resultado.ingresos_pensiones += valor
                resultado.retenciones_pensiones += retencion
                resultado.tiene_pension = True
            elif tipo == "dividendo":
                resultado.dividendos += valor
                resultado.retenciones_dividendos += retencion
                resultado.tiene_dividendos = True
            elif tipo == "ganancia_ocasional":
                resultado.ganancias_ocasionales += valor
            elif tipo == "patrimonio_cuenta":
                resultado.saldos_cuentas += valor
            elif tipo == "no_constitutivo":
                resultado.ingresos_no_const += valor
            elif tipo == "gmf":
                resultado.gmf_pagado += valor
            elif tipo == "consignacion":
                resultado.total_consignaciones += valor

            # Registrar pagador/entidad
            if nombre and valor > 0 and tipo not in (
                "patrimonio_cuenta", "gmf", "consignacion", "no_constitutivo"
            ):
                self._registrar_pagador(resultado, nombre, nit, valor, retencion, tipo)

    def _clasificar_tipo(
        self,
        nombre: str,
        nit: str,
        valor: float,
        concepto: str,
        formato: str,
        hoja: str,
    ) -> str:
        """
        Clasifica una fila de la exogena en el tipo de ingreso del 210.
        El orden importa: los mas especificos primero.
        """
        hoja_lower  = hoja.lower()
        formato_num = re.sub(r"[^\d]", "", formato)

        # Por nombre de hoja / formato
        if formato_num == "220" or "220" in hoja_lower:
            return "trabajo_laboral"

        if formato_num in ("2276", "1001") or any(
            k in hoja_lower for k in ("honorario", "independiente", "servicio")
        ):
            return "trabajo_no_laboral"

        if formato_num == "2278" or any(
            k in hoja_lower for k in ("rendimiento", "interes", "financiero")
        ):
            return "capital"

        if formato_num == "1012" or any(k in hoja_lower for k in ("cuenta", "saldo")):
            return "patrimonio_cuenta"

        if formato_num == "1010" or "dividend" in hoja_lower:
            return "dividendo"

        if "1115" in concepto or "gmf" in hoja_lower:
            return "gmf"

        if "consignaci" in hoja_lower:
            return "consignacion"

        # Por nombre de entidad
        if self._es_fondo_pension(nombre):
            return "pension"

        if self._es_entidad_financiera(nombre):
            # Si viene de entidad financiera y parece rendimiento → capital
            if any(k in nombre for k in ["RENDIMIENTO", "INTERES", "CDT", "FIDUCIARIA"]):
                return "capital"
            # Si parece saldo de cuenta
            if any(k in nombre for k in ["CUENTA", "AHORRO", "CORRIENTE"]):
                return "patrimonio_cuenta"
            return "capital"  # por defecto rendimiento

        # Por concepto DIAN
        if concepto in _CONCEPTOS_PENSION:
            return "pension"
        if concepto in _CONCEPTOS_TRABAJO:
            return "trabajo_laboral"
        if concepto in _CONCEPTOS_INDEPENDIENTE:
            return "trabajo_no_laboral"
        if concepto in _CONCEPTOS_RENDIMIENTOS:
            return "capital"
        if concepto in _CONCEPTOS_NO_CONSTITUTIVOS:
            return "no_constitutivo"
        if concepto in _CONCEPTOS_GMF:
            return "gmf"

        # Default: renta no laboral (residual, como indica el 210)
        return "no_laboral"

    def _registrar_pagador(
        self,
        resultado: ResumenExogena,
        nombre: str,
        nit: str,
        valor: float,
        retencion: float,
        tipo: str,
    ) -> None:
        """Agrupa pagadores — si ya existe suma los valores."""
        clave = nit or nombre
        for p in resultado.pagadores:
            if p["clave"] == clave:
                p["valor"] += valor
                p["retencion"] += retencion
                return

        entrada = {
            "clave": clave,
            "nombre": nombre,
            "nit": nit,
            "valor": valor,
            "retencion": retencion,
            "tipo": tipo,
        }
        resultado.pagadores.append(entrada)

        # Separar entidades financieras en su propia lista
        if self._es_entidad_financiera(nombre):
            ya_registrada = any(
                e["nombre"] == nombre for e in resultado.entidades_financieras
            )
            if not ya_registrada:
                resultado.entidades_financieras.append({"nombre": nombre, "nit": nit})

    def _calcular_totales(self, resultado: ResumenExogena) -> None:
        """Calcula el total de ingresos brutos para el analisis de obligacion."""
        resultado.total_ingresos_brutos = (
            resultado.ingresos_laborales
            + resultado.ingresos_no_laborales_trabajo
            + resultado.ingresos_capital
            + resultado.ingresos_no_laborales
            + resultado.ingresos_pensiones
            + resultado.dividendos
        )
        resultado.total_retenciones = (
            resultado.retenciones_trabajo
            + resultado.retenciones_capital
            + resultado.retenciones_no_laborales
            + resultado.retenciones_pensiones
            + resultado.retenciones_dividendos
        )
