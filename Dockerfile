FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Indiana/Indianapolis

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       sox \
       libsox-fmt-all \
       flac \
       curl \
       tini \
       util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
RUN python -m compileall -q app tests

RUN mkdir -p /data \
    && chown -R 568:568 /app /data

USER 568:568
RUN python -m unittest discover -s tests -v

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
