"""
interfaces/base.py
Contratos (interfaces) de todos los servicios.
Los modulos dependen de estas abstracciones, nunca de concretos.
Principio D de SOLID.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional
import time
from dataclasses import dataclass, field


# ------------------------------------------------------------
# Modelos de dominio
# ------------------------------------------------------------

@dataclass
class ResumenExogena:
    """Resultado del parseo del Excel de exogena."""
    nit_usuario: str = ""
    nombre_usuario: str = ""

    # Ingresos detectados por tipo
    ingresos_laborales: float = 0.0          # formato 220 → casilla 32
    ingresos_no_laborales_trabajo: float = 0.0  # formato 2276/1001 → casilla 43
    ingresos_capital: float = 0.0            # rendimientos financieros → casilla 58
    ingresos_no_laborales: float = 0.0       # otros → casilla 74
    ingresos_pensiones: float = 0.0          # pensiones → cedula 91
    dividendos: float = 0.0                  # dividendos → cedula 100
    ganancias_ocasionales: float = 0.0       # venta bienes → cedula 109

    # Retenciones detectadas
    retenciones_trabajo: float = 0.0
    retenciones_capital: float = 0.0
    retenciones_no_laborales: float = 0.0
    retenciones_pensiones: float = 0.0
    retenciones_dividendos: float = 0.0

    # Patrimonio
    saldos_cuentas: float = 0.0
    inversiones: float = 0.0
    otros_activos: float = 0.0

    # Pagadores / entidades detectados
    pagadores: list = field(default_factory=list)  # [{nombre, nit, monto, tipo_formato}]
    entidades_financieras: list = field(default_factory=list)
    tiene_pension: bool = False
    tiene_dividendos: bool = False

    # Consignaciones / compras (para evaluar obligacion)
    total_consignaciones: float = 0.0
    total_compras: float = 0.0

    # Ingresos no constitutivos detectados
    ingresos_no_const: float = 0.0

    # GMF reportado por bancos
    gmf_pagado: float = 0.0

    # Errores de parseo (no fatales)
    advertencias: list = field(default_factory=list)


@dataclass
class AnalisisObligacion:
    """Resultado del analisis de si el usuario debe declarar."""
    debe_declarar: bool
    razones_obliga: list = field(default_factory=list)
    razones_no_obliga: list = field(default_factory=list)
    puede_beneficiarse_voluntaria: bool = False
    retenciones_recuperables: float = 0.0
    detalle: str = ""


@dataclass
class SesionUsuario:
    """Estado completo de la conversacion de un usuario."""
    chat_id: int
    estado: str                        # EstadoBot.*
    resumen_exogena: Optional[Any] = None
    analisis_obligacion: Optional[Any] = None
    datos_confirmados: dict = field(default_factory=dict)
    documentos_recibidos: list = field(default_factory=list)   # archivos del ZIP
    documentos_pendientes: list = field(default_factory=list)  # lo que aun se pide
    borrador_210: dict = field(default_factory=dict)           # campos calculados
    historial_mensajes: list = field(default_factory=list)     # para contexto IA
    paso_actual: int = 0
    ultima_pregunta: str = ""
    ultima_actividad: float = field(default_factory=time.time)  # timestamp Unix


@dataclass
class ChunkRAG:
    """Un fragmento del Formulario 210 recuperado por el RAG."""
    id: str
    texto: str
    seccion: str          # ej: "Rentas de Trabajo", "Patrimonio"
    casillas: list        # ej: [32, 33, 34]
    score: float = 0.0


@dataclass
class RespuestaIA:
    """Respuesta generada por el LLM."""
    texto: str
    tokens_usados: int = 0
    error: Optional[str] = None


# ------------------------------------------------------------
# Interfaces de servicios
# ------------------------------------------------------------

class IExogenaParser(ABC):
    @abstractmethod
    def parsear(self, ruta_archivo: str) -> ResumenExogena:
        """Lee el Excel de exogena y retorna un resumen estructurado."""
        ...


class IVisionParser(ABC):
    @abstractmethod
    def extraer(self, ruta_archivo: str, tipo_documento: str) -> dict:
        """
        Convierte un archivo a imagen y usa el LLM para extraer valores.
        Retorna dict con los campos numericos del documento.
        """
        ...

    @abstractmethod
    def extraer_desde_bytes(self, contenido: bytes, tipo_documento: str, ext: str) -> dict:
        """Version que recibe bytes directamente (desde el ZIP)."""
        ...


class IZipParser(ABC):
    @abstractmethod
    def parsear(self, ruta_zip: str) -> dict:
        """
        Descomprime y analiza cada archivo del ZIP.
        Retorna dict: {nombre_entidad: {tipo, datos, campos_210}}
        """
        ...


class IRAGService(ABC):
    @abstractmethod
    def recuperar_contexto(
        self, query: str, secciones: Optional[list] = None
    ) -> list[ChunkRAG]:
        """Busca los chunks mas relevantes del Formulario 210."""
        ...

    @abstractmethod
    def esta_indexado(self) -> bool:
        """Verifica si el PDF ya fue indexado en ChromaDB."""
        ...

    @abstractmethod
    def reindexar(self) -> None:
        """Re-indexa el PDF desde cero."""
        ...


class IVectorStore(ABC):
    @abstractmethod
    def insertar(self, chunks: list[ChunkRAG]) -> None: ...

    @abstractmethod
    def buscar(self, query: str, k: int) -> list[ChunkRAG]: ...

    @abstractmethod
    def limpiar(self) -> None: ...

    @abstractmethod
    def contar(self) -> int: ...


class IAIClient(ABC):
    @abstractmethod
    def completar(
        self,
        mensajes: list[dict],
        system_prompt: str,
        max_tokens: int,
    ) -> RespuestaIA:
        """Llama al endpoint del LLM y retorna la respuesta."""
        ...


class IPromptBuilder(ABC):
    @abstractmethod
    def construir_system_prompt(
        self,
        chunks_210: list[ChunkRAG],
        resumen_exogena: Optional[ResumenExogena],
        contexto_extra: str = "",
    ) -> str:
        """
        Arma el system prompt con:
        - Rol de experto tributario
        - Chunks relevantes del 210
        - Datos de la exogena del usuario
        - Instrucciones de comportamiento
        """
        ...

    @abstractmethod
    def construir_prompt_analisis(self, resumen: ResumenExogena) -> str:
        """Prompt para analizar si el usuario debe declarar."""
        ...

    @abstractmethod
    def construir_prompt_campo(
        self,
        casillas: list[int],
        datos_disponibles: dict,
        sesion: SesionUsuario,
    ) -> str:
        """Prompt para preguntar / calcular campos especificos del 210."""
        ...


class ISessionRepo(ABC):
    @abstractmethod
    def obtener(self, chat_id: int) -> Optional[SesionUsuario]: ...

    @abstractmethod
    def guardar(self, sesion: SesionUsuario) -> None: ...

    @abstractmethod
    def eliminar(self, chat_id: int) -> None: ...


class IFormGenerator(ABC):
    @abstractmethod
    def generar_excel(self, borrador: dict, ruta_salida: str) -> str:
        """Genera Excel con campos del 210 prellenados y columna de explicacion."""
        ...

    @abstractmethod
    def generar_resumen_pdf(self, borrador: dict, ruta_salida: str) -> str:
        """Genera PDF con resumen del borrador para el usuario."""
        ...