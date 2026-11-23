# PRISM as a container image: the GitHub Package (ghcr.io/norik-jusufi/prism).
#
# Built and published by .github/workflows/package.yml for every release tag.
# PRISM is a desktop app, so the container draws on your screen through X11
# (on Wayland desktops: XWayland). On Linux:
#
#   xhost +SI:localuser:$(id -un)                       # let the container use your display
#   docker run --rm -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
#     --user $(id -u):$(id -g) --shm-size 1g \
#     -v prism-data:/data ghcr.io/norik-jusufi/prism:latest
#
# Settings, logins and stats live in the "prism-data" volume, so they survive
# image updates (docker pull ... to update).

FROM python:3.14-slim-bookworm

# Runtime libraries Qt WebEngine (Chromium) needs, plus fonts.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 libdrm2 \
        libegl1 libfontconfig1 libgbm1 libgl1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 \
        libx11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 \
        libxcb-xkb1 libxcomposite1 libxdamage1 libxkbcommon-x11-0 libxkbcommon0 \
        libxkbfile1 libxrandr2 libxshmfence1 libxtst6 \
        fonts-dejavu-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/prism
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Fresh blocklists baked in; a failing source isn't fatal.
RUN python update_blocklists.py || true \
    && python -m compileall -q . \
    && chmod -R a+rX /opt/prism

# Any user id works (docker run --user ...): data goes to /data.
# Chromium's own sandbox needs kernel features containers don't get by
# default; the container is the sandbox here.
ENV HOME=/data \
    XDG_DATA_HOME=/data \
    PYTHONUNBUFFERED=1 \
    QTWEBENGINE_DISABLE_SANDBOX=1
RUN mkdir -p /data && chmod 1777 /data
VOLUME /data

LABEL org.opencontainers.image.title="PRISM" \
      org.opencontainers.image.description="Privacy-first research browser by Synterra" \
      org.opencontainers.image.source="https://github.com/norik-jusufi/Prism"

ENTRYPOINT ["python", "/opt/prism/prism.py"]
