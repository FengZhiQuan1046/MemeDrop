FROM python:3.11-slim-bookworm

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QT_QPA_PLATFORM=offscreen \
    QT_LOGGING_RULES="qt.multimedia.*=false"

RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
    libegl1 libgl1 libglib2.0-0 libdbus-1-3 libfontconfig1 \
    libxkbcommon0 libxkbcommon-x11-0 libx11-6 libx11-xcb1 libxrandr2 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 \
    libpulse0 libasound2 fonts-noto-cjk fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt ./
ARG PYPI_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
RUN python -m pip install --no-cache-dir --index-url "${PYPI_INDEX}" -r requirements.txt
COPY main.py ./
COPY memedrop/ ./memedrop/
COPY tests/ ./tests/
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
