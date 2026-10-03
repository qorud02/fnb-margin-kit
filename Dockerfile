FROM python:3.12-slim-bookworm AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE /build/
COPY src/ /build/src/
COPY scripts/verify_wheel.py /build/scripts/verify_wheel.py
RUN python -m pip wheel --no-deps --wheel-dir /wheels . \
    && python scripts/verify_wheel.py /wheels

FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/qorud02/fnb-margin-kit" \
      org.opencontainers.image.description="Calculate menu contribution from explicit CSV prices, costs and sold units." \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /wheels /wheels
COPY LICENSE /app/LICENSE
RUN python -m pip install --no-index --no-deps /wheels/*.whl \
    && python -I -c "from importlib.metadata import version; print(version('fnb-margin-kit'))" \
    && rm -rf /wheels \
    && mkdir /work

USER 10001:10001
WORKDIR /work
ENTRYPOINT ["python", "-P", "-m", "fnb_margin_kit.cli"]
CMD ["--help"]
