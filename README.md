# renta-facil

AI-powered Telegram bot that guides Colombian taxpayers through the Formulario 210
income tax return. Analyzes the DIAN exogena, collects supporting documents via
vision AI, and generates a pre-filled Form 210 draft in Excel. Powered by a local
LLM with RAG over the official DIAN PDF.

**Ano gravable:** 2025 | **UVT:** $49.799

---

## Requisitos

- Docker + Docker Compose
- Servidor de IA local con endpoint compatible OpenAI (`/v1/chat/completions`)
  y endpoint compatible Anthropic con soporte de vision (`/v1/messages`)
- Token de Telegram (crear bot con @BotFather)
- Instructivo del Formulario 210 en PDF, descargado del portal oficial de la DIAN

---

## Directorio `/var/lib/renta-facil`

Vive fuera del proyecto. Aqui se almacenan el PDF, el indice vectorial y las
sesiones de usuario.

| Contenido | Generado por |
|-----------|-------------|
| `formulario_210.pdf` | Tu — colocarlo manualmente |
| `chroma/` | Auto-generado al arrancar |
| `sesiones.db` | Auto-generado en la primera conversacion |

```bash
sudo mkdir -p /var/lib/renta-facil
cp /ruta/al/formulario_210.pdf /var/lib/renta-facil/formulario_210.pdf
```

### Permisos

**Sin Docker:**
```bash
sudo chown -R $USER:$USER /var/lib/renta-facil
chmod 755 /var/lib/renta-facil
chmod 644 /var/lib/renta-facil/formulario_210.pdf
```

**Con Docker:**
```bash
sudo chmod 777 /var/lib/renta-facil
```

---

## Instalacion con Docker

```bash
cp .env.example .env
# Editar .env con TELEGRAM_TOKEN y AI_BASE_URL

sudo mkdir -p /var/lib/renta-facil
sudo chmod 777 /var/lib/renta-facil
cp /ruta/al/formulario_210.pdf /var/lib/renta-facil/formulario_210.pdf

docker compose up -d
docker logs -f renta-facil
```

---

## Flujo — 11 pasos

```
Paso  1  Subir exogena (.xlsx) — evalua obligacion de declarar
Paso  2  Confirmar datos personales (NIT, nombre)
Paso  3  Dependientes economicos
Paso  4  Credito hipotecario
Paso  5  Medicina prepagada
Paso  6  Aportes AFC / FPV
Paso  7  Pensiones voluntarias
Paso  8  Credito ICETEX
Paso  9  Resumen — lista exacta de documentos con nombre de archivo requerido
Paso 10  Subir ZIP — revision documento por documento con confirmacion del usuario
Paso 11  Borrador del Formulario 210 en Excel + explicacion por cedula
```

La obligacion de declarar y todos los calculos tributarios son logica hardcodeada
en Python — la IA solo explica, guia y extrae valores de los certificados por vision.

---

## Estructura

```
renta-facil/
├── main.py                 ← Punto de entrada
├── app.py                  ← Contenedor de dependencias (DI)
├── config/
│   ├── constants.py        ← UVT, topes, umbrales — todo calculado desde UVT
│   └── settings.py         ← Variables de entorno
├── interfaces/
│   └── base.py             ← Contratos ABC de todos los servicios
├── bot/
│   ├── handler.py          ← Flujo conversacional + calculos tributarios
│   └── session_repo.py     ← Estado de sesion en SQLite
├── parsers/
│   ├── excel_parser.py     ← Exogena DIAN → ResumenExogena
│   ├── zip_parser.py       ← ZIP lazy — procesa un archivo a la vez
│   └── vision_parser.py    ← PDF → imagen → LLM extrae valores
├── rag/
│   ├── indexer.py          ← Chunking del PDF + deteccion de cambios por hash
│   └── vector_store.py     ← ChromaDB wrapper
├── ai/
│   └── client.py           ← LLMClient + PromptBuilder210
├── generators/
│   └── form_210.py         ← Excel con borrador prellenado
└── watchers/
    └── pdf_watcher.py      ← Re-indexa si el PDF cambia

/var/lib/renta-facil/          ← Fuera del proyecto, montar como volumen
    formulario_210.pdf
    chroma/
    sesiones.db
```

---

## Actualizar el ano gravable

Editar dos lineas en `config/constants.py`:

```python
ANNO_GRAVABLE = 2026
UVT = 52_374  # valor fijado por la DIAN para ese ano
```

Todos los umbrales y topes se recalculan automaticamente desde la UVT.
El PDF del formulario tambien debe reemplazarse con la version del nuevo ano.

---

## Notas

- El borrador es **orientativo**. El contribuyente debe verificar y presentar
  en el sistema oficial de la DIAN.
- El bot no almacena archivos subidos por el usuario — los procesa y elimina
  el temporal inmediatamente.
- Solo soporta el ano gravable configurado en `constants.py`. No maneja
  declaraciones de anos anteriores.