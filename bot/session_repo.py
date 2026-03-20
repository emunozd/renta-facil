"""
bot/session_repo.py
Persiste el estado de cada conversacion en SQLite.
Un registro por chat_id de Telegram.
"""
import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from typing import Optional

from interfaces.base import ISessionRepo, SesionUsuario, ResumenExogena, AnalisisObligacion
from config.constants import EstadoBot

logger = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sesiones (
    chat_id     INTEGER PRIMARY KEY,
    estado      TEXT    NOT NULL DEFAULT 'inicio',
    datos       TEXT    NOT NULL DEFAULT '{}',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


class SQLiteSessionRepo(ISessionRepo):
    """
    Almacena y recupera sesiones de usuario en SQLite.
    El campo `datos` es un JSON con toda la informacion de la sesion.
    """

    def __init__(self, db_path: str) -> None:
        import os
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._db_path = db_path
        self._inicializar()

    def _inicializar(self) -> None:
        with self._conexion() as conn:
            conn.execute(_CREATE_SQL)

    @contextmanager
    def _conexion(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    def obtener(self, chat_id: int) -> Optional[SesionUsuario]:
        with self._conexion() as conn:
            fila = conn.execute(
                "SELECT estado, datos FROM sesiones WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()

        if not fila:
            return None

        try:
            datos = json.loads(fila["datos"])
            sesion = SesionUsuario(chat_id=chat_id, estado=fila["estado"])

            # Reconstruir ResumenExogena si existe
            if datos.get("resumen_exogena"):
                re_dict = datos["resumen_exogena"]
                sesion.resumen_exogena = ResumenExogena(**re_dict)

            # Reconstruir AnalisisObligacion si existe
            if datos.get("analisis_obligacion"):
                ao_dict = datos["analisis_obligacion"]
                sesion.analisis_obligacion = AnalisisObligacion(**ao_dict)

            sesion.datos_confirmados   = datos.get("datos_confirmados", {})
            sesion.documentos_recibidos = datos.get("documentos_recibidos", [])
            sesion.documentos_pendientes = datos.get("documentos_pendientes", [])
            sesion.borrador_210         = datos.get("borrador_210", {})
            sesion.historial_mensajes   = datos.get("historial_mensajes", [])
            sesion.paso_actual          = datos.get("paso_actual", 0)
            sesion.ultima_pregunta      = datos.get("ultima_pregunta", "")

            return sesion
        except Exception as e:
            logger.warning(f"Error reconstruyendo sesion {chat_id}: {e}")
            return None

    def guardar(self, sesion: SesionUsuario) -> None:
        datos: dict = {
            "datos_confirmados":    sesion.datos_confirmados,
            "documentos_recibidos": sesion.documentos_recibidos,
            "documentos_pendientes": sesion.documentos_pendientes,
            "borrador_210":         sesion.borrador_210,
            "historial_mensajes":   sesion.historial_mensajes[-40:],  # max 40 turnos
            "paso_actual":          sesion.paso_actual,
            "ultima_pregunta":      sesion.ultima_pregunta,
        }

        if sesion.resumen_exogena:
            datos["resumen_exogena"] = self._serializar_dataclass(
                sesion.resumen_exogena
            )

        if sesion.analisis_obligacion:
            datos["analisis_obligacion"] = self._serializar_dataclass(
                sesion.analisis_obligacion
            )

        with self._conexion() as conn:
            conn.execute(
                """
                INSERT INTO sesiones (chat_id, estado, datos, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(chat_id) DO UPDATE SET
                    estado     = excluded.estado,
                    datos      = excluded.datos,
                    updated_at = excluded.updated_at
                """,
                (sesion.chat_id, sesion.estado, json.dumps(datos, ensure_ascii=False)),
            )

    def eliminar(self, chat_id: int) -> None:
        with self._conexion() as conn:
            conn.execute("DELETE FROM sesiones WHERE chat_id = ?", (chat_id,))
        logger.info(f"Sesion eliminada para chat_id={chat_id}")

    @staticmethod
    def _serializar_dataclass(obj) -> dict:
        """Convierte un dataclass a dict serializable (floats seguros)."""
        try:
            return asdict(obj)
        except Exception:
            return {}
