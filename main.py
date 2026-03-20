"""
main.py
Punto de entrada unico del proyecto.
Responsabilidades:
  1. Cargar configuracion
  2. Construir el contenedor de dependencias
  3. Arrancar el PDFWatcher en background
  4. Arrancar el bot de Telegram (event loop asyncio)

Para arrancar:
    source ~/mlx-env/bin/activate   # o tu venv
    python main.py
"""
import asyncio
import logging
import os
import sys

# ─── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
# Silenciar librerias ruidosas
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("=" * 60)
    logger.info("  Renta Bot Colombia — Formulario 210")
    from config.constants import ANNO_GRAVABLE, UVT
    logger.info(f"  Ano gravable {ANNO_GRAVABLE} | UVT: ${UVT:,}")
    logger.info("=" * 60)

    # 1. Configuracion
    try:
        from config.settings import Settings
        settings = Settings.from_env()
        logger.info(f"Configuracion cargada. AI: {settings.ai_base_url}")
    except ValueError as e:
        logger.error(f"Error de configuracion: {e}")
        logger.error(
            "Crea un archivo .env en el directorio del proyecto con:\n"
            "  TELEGRAM_TOKEN=tu_token_de_botfather\n"
            "  AI_BASE_URL=http://localhost:8181  (donde corre kingsrow_ai_base.py)\n"
        )
        sys.exit(1)

    # Crear directorios necesarios
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    os.makedirs(settings.chroma_persist_dir, exist_ok=True)
    os.makedirs(os.path.dirname(settings.pdf_formulario_path) or ".", exist_ok=True)

    # Verificar que el PDF existe
    if not os.path.exists(settings.pdf_formulario_path):
        logger.warning(
            f"PDF no encontrado en: {settings.pdf_formulario_path}\n"
            "El bot funcionara pero el RAG no podra recuperar contexto del 210 "
            "hasta que coloques el archivo. Descargalo de:\n"
            "https://www.dian.gov.co/atencionciudadano/formulariosinstructivos/"
            "Formularios/2024/Formulario_210_2024.pdf"
        )

    # 2. Contenedor de dependencias
    from app import AppContainer
    container = AppContainer(settings)

    # 3. PDFWatcher en background (thread daemon)
    container.pdf_watcher.iniciar()

    # 4. Construir y arrancar el bot de Telegram
    logger.info("Construyendo aplicacion Telegram...")
    application = container.bot_handler.construir_aplicacion()

    logger.info("Bot iniciado. Esperando mensajes...")
    logger.info("Para detener: Ctrl+C")

    # run_polling maneja el event loop de asyncio internamente
    application.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,     # ignorar mensajes acumulados mientras estuvo apagado
        close_loop=False,
    )


if __name__ == "__main__":
    main()
