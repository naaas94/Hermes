# Hermes — container image for the CLI (override CMD with subcommands, e.g. `extract`).
# Build:  docker build -t hermes .
# Extras: docker build --build-arg PIP_EXTRAS='[tiktoken]' -t hermes .
#          docker build --build-arg PIP_EXTRAS='[ocr]' -t hermes-ocr .
# Run:     docker run --rm -v "$PWD:/work" -w /work hermes --help
#          docker run --rm -v "$PWD:/work" -w /work hermes extract ./doc.pdf

FROM python:3.12-slim-bookworm

ARG PIP_EXTRAS=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY hermes ./hermes/

RUN pip install --upgrade pip \
    && pip install ".${PIP_EXTRAS}" \
    && useradd --create-home --uid 1000 hermes \
    && chown -R hermes:hermes /app

USER hermes
WORKDIR /home/hermes

ENTRYPOINT ["hermes"]
CMD ["--help"]
