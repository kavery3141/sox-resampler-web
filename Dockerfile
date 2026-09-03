FROM debian:bookworm-slim AS sox-ultra-builder

ARG SOX_SOURCE_COMMIT=0be259eaa9ce3f3fa587a3ef0cf2c0b9c73167a2

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git build-essential autoconf automake libtool pkg-config \
       libflac-dev libogg-dev libvorbis-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone https://github.com/mansr/sox.git source \
    && cd source \
    && git checkout "$SOX_SOURCE_COMMIT" \
    && test "$(git rev-parse HEAD)" = "$SOX_SOURCE_COMMIT"

# Stock SoX's development rate effect accepts a custom bit-accuracy request with -d,
# but artificially caps the parser/assert at 33 bits. The foobar component exposes
# Ultra 37, so make only those two guarded limit changes while retaining the same
# double-precision SoX rate implementation.
RUN cd /build/source \
    && test "$(grep -Fc 'assert(!bits || (15 <= bits && bits <= 33));' src/rate.c)" = "1" \
    && test "$(grep -Fc "GETOPT_NUMERIC(optstate, 'd', bit_depth, 15, 33)" src/rate.c)" = "1" \
    && sed -i 's/assert(!bits || (15 <= bits && bits <= 33));/assert(!bits || (15 <= bits \&\& bits <= 53));/' src/rate.c \
    && sed -i "s/GETOPT_NUMERIC(optstate, 'd', bit_depth, 15, 33)/GETOPT_NUMERIC(optstate, 'd', bit_depth, 15, 53)/" src/rate.c \
    && grep -Fq 'assert(!bits || (15 <= bits && bits <= 53));' src/rate.c \
    && grep -Fq "GETOPT_NUMERIC(optstate, 'd', bit_depth, 15, 53)" src/rate.c \
    && autoreconf -fi \
    && ./configure --prefix=/opt/sox-ultra --disable-shared --enable-static \
    && make -j"$(nproc)" \
    && make install DESTDIR=/stage \
    && /stage/opt/sox-ultra/bin/sox --version


FROM python:3.12-slim-bookworm

ARG APP_VERSION=1.0.0
ARG BUILD_SHA=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Indiana/Indianapolis \
    APP_VERSION=${APP_VERSION} \
    BUILD_SHA=${BUILD_SHA} \
    SOX_ULTRA_BIN=/opt/sox-ultra/bin/sox \
    ZFS_POOL=MainStorage

RUN sed -i 's/^Components: main$/Components: main contrib/' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       sox \
       libsox-fmt-all \
       flac \
       curl \
       tini \
       util-linux \
       cpulimit \
       zfsutils-linux \
    && rm -rf /var/lib/apt/lists/*

ARG RSGAIN_VERSION=3.7
ARG RSGAIN_SHA256=0fb483b82674e63855dfba633409af0735f8600e231f512afb5627e52c01b46e
RUN curl -fsSL "https://github.com/complexlogic/rsgain/releases/download/v${RSGAIN_VERSION}/rsgain_${RSGAIN_VERSION}_amd64.deb" -o /tmp/rsgain.deb \
    && echo "${RSGAIN_SHA256}  /tmp/rsgain.deb" | sha256sum -c - \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/rsgain.deb \
    && rm -f /tmp/rsgain.deb \
    && rm -rf /var/lib/apt/lists/* \
    && rsgain --version

COPY --from=sox-ultra-builder /stage/opt/sox-ultra /opt/sox-ultra

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
RUN printf '%s\n' "$BUILD_SHA" > /app/app/static/build.txt \
    && python -m compileall -q app tests \
    && /opt/sox-ultra/bin/sox --version \
    && rsgain --version \
    && /opt/sox-ultra/bin/sox -n -r 96000 -b 24 /tmp/ultra-input.flac synth 0.05 sine 997 vol 0.1 \
    && /opt/sox-ultra/bin/sox /tmp/ultra-input.flac /tmp/ultra-output.flac rate -d 37 -B 95 -p 50 48000 \
    && test "$(/opt/sox-ultra/bin/soxi -r /tmp/ultra-output.flac)" = "48000" \
    && rm -f /tmp/ultra-input.flac /tmp/ultra-output.flac

RUN mkdir -p /data \
    && chown -R 568:568 /app /data

USER 568:568
RUN python -m unittest discover -s tests -v

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
