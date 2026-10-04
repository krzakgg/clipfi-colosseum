FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/root/.local/share/solana/install/active_release/bin:/root/.avm/bin:/root/.cargo/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential curl git pkg-config libudev-dev libssl-dev \
        ca-certificates python3 unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y

RUN curl --proto '=https' --tlsv1.2 -sSfL \
    https://solana-install.solana.workers.dev | bash

RUN cargo install --git https://github.com/coral-xyz/anchor avm \
    --locked --force \
    && avm install latest \
    && avm use latest

WORKDIR /workspace

COPY entrypoint.sh /usr/local/bin/escrow-entrypoint
RUN chmod +x /usr/local/bin/escrow-entrypoint

ENTRYPOINT ["escrow-entrypoint"]
