# ── KaChat Bot v2 ────────────────────────────────────────────────────────────
# One container, several bots (mining / price / wallet / answers), each with its own
# wallet. The Kaspa Quick Start panel writes /conf/bots.json and reads /state/; see README.md.
#
# Two stages (BOT-008): the first has the compilers some grpcio builds need (on ARM) and
# compiles proto/ into Python stubs; the image that runs holds only Python, the installed
# packages (exact versions, requirements.txt) and the bot, and runs as an unprivileged user.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY proto/ ./proto/
RUN PYTHONPATH=/install/lib/python3.12/site-packages python -m grpc_tools.protoc \
        -I./proto \
        --python_out=. \
        --grpc_python_out=. \
        ./proto/messages.proto \
        ./proto/rpc.proto \
    && echo "Proto files compiled successfully."


FROM python:3.12-slim

# The bot's own user; /state is handed to it at start (docker-entrypoint.sh).
RUN groupadd --system --gid 10001 bot \
    && useradd --system --uid 10001 --gid bot --home-dir /app --no-create-home --shell /usr/sbin/nologin bot

COPY --from=build /install /usr/local
WORKDIR /app
COPY --from=build /build/messages_pb2.py /build/messages_pb2_grpc.py /build/rpc_pb2.py /build/rpc_pb2_grpc.py ./
COPY kachat/ ./kachat/
COPY botd.py .
# Wallet generator, run on its own by the panel (python gen_wallet.py --network ...).
# Same SDK the bots sign with, so the address it prints is the one they spend from.
COPY gen_wallet.py .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-u", "botd.py"]
