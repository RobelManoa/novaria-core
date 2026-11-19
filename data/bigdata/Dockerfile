# --- Image du prototype Big Data (DAT-08) : PySpark en mode local, hors des quatre services (ADR-016) ---
# Construction depuis la racine du dépôt :  docker build -t novaria-bigdata -f data/bigdata/Dockerfile data/bigdata
# Le code et les données ne sont pas dans l'image : le dépôt est monté en lecture seule, les données dans un volume.
# PySpark n'est publié que sous forme de sources (PyPI : pyspark-4.1.4.tar.gz, pas de roue). Un premier étage le construit en
# roue depuis le verrou à empreintes (les sources sont vérifiées par leur empreinte) ; l'image finale n'installe que des roues
# (--only-binary :all:), sans exécuter de script d'installation de paquet (règle SonarQube docker:S8541).
FROM python:3.12-slim AS roues
COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --require-hashes --no-deps --no-cache-dir -r /tmp/requirements.txt -w /roues

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY --from=roues /roues /roues
RUN pip install --no-index --find-links /roues --only-binary :all: pyspark py4j \
    && rm -rf /roues \
    && useradd --uid 1000 --create-home novaria && mkdir -p /data && chown novaria /data
USER novaria
ENV PYTHONPATH=/repo/data/bigdata:/repo/data/etl
WORKDIR /repo/data/bigdata
VOLUME /data
ENTRYPOINT ["python", "-m", "bigdata"]
