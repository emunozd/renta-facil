"""
rag/vector_store.py  +  rag/service.py
VectorStore: wrapper sobre ChromaDB (principio L — reemplazable por FAISS).
RAGService: orquesta indexacion y recuperacion de contexto del 210.
"""
import logging
import os
from typing import Optional

from interfaces.base import IVectorStore, IRAGService, ChunkRAG
from config.settings import Settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# VectorStore — ChromaDB
# ─────────────────────────────────────────────────────────────
class ChromaVectorStore(IVectorStore):
    """
    Wrapper sobre ChromaDB con embeddings multilingues.
    Si se cambia a FAISS, solo se reemplaza esta clase; el resto no cambia.
    """

    _COLLECTION_NAME = "formulario_210"

    def __init__(self, persist_dir: str, embedding_model: str) -> None:
        self._persist_dir     = persist_dir
        self._embedding_model = embedding_model
        self._client     = None
        self._collection = None
        self._ef         = None

    def _inicializar(self) -> None:
        if self._client is not None:
            return
        try:
            import chromadb
            from chromadb.utils import embedding_functions as ef_utils

            os.makedirs(self._persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._ef = ef_utils.SentenceTransformerEmbeddingFunction(
                model_name=self._embedding_model
            )
            self._collection = self._client.get_or_create_collection(
                name=self._COLLECTION_NAME,
                embedding_function=self._ef,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"ChromaDB inicializado en {self._persist_dir}, "
                f"documentos: {self._collection.count()}"
            )
        except ImportError as e:
            raise RuntimeError(
                f"Dependencia faltante: {e}. "
                "Ejecuta: pip install chromadb sentence-transformers"
            )

    def insertar(self, chunks: list[ChunkRAG]) -> None:
        self._inicializar()
        if not chunks:
            return

        ids        = [c.id for c in chunks]
        textos     = [c.texto for c in chunks]
        metadatas  = [
            {
                "seccion":  c.seccion,
                "casillas": str(c.casillas),
            }
            for c in chunks
        ]

        # ChromaDB acepta max 5461 documentos por batch
        batch = 500
        for i in range(0, len(chunks), batch):
            self._collection.add(
                ids=ids[i:i+batch],
                documents=textos[i:i+batch],
                metadatas=metadatas[i:i+batch],
            )
        logger.info(f"Insertados {len(chunks)} chunks en ChromaDB.")

    def buscar(self, query: str, k: int) -> list[ChunkRAG]:
        self._inicializar()
        if self._collection.count() == 0:
            return []

        resultados = self._collection.query(
            query_texts=[query],
            n_results=min(k, self._collection.count()),
        )

        chunks = []
        for i, doc in enumerate(resultados["documents"][0]):
            meta  = resultados["metadatas"][0][i]
            dist  = resultados["distances"][0][i]
            score = 1.0 - dist  # cosine distance → similarity

            casillas_str = meta.get("casillas", "[]")
            try:
                import ast
                casillas = ast.literal_eval(casillas_str)
            except Exception:
                casillas = []

            chunks.append(ChunkRAG(
                id=resultados["ids"][0][i],
                texto=doc,
                seccion=meta.get("seccion", "General"),
                casillas=casillas,
                score=score,
            ))

        return chunks

    def limpiar(self) -> None:
        self._inicializar()
        try:
            self._client.delete_collection(self._COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self._COLLECTION_NAME,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB limpiado.")

    def contar(self) -> int:
        try:
            self._inicializar()
            return self._collection.count()
        except Exception:
            return 0

    def guardar_hash(self, hash_val: str) -> None:
        """Guarda el hash del PDF como metadata de la coleccion ChromaDB."""
        self._inicializar()
        # ChromaDB no permite modificar metadata de coleccion directamente,
        # pero si podemos guardar un documento especial con id reservado
        try:
            self._collection.upsert(
                ids=["__pdf_hash__"],
                documents=[hash_val],
                metadatas=[{"tipo": "hash_control"}],
            )
        except Exception as e:
            logger.warning(f"No se pudo guardar hash en ChromaDB: {e}")

    def obtener_hash(self) -> str | None:
        """Recupera el hash guardado del PDF desde ChromaDB."""
        self._inicializar()
        try:
            resultado = self._collection.get(ids=["__pdf_hash__"])
            if resultado and resultado["documents"]:
                return resultado["documents"][0]
        except Exception:
            pass
        return None

    def limpiar_preservando_interfaz(self) -> None:
        """Alias de limpiar() — elimina todos los documentos incluido el hash."""
        self.limpiar()


# ─────────────────────────────────────────────────────────────
# RAGService — orquesta indexacion + recuperacion
# ─────────────────────────────────────────────────────────────
class RAGService(IRAGService):
    """
    Servicio principal del RAG.
    - Delega la indexacion al Indexer.
    - Delega el almacenamiento al VectorStore.
    - Expone recuperar_contexto() al resto del sistema.
    """

    def __init__(
        self,
        vector_store: IVectorStore,
        indexer,           # Indexer (evitar importacion circular)
        top_k: int = 5,
    ) -> None:
        self._store   = vector_store
        self._indexer = indexer
        self._top_k   = top_k

    def esta_indexado(self) -> bool:
        return self._store.contar() > 0

    def reindexar(self) -> None:
        logger.info("Re-indexando Formulario 210...")
        self._indexer.indexar()
        logger.info(
            f"Re-indexacion completa. "
            f"Chunks en ChromaDB: {self._store.contar()}"
        )

    def recuperar_contexto(
        self,
        query: str,
        secciones: Optional[list] = None,
    ) -> list[ChunkRAG]:
        """
        Recupera los chunks mas relevantes del 210 para la query dada.
        Si se pasan secciones especificas, prioriza chunks de esas secciones.
        """
        if not self.esta_indexado():
            logger.warning("RAG no indexado, retornando contexto vacio.")
            return []

        # Busqueda semantica base
        chunks = self._store.buscar(query, k=self._top_k * 2)

        # Filtrar y priorizar por seccion si se especifica
        if secciones:
            prioritarios = [
                c for c in chunks
                if any(s.lower() in c.seccion.lower() for s in secciones)
            ]
            otros = [c for c in chunks if c not in prioritarios]
            chunks = (prioritarios + otros)[: self._top_k]
        else:
            chunks = chunks[: self._top_k]

        logger.debug(
            f"RAG recupero {len(chunks)} chunks para query: '{query[:60]}...'"
        )
        return chunks

    def recuperar_para_casillas(self, casillas: list[int]) -> list[ChunkRAG]:
        """Recupera chunks especificamente para un conjunto de casillas."""
        query = f"casillas {' '.join(str(c) for c in casillas)} instrucciones"
        return self.recuperar_contexto(query)