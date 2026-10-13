ARG BMV2_IMAGE=p4lang/behavioral-model@sha256:53eb8d8514619a1d0033fab462dd9f002a6055c82a4676ac180322e0d589f99f
FROM ${BMV2_IMAGE}
USER root
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends mininet python3 iproute2 iputils-ping iperf3 ethtool curl && rm -rf /var/lib/apt/lists/*
WORKDIR /experiment
ENTRYPOINT ["/usr/bin/python3", "-m", "src.emulator"]
