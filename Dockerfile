FROM python:3.12-slim

# Sin dependencias: el servidor usa sólo la biblioteca estándar. Así el build no puede fallar por
# un pip install caído y la imagen arranca siempre.
WORKDIR /app
COPY . /app

ENV PORT=3000 \
    DATOS=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /data
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=4s --start-period=15s --retries=3 \
  CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:3000/api/salud',timeout=3)"

CMD ["python3", "servidor_nan.py"]
