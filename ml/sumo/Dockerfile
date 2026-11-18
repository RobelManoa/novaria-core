# --- Image du prototype SUMO (IA-11) : SUMO 1.28.0 installé depuis PyPI avec empreintes, non-root, aucune donnée dedans ---
# Pas d'image officielle de 1,6 Go : le paquet `eclipse-sumo` (environ 90 Mo) apporte les binaires `sumo`, `netconvert`, `duarouter`.
FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 SUMO_HOME=/usr/local/lib/python3.15/site-packages/sumo
# Bibliothèques que les binaires de SUMO exigent au chargement, même sans interface graphique (trouvées avec `ldd`).
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libx11-6 libxext6 libxrender1 libgl1 libatomic1 libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt \
    && useradd --system --uid 10001 --create-home sumo
USER sumo
WORKDIR /work
# Le dossier d'un run est monté sur /work ; la commande vient de l'appelant (netconvert puis sumo).
CMD ["sumo", "--version"]
