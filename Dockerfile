FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema para pdfplumber y openpyxl
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpoppler-cpp-dev \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo fuente (sin data/ — viene del volumen)
COPY config/      ./config/
COPY interfaces/  ./interfaces/
COPY parsers/     ./parsers/
COPY rag/         ./rag/
COPY ai/          ./ai/
COPY bot/         ./bot/
COPY generators/  ./generators/
COPY watchers/    ./watchers/
COPY app.py       .
COPY main.py      .
COPY __init__.py  .

# El directorio data/ lo provee el volumen en runtime
# Aqui solo creamos el punto de montaje
RUN mkdir -p /data/renta-facil

CMD ["python", "main.py"]
