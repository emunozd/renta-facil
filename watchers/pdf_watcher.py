"""
watchers/pdf_watcher.py
Monitorea el directorio data/ en un thread separado.
Si detecta que el PDF del Formulario 210 cambio (hash SHA-256 diferente),
dispara la re-indexacion automaticamente sin interrumpir el bot.
Principio O: cambias el PDF → el sistema se adapta solo.
"""
import logging
import threading
import time

from interfaces.base import IRAGService

logger = logging.getLogger(__name__)


class PDFWatcher:
    """
    Corre en un thread daemon. Cada N segundos verifica si el PDF
    del Formulario 210 cambio. Si cambio, llama a rag_service.reindexar().

    El thread es daemon: se detiene automaticamente cuando el proceso principal termina.
    """

    def __init__(
        self,
        rag_service: IRAGService,
        intervalo_segundos: int = 300,
    ) -> None:
        self._rag       = rag_service
        self._intervalo = intervalo_segundos
        self._hilo      = threading.Thread(
            target=self._ciclo,
            name="PDFWatcher",
            daemon=True,
        )
        self._activo = False

    def iniciar(self) -> None:
        """Arranca el watcher en segundo plano."""
        self._activo = True
        self._hilo.start()
        logger.info(
            f"PDFWatcher iniciado — verificacion cada {self._intervalo}s."
        )

    def detener(self) -> None:
        self._activo = False
        logger.info("PDFWatcher detenido.")

    # ------------------------------------------------------------------
    def _ciclo(self) -> None:
        # Primera verificacion al arrancar
        self._verificar()

        while self._activo:
            time.sleep(self._intervalo)
            if self._activo:
                self._verificar()

    def _verificar(self) -> None:
        try:
            if self._rag._indexer.necesita_reindexar():
                logger.info("PDFWatcher: PDF cambio, re-indexando...")
                self._rag.reindexar()
                logger.info("PDFWatcher: Re-indexacion completa.")
            else:
                logger.debug("PDFWatcher: PDF sin cambios.")
        except FileNotFoundError as e:
            logger.error(
                f"PDFWatcher: {e}. "
                "Coloca el formulario_210.pdf en data/ para continuar."
            )
        except Exception as e:
            logger.exception(f"PDFWatcher: error inesperado: {e}")
