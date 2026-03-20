# renta-facil — Formulario 210 Colombia

Bot de Telegram que guía al contribuyente colombiano a determinar si debe
presentar declaración de renta (año gravable 2023) y a diligenciar el
Formulario 210, usando tu IA local (Qwen vía kingsrow_ai_base.py) con RAG
sobre el instructivo oficial de la DIAN.

---

## Requisitos previos

- Python 3.11+ (sin Docker) o Docker + Docker Compose
- `kingsrow_ai_base.py` corriendo en `http://localhost:8181`
- Token de Telegram (crear bot con @BotFather)
- El instructivo del Formulario 210 en PDF, descargado del portal oficial de la DIAN

---

## Directorio `/data/renta-facil` — lectura obligatoria antes de arrancar

El directorio `/data/renta-facil` es el corazón del sistema. Aquí viven tres cosas:

| Contenido | Generado por |
|-----------|-------------|
| `formulario_210.pdf` | **Tú** — debes colocarlo manualmente |
| `chroma/` | El bot — índice vectorial del PDF (auto-generado al arrancar) |
| `sesiones.db` | El bot — base de datos de conversaciones (auto-generado) |

El PDF es la **base de conocimiento principal**. Sin él el bot arranca pero
no puede recuperar contexto del formulario ni guiar correctamente al usuario.
El índice (`chroma/`) se genera automáticamente la primera vez que el bot
encuentra el PDF, y se regenera solo cada vez que detecta que el archivo cambió.

### Crear el directorio y colocar el PDF

```bash
# Crear el directorio en la raíz del sistema de archivos
sudo mkdir -p /data/renta-facil

# Dar propiedad al usuario que correrá el bot (sin Docker)
sudo chown $USER:$USER /data/renta-facil

# Descarga el instructivo del Formulario 210 desde el portal de la DIAN
# (busca la sección de Formularios e Instructivos, año gravable vigente)
# y coloca el archivo aquí con exactamente este nombre:
cp /ruta/donde/descargaste/el/formulario.pdf /data/renta-facil/formulario_210.pdf
```

> El nombre del archivo debe ser exactamente `formulario_210.pdf`.
> Está configurado en `.env` con la variable `PDF_FORMULARIO_PATH`.
> Si necesitas otro nombre, actualiza esa variable antes de arrancar.

### Permisos

El proceso que corre el bot necesita leer el PDF y escribir en `chroma/` y
`sesiones.db`. Aplica los permisos según tu escenario:

**Sin Docker (proceso corriendo como tu usuario):**
```bash
sudo chown -R $USER:$USER /data/renta-facil
chmod 755 /data/renta-facil
chmod 644 /data/renta-facil/formulario_210.pdf
```

**Con Docker (el contenedor escribe dentro del volumen montado):**
```bash
# Opción A — permisos amplios (más simple):
sudo chmod 777 /data/renta-facil

# Opción B — fijar el uid/gid del contenedor al de tu usuario actual
#   En docker-compose.yml, bajo el servicio renta-facil, agrega:
#     user: "${UID}:${GID}"
#   Luego aplica permisos estándar:
sudo chown -R $USER:$USER /data/renta-facil
chmod 755 /data/renta-facil
chmod 644 /data/renta-facil/formulario_210.pdf
```

**Verificar que todo está en orden antes de arrancar:**
```bash
ls -lah /data/renta-facil/
# Debes ver el archivo formulario_210.pdf listado

du -sh /data/renta-facil/formulario_210.pdf
# Si el tamaño es 0 o menor a 500 KB, el PDF no es válido
```

---

## Instalación sin Docker

```bash
# 1. Descomprimir / ubicarse en el proyecto
cd renta-facil

# 2. Activar tu entorno virtual
source ~/mlx-env/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env — como mínimo coloca tu TELEGRAM_TOKEN

# 5. Crear el directorio y colocar el PDF (ver sección anterior)
sudo mkdir -p /data/renta-facil
sudo chown $USER:$USER /data/renta-facil
chmod 755 /data/renta-facil
cp /ruta/al/formulario_210.pdf /data/renta-facil/formulario_210.pdf
chmod 644 /data/renta-facil/formulario_210.pdf

# 6. Arrancar (con kingsrow_ai_base.py ya corriendo en otra terminal)
python main.py
```

---

## Instalación con Docker

```bash
# 1. Configurar variables de entorno
cp .env.example .env
# Editar .env — como mínimo coloca tu TELEGRAM_TOKEN

# 2. Crear el directorio y colocar el PDF
sudo mkdir -p /data/renta-facil
sudo chmod 777 /data/renta-facil
cp /ruta/al/formulario_210.pdf /data/renta-facil/formulario_210.pdf

# 3. Construir la imagen y arrancar
docker compose up -d

# 4. Ver logs en tiempo real
docker logs -f renta-facil
```

El directorio `/data/renta-facil` del host queda montado directamente como
`/data/renta-facil` dentro del contenedor. Todo lo que el bot genere (índice,
base de datos) queda en tu máquina y sobrevive reinicios del contenedor.

---

## Actualizar el Formulario 210

Cuando la DIAN publique una nueva versión del instructivo:

