FROM python:3.11.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends gcc nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default \
    && useradd --create-home --home-dir /home/furuflow-streamlit --shell /usr/sbin/nologin furuflow-streamlit \
    && useradd --create-home --home-dir /home/furuflow-broker --shell /usr/sbin/nologin furuflow-broker

COPY requirements.txt ./
RUN python -m pip install --requirement requirements.txt

COPY . .
RUN chown -R root:root /app \
    && chmod -R a+rX /app \
    && touch /app/pool_history.json \
    && chown furuflow-streamlit:furuflow-streamlit /app/pool_history.json \
    && chmod 600 /app/pool_history.json

CMD ["python", "deploy/render/supervise.py"]
