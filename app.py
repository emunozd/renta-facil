"""
app.py
Contenedor de dependencias (DI).
Instancia todos los servicios y los conecta.
Los modulos NO se importan unos a otros directamente — todo pasa por aqui.
Principio D de SOLID.
"""
import logging

from config.settings import Settings
from interfaces.base import (
    IExogenaParser, IZipParser, IRAGService,
    IAIClient, IPromptBuilder, ISessionRepo, IFormGenerator,
)

from parsers.excel_parser  import ExogenaParser
from parsers.vision_parser import VisionParser
from parsers.zip_parser    import ZipParser
from rag.indexer           import Indexer
from rag.vector_store      import ChromaVectorStore, RAGService
from ai.client             import LLMClient, PromptBuilder210
from bot.session_repo      import SQLiteSessionRepo
from bot.handler           import BotHandler
from generators.form_210   import FormGenerator210
from watchers.pdf_watcher  import PDFWatcher

logger = logging.getLogger(__name__)


class AppContainer:
    """
    Punto central de composicion.
    Todos los servicios se crean aqui y se inyectan a quienes los necesitan.
    Para cambiar una implementacion, solo se cambia la linea de instanciacion
    aqui — nada mas.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._construir()

    def _construir(self) -> None:
        s = self._settings
        logger.info("Construyendo contenedor de dependencias...")

        # --- Parsers ---
        self.exogena_parser: IExogenaParser = ExogenaParser()

        # VisionParser se construye primero — ZipParser lo recibe inyectado
        # Usa /v1/messages (Anthropic-compatible) porque ese endpoint soporta imagenes
        vision_parser = VisionParser(
            base_url        = s.ai_base_url,
            api_key         = s.ai_api_key,
            timeout_seconds = s.ai_timeout_seconds,
        )

        # ZipParser recibe el VisionParser como dependencia
        # Si vision_parser falla, ZipParser cae al fallback de texto automaticamente
        self.zip_parser: IZipParser = ZipParser(vision_parser=vision_parser)

        # --- RAG ---
        vector_store = ChromaVectorStore(
            persist_dir     = s.chroma_persist_dir,
            embedding_model = s.embedding_model,
        )
        indexer = Indexer(
            vector_store  = vector_store,
            pdf_path      = s.pdf_formulario_path,
            chunk_size    = s.rag_chunk_size,
            chunk_overlap = s.rag_chunk_overlap,
        )
        self.rag_service: IRAGService = RAGService(
            vector_store = vector_store,
            indexer      = indexer,
            top_k        = s.rag_top_k,
        )

        # --- IA ---
        self.ai_client: IAIClient = LLMClient(
            base_url        = s.ai_base_url,
            api_key         = s.ai_api_key,
            model           = s.ai_model,
            timeout_seconds = s.ai_timeout_seconds,
        )
        self.prompt_builder: IPromptBuilder = PromptBuilder210()

        # --- Persistencia ---
        self.session_repo: ISessionRepo = SQLiteSessionRepo(
            db_path = s.db_path,
        )

        # --- Generador ---
        self.form_generator: IFormGenerator = FormGenerator210()

        # --- Watcher ---
        self.pdf_watcher = PDFWatcher(
            rag_service        = self.rag_service,
            intervalo_segundos = s.pdf_watch_interval_seconds,
        )

        # --- Bot handler ---
        self.bot_handler = BotHandler(
            settings       = s,
            exogena_parser = self.exogena_parser,
            zip_parser     = self.zip_parser,
            rag_service    = self.rag_service,
            ai_client      = self.ai_client,
            prompt_builder = self.prompt_builder,
            session_repo   = self.session_repo,
            form_generator = self.form_generator,
        )

        logger.info("Contenedor construido correctamente.")