```bash
# Descarga el nuevo instructivo desde el portal de la DIAN
# y reemplaza el archivo con el mismo nombre
cp /ruta/al/nuevo_formulario.pdf /data/renta-facil/formulario_210.pdf

# El PDFWatcher detecta el cambio automáticamente.
# Compara el hash SHA-256 del archivo cada 5 minutos
# (configurable con PDF_WATCH_INTERVAL en .env).
# No necesitas reiniciar el bot ni tocar código.
# El índice se regenera solo en segundo plano.
```

---

## Flujo completo del bot

```
/start
  └─► Bienvenida + instrucciones

[Usuario sube exogena.xlsx]
  └─► Parser detecta ingresos por tipo y entidad
  └─► Lógica hardcodeada evalúa obligación (umbrales UVT 2023)
  └─► Qwen explica el resultado con contexto del 210 (RAG)

  Si NO debe declarar:
    └─► Explica razones
    └─► Si tiene retenciones → ofrece declaración voluntaria

  Si SÍ debe declarar:
    └─► Confirmar datos personales (NIT, nombre)
    └─► Lista PERSONALIZADA de documentos según exógena:
        - Formato 220 por cada empleador detectado
        - Certificados de rendimientos por cada banco detectado
        - Certificado de pensión si se detectó
        - Documentos de deducciones (hipoteca, medicina prepagada, etc.)

[Usuario sube documentos.zip]
  └─► Parser analiza cada PDF/Excel del ZIP por entidad
  └─► Mapea cada documento a sus casillas del 210
  └─► Detecta documentos faltantes o inconsistencias
  └─► Qwen genera resumen del análisis

  Generación del borrador:
    └─► Cálculo hardcodeado de todas las cédulas (precisión legal)
    └─► Aplicación automática de topes:
        25% laboral (790 UVT), 40%/1340 UVT, intereses vivienda (1200 UVT), etc.
    └─► Qwen explica el borrador en lenguaje sencillo
    └─► Envía Excel con dos hojas:
        - Resumen ejecutivo (saldo a cargo/favor)
        - Detalle por casilla con explicación de cada una

[Etapa de revisión]
  └─► Usuario puede hacer preguntas libremente
  └─► Qwen responde con contexto del 210 (RAG) + datos del borrador
```

---

## Estructura del proyecto

```
renta-facil/
├── main.py                    ← Punto de entrada único
├── app.py                     ← Contenedor de dependencias (DI)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
│
├── config/
│   ├── constants.py           ← Umbrales, UVT, topes legales ET 2023
│   └── settings.py            ← Variables de entorno
│
├── interfaces/
│   └── base.py                ← Contratos (ABC) de todos los servicios
│
├── bot/
│   ├── handler.py             ← Manejo de mensajes Telegram + flujo
│   └── session_repo.py        ← Estado de conversación en SQLite
│
├── parsers/
│   ├── excel_parser.py        ← Exógena DIAN → ResumenExogena
│   └── zip_parser.py          ← ZIP documentos → campos del 210
│
├── rag/
│   ├── indexer.py             ← Chunking del PDF + detección de cambios
│   └── vector_store.py        ← ChromaDB wrapper + RAGService
│
├── ai/
│   └── client.py              ← QwenClient + PromptBuilder210
│
├── generators/
│   └── form_210.py            ← Excel/PDF con borrador prellenado
│
└── watchers/
    └── pdf_watcher.py         ← Thread que monitorea cambios del PDF

/data/renta-facil/               ← FUERA del proyecto — crear manualmente
    ├── formulario_210.pdf     ← Colocar manualmente (portal DIAN)
    ├── chroma/                ← Auto-generado al indexar
    └── sesiones.db            ← Auto-generado en primera conversación
```

---

## Principios SOLID aplicados

| Principio | Donde |
|-----------|-------|
| **S** — Responsabilidad única | Cada archivo hace una sola cosa. `pdf_watcher.py` solo vigila, no sabe de Telegram. |
| **O** — Abierto/cerrado | Cambias el PDF → solo re-indexa. Nunca tocas `handler.py`. |
| **L** — Sustitución Liskov | `ChromaVectorStore` implementa `IVectorStore`. Puedes cambiar a FAISS sin tocar nada más. |
| **I** — Segregación de interfaces | `bot/handler.py` no importa ChromaDB. `ai/client.py` no sabe de Excel. |
| **D** — Inversión de dependencias | `app.py` inyecta concretos. Los módulos solo dependen de interfaces (`IRAGService`, `IAIClient`, etc.). |

---

## Notas importantes

- El **cálculo del borrador** usa lógica hardcodeada (no IA) para garantizar
  precisión legal. La IA solo explica y conversa.
- Los **umbrales de obligación** son del año gravable 2023 (UVT = $42.412).
- El borrador es **orientativo**. El contribuyente debe verificar y presentar
  en el sistema de diligenciamiento oficial de la DIAN.
- El bot **no almacena archivos** subidos por el usuario — los procesa en
  memoria y elimina el temporal inmediatamente.
- El directorio `/data/renta-facil` **no se incluye en la imagen Docker** — siempre
  viene del host vía volumen, lo que garantiza que los datos persisten entre
  reinicios y actualizaciones de la imagen.
