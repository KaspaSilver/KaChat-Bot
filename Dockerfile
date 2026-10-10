# ── KaChat Bot v2 ────────────────────────────────────────────────────────────
# One container, several bots (mining / price / wallet), each with its own
# wallet and owner. The Kaspa Quick Start panel writes /conf/bots.json and
# reads /state/; see README.md.
#   1. installs grpcio, the Kaspa Python SDK and cryptography
#   2. compiles proto/ into Python stubs (gRPC MessageStream to kaspad)
#   3. runs botd.py
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

WORKDIR /app

# Some grpcio builds on ARM need a compiler.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ ./proto/
RUN python -m grpc_tools.protoc \
        -I./proto \
        --python_out=. \
        --grpc_python_out=. \
        ./proto/messages.proto \
        ./proto/rpc.proto \
    && echo "Proto files compiled successfully."

COPY kachat/ ./kachat/
COPY botd.py .
# Wallet generator, run on its own by the panel (python gen_wallet.py --network ...).
# Same SDK the bots sign with, so the address it prints is the one they spend from.
COPY gen_wallet.py .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "botd.py"]
