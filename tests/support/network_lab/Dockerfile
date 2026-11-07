FROM node:24-trixie
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pil python3-tk python3-numpy python3-cairo python3-gi python3-gi-cairo gir1.2-pango-1.0 liblinphone-dev \
    libmediastreamer-dev libavcodec-dev libavutil-dev libegl-dev libgles-dev libglew-dev \
    iproute2 nftables conntrack tcpdump xvfb xauth libgl1-mesa-dri patch \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN node build_tools/build-admin.cjs && sh build_tools/linux/build-media.sh
RUN apt-get update && apt-get install -y --no-install-recommends \
    mediastreamer2-plugin-openh264 mediastreamer2-plugin-msqogl coturn openssl \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 LIBGL_ALWAYS_SOFTWARE=1
RUN python3 build_tools/linux/build-turn.py
ENTRYPOINT ["python3", "/app/tests/support/network_lab/entry.py"]
