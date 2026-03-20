"""
rag/indexer.py
Divide el PDF del Formulario 210 en chunks semanticos y los indexa.
Detecta automaticamente si el PDF cambio (hash SHA-256) y re-indexa.
Principio O: anadir nuevo PDF = cambiar el archivo, no el codigo.
"""
import hashlib
import json
import logging
import os
import re
from typing import Optional
import pdfplumber

from interfaces.base import IVectorStore, ChunkRAG

logger = logging.getLogger(__name__)

# Archivo donde se guarda el hash del PDF para detectar cambios
_HASH_FILE = ".pdf_hash.json"

# Secciones del Formulario 210 con sus casillas de referencia
# Se usan para etiquetar cada chunk y mejorar la recuperacion
_SECCIONES_210 = [
    {"patron": r"patrimonio",
     "nombre": "Patrimonio", "casillas": [29, 30, 31]},
    {"patron": r"rentas de trabajo(?!\s+que no)",
     "nombre": "Rentas de Trabajo (laborales)", "casillas": list(range(32, 43))},
    {"patron": r"rentas de trabajo que no provengan",
     "nombre": "Rentas de Trabajo no laborales", "casillas": list(range(43, 58))},
    {"patron": r"rentas de capital",
     "nombre": "Rentas de Capital", "casillas": list(range(58, 74))},
    {"patron": r"rentas no laborales",
     "nombre": "Rentas No Laborales", "casillas": list(range(74, 91))},
    {"patron": r"c[eé]dula de pensiones|rentas de pensiones",
     "nombre": "Cedula de Pensiones", "casillas": list(range(91, 100))},
    {"patron": r"c[eé]dula de dividendos",
     "nombre": "Cedula de Dividendos", "casillas": list(range(100, 109))},
    {"patron": r"ganancias ocasionales",
     "nombre": "Ganancias Ocasionales", "casillas": list(range(109, 120))},
    {"patron": r"descuentos tributarios|impuesto neto",
     "nombre": "Descuentos y Liquidacion", "casillas": list(range(119, 135))},
    {"patron": r"retenciones",
     "nombre": "Retenciones en la Fuente", "casillas": list(range(80, 91))},
    {"patron": r"anticipo",
     "nombre": "Anticipo Impuesto", "casillas": [137, 138, 139, 140, 141]},
    {"patron": r"rentas exentas.*trabajo|exenta.*trabajo",
     "nombre": "Rentas Exentas Laborales", "casillas": [35, 36, 37, 41]},
    {"patron": r"deducciones imputables.*trabajo",
     "nombre": "Deducciones Trabajo", "casillas": [38, 39, 40]},
    {"patron": r"obligad[ao]|debe declarar|no obliga",
     "nombre": "Obligacion de Declarar", "casillas": []},
    {"patron": r"datos del declarante",
     "nombre": "Datos del Declarante", "casillas": list(range(1, 28))},
]


