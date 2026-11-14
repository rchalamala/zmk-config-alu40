FROM docker.io/zmkfirmware/zmk-build-arm@sha256:edb1c953438c6f720ddb79c3762f3972013b7fbbaf4fff3592fc869983e7afc5

ENV PYTHONDONTWRITEBYTECODE=1

RUN --mount=type=bind,source=.,target=/source \
    --mount=type=secret,id=proxy_ca \
    set -eu; \
    if [ -f /run/secrets/proxy_ca ]; then \
      export GIT_SSL_CAINFO=/run/secrets/proxy_ca REQUESTS_CA_BUNDLE=/run/secrets/proxy_ca; \
    fi; \
    mkdir -p /work /config; \
    cp -a /source/. /config/; \
    cd /work; \
    python3 /config/scripts/build_firmware.py --prepare
WORKDIR /work
ENTRYPOINT ["python3", "/config/scripts/build_firmware.py"]
