"""
config/settings.py
Variables de configuracion del proyecto. Carga desde .env
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Telegram
    telegram_token: str

    # IA local (kingsrow_ai_base.py)
    ai_base_url: str
    ai_api_key: str
    ai_model: str
    ai_max_tokens: int
    ai_timeout_seconds: int

    # RAG
    chroma_persist_dir: str
    pdf_formulario_path: str
    embedding_model: str
    rag_top_k: int             # cuantos chunks recuperar por consulta
    rag_chunk_size: int        # tokens aprox por chunk
    rag_chunk_overlap: int

    # Watcher
    pdf_watch_interval_seconds: int

    # SQLite
    db_path: str

    # Limites de archivos
    max_file_size_mb: int

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("TELEGRAM_TOKEN")
        if not token:
            raise ValueError(
                "TELEGRAM_TOKEN no configurado. "
                "Crea un archivo .env con TELEGRAM_TOKEN=tu_token"
            )
        return cls(
            telegram_token=token,
            ai_base_url=os.getenv("AI_BASE_URL", "http://localhost:8181"),
            ai_api_key=os.getenv("AI_API_KEY", ""),
            ai_model=os.getenv("AI_MODEL", "mlx-community/Qwen3.5-35B-A3B-4bit"),
            ai_max_tokens=int(os.getenv("AI_MAX_TOKENS", "4096")),
            ai_timeout_seconds=int(os.getenv("AI_TIMEOUT_SECONDS", "120")),
            chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR", "/var/lib/renta-facil/chroma"),
            pdf_formulario_path=os.getenv(
                "PDF_FORMULARIO_PATH", "/var/lib/renta-facil/formulario_210.pdf"
            ),
            embedding_model=os.getenv(
                "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            ),
            rag_top_k=int(os.getenv("RAG_TOP_K", "5")),
            rag_chunk_size=int(os.getenv("RAG_CHUNK_SIZE", "600")),
            rag_chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP", "80")),
            pdf_watch_interval_seconds=int(os.getenv("PDF_WATCH_INTERVAL", "300")),
            db_path=os.getenv("DB_PATH", "/var/lib/renta-facil/sesiones.db"),
            max_file_size_mb=int(os.getenv("MAX_FILE_SIZE_MB", "20")),
        )