class Indexer:
    """
    Lee el PDF del Formulario 210, lo divide en chunks inteligentes
    (respetando la estructura de casillas y secciones), genera embeddings
    y los almacena en ChromaDB.
    """

    def __init__(
        self,
        vector_store: IVectorStore,
        pdf_path: str,
        chunk_size: int = 600,
        chunk_overlap: int = 80,
    ) -> None:
        self._store   = vector_store
        self._pdf_path = pdf_path
        self._chunk_size    = chunk_size
        self._chunk_overlap = chunk_overlap
        self._hash_file = os.path.join(
            os.path.dirname(pdf_path), _HASH_FILE
        )

    # ------------------------------------------------------------------
    def necesita_reindexar(self) -> bool:
        """True si el PDF cambio desde la ultima indexacion o no esta indexado."""
        if self._store.contar() == 0:
            logger.info("ChromaDB vacio, se requiere indexacion.")
            return True

        hash_actual = self._calcular_hash()
        hash_guardado = self._cargar_hash_guardado()

        if hash_actual != hash_guardado:
            logger.info("PDF cambio (hash diferente), se requiere re-indexacion.")
            return True

        return False

    def indexar(self) -> None:
        """Indexa el PDF del Formulario 210 desde cero."""
        if not os.path.exists(self._pdf_path):
            raise FileNotFoundError(
                f"No se encontro el Formulario 210 en: {self._pdf_path}\n"
                "Coloca el archivo en data/formulario_210.pdf"
            )

        logger.info(f"Iniciando indexacion de: {self._pdf_path}")

        # Limpiar indexacion anterior
        self._store.limpiar()

        # Extraer texto completo
        texto_completo = self._extraer_texto_pdf()
        if not texto_completo.strip():
            raise ValueError(
                "No se pudo extraer texto del PDF. "
                "Verifica que sea un PDF con texto (no escaneado)."
            )

        # Dividir en chunks preservando estructura del 210
        chunks = self._dividir_en_chunks(texto_completo)
        logger.info(f"Generados {len(chunks)} chunks del Formulario 210")

        # Insertar en ChromaDB
        self._store.insertar(chunks)

        # Guardar hash para deteccion de cambios futuros
        self._guardar_hash(self._calcular_hash())

        logger.info("Indexacion completada exitosamente.")

    # ------------------------------------------------------------------
    def _extraer_texto_pdf(self) -> str:
        """Extrae el texto completo del PDF preservando estructura."""
        partes = []
        try:
            with pdfplumber.open(self._pdf_path) as pdf:
                for i, pagina in enumerate(pdf.pages):
                    texto = pagina.extract_text()
                    if texto:
                        partes.append(f"[PAGINA {i+1}]\n{texto}")
        except Exception as e:
            raise RuntimeError(f"Error leyendo PDF: {e}")

        return "\n\n".join(partes)

    def _dividir_en_chunks(self, texto: str) -> list[ChunkRAG]:
        """
        Divide el texto en chunks respetando la estructura del Formulario 210.
        Estrategia:
        1. Primero intenta dividir por casilla (cada casilla es un chunk)
        2. Si el texto entre casillas es muy largo, lo subdivide por oraciones
        3. Etiqueta cada chunk con la seccion y casillas que contiene
        """
        chunks = []
        chunk_id = 0

        # Patron para detectar inicio de descripcion de una casilla
        # Ejemplos: "29. Total patrimonio bruto:" o "32. Ingresos brutos"
        patron_casilla = re.compile(
            r"(\d{2,3})\.\s+([A-ZÁÉÍÓÚÑ][^\n]{5,80}(?:\n(?!\d{2,3}\.)[^\n]*){0,5})",
            re.IGNORECASE
        )

        posiciones = []
        for match in patron_casilla.finditer(texto):
            num_casilla = int(match.group(1))
            if 1 <= num_casilla <= 200:  # rango valido de casillas
                posiciones.append((match.start(), num_casilla, match.group(0)))

        if len(posiciones) < 10:
            # El PDF no tiene estructura de casillas detectables —
            # dividir por tamano con solapamiento
            logger.warning(
                "Pocos patrones de casilla detectados, dividiendo por tamano."
            )
            return self._dividir_por_tamano(texto)

        # Dividir por casilla
        for i, (inicio, num_casilla, titulo) in enumerate(posiciones):
            fin = posiciones[i + 1][0] if i + 1 < len(posiciones) else len(texto)
            fragmento = texto[inicio:fin].strip()

            if not fragmento:
                continue

            # Si el fragmento es muy largo, subdividirlo
            sub_chunks = self._subdividir_si_largo(fragmento, num_casilla)

            for j, sub in enumerate(sub_chunks):
                seccion = self._detectar_seccion(sub, num_casilla)
                chunks.append(ChunkRAG(
                    id=f"casilla_{num_casilla}_{j}",
                    texto=sub,
                    seccion=seccion,
                    casillas=[num_casilla],
                    score=0.0,
                ))
                chunk_id += 1

        # Agregar chunks de contexto general (intro, obligacion de declarar, etc.)
        fragmentos_intro = self._extraer_secciones_especiales(texto)
        for k, (texto_frag, seccion, casillas) in enumerate(fragmentos_intro):
            chunks.append(ChunkRAG(
                id=f"intro_{k}",
                texto=texto_frag,
                seccion=seccion,
                casillas=casillas,
                score=0.0,
            ))

        return chunks

    def _subdividir_si_largo(self, texto: str, casilla: int) -> list[str]:
        """Si el texto de una casilla es muy largo, lo parte en sub-chunks."""
        palabras = texto.split()
        if len(palabras) <= self._chunk_size:
            return [texto]

        subs = []
        inicio = 0
        while inicio < len(palabras):
            fin = min(inicio + self._chunk_size, len(palabras))
            subs.append(" ".join(palabras[inicio:fin]))
            inicio = fin - self._chunk_overlap
            if inicio >= len(palabras) - self._chunk_overlap:
                break
        return subs

    def _dividir_por_tamano(self, texto: str) -> list[ChunkRAG]:
        """Fallback: divide por tamano con solapamiento."""
        palabras = texto.split()
        chunks   = []
        inicio   = 0
        idx      = 0

        while inicio < len(palabras):
            fin     = min(inicio + self._chunk_size, len(palabras))
            fragmento = " ".join(palabras[inicio:fin])
            seccion = self._detectar_seccion(fragmento.lower(), 0)

            chunks.append(ChunkRAG(
                id=f"chunk_{idx}",
                texto=fragmento,
                seccion=seccion,
                casillas=[],
                score=0.0,
            ))
            idx   += 1
            inicio = fin - self._chunk_overlap
            if inicio >= len(palabras) - self._chunk_overlap:
                break

        return chunks

    def _detectar_seccion(self, texto: str, num_casilla: int) -> str:
        """Detecta a que seccion del 210 pertenece un chunk."""
        texto_lower = texto.lower() if not texto.islower() else texto

        for sec in _SECCIONES_210:
            if re.search(sec["patron"], texto_lower):
                return sec["nombre"]
            if num_casilla and sec["casillas"]:
                if num_casilla in sec["casillas"]:
                    return sec["nombre"]

        return "General"

    def _extraer_secciones_especiales(self, texto: str) -> list[tuple]:
        """Extrae partes especiales del PDF que no siguen el patron de casillas."""
        resultados = []
        texto_lower = texto.lower()

        # Introduccion / instrucciones generales
        idx_intro = texto_lower.find("este instructivo")
        if idx_intro >= 0:
            fragmento = texto[max(0, idx_intro-100):idx_intro+800]
            resultados.append((fragmento, "Introduccion e Instrucciones Generales", []))

        # Limites rentas exentas y deducciones
        idx_limite = texto_lower.find("cuarenta por ciento")
        if idx_limite >= 0:
            fragmento = texto[max(0, idx_limite-200):idx_limite+600]
            resultados.append((
                fragmento,
                "Limites Rentas Exentas y Deducciones (40%, 1340 UVT)",
                [40, 41, 53, 69],
            ))

        # Tabla de tarifas impuesto
        idx_tarifa = texto_lower.find("tabla de impuesto")
        if idx_tarifa < 0:
            idx_tarifa = texto_lower.find("tarifa marginal")
        if idx_tarifa >= 0:
            fragmento = texto[max(0, idx_tarifa-100):idx_tarifa+600]
            resultados.append((fragmento, "Tabla Tarifas Impuesto Renta", [125]))

        return resultados

    # ------------------------------------------------------------------
    def _calcular_hash(self) -> str:
        """Calcula SHA-256 del PDF."""
        sha256 = hashlib.sha256()
        with open(self._pdf_path, "rb") as f:
            for bloque in iter(lambda: f.read(65536), b""):
                sha256.update(bloque)
        return sha256.hexdigest()

    def _cargar_hash_guardado(self) -> Optional[str]:
        if os.path.exists(self._hash_file):
            try:
                with open(self._hash_file) as f:
                    return json.load(f).get("hash")
            except Exception:
                pass
        return None

    def _guardar_hash(self, hash_val: str) -> None:
        with open(self._hash_file, "w") as f:
            json.dump({"hash": hash_val, "pdf": self._pdf_path}, f)
