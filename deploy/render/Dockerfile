FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default \
    && useradd --create-home --home-dir /home/furuflow-streamlit --shell /usr/sbin/nologin furuflow-streamlit \
    && useradd --create-home --home-dir /home/furuflow-broker --shell /usr/sbin/nologin furuflow-broker

COPY requirements.txt ./
RUN python -m pip install --requirement requirements.txt

COPY . .
RUN chown -R root:root /app \
    && chmod -R a+rX /app

CMD ["python", "deploy/render/supervise.py"]
