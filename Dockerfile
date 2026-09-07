FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBRA_DB=/data/debra.sqlite3 \
    PORT=5000

WORKDIR /app

# poppler-utils = pdftotext für den optionalen Vorjahres-PDF-Import
# (die beigelegte 2025er-Rangliste funktioniert auch ohne).
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Datenverzeichnis (SQLite-DB) als Volume – bleibt über Neustarts erhalten.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 5000

# einfacher Health-Check auf die Login-Seite
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:'+os.environ.get('PORT','5000')+'/login').read()" || exit 1

CMD ["python", "serve.py"]
