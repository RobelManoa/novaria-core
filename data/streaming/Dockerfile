# Image Flink du prototype de flux (DAT-09) : Flink 1.20 (version à support long) et les deux connecteurs SQL dont le job a
# besoin, épinglés par leur empreinte SHA-256 (le téléchargement échoue si le fichier diffère). Aucun secret dans l'image :
# les identifiants arrivent par l'environnement au lancement.
# L'image de base est désignée par son étiquette ET son empreinte (celle de la liste multi-architecture, relevée le 16/11/2026).
FROM flink:1.20.5-java17@sha256:7d051ec9aa4048eb7e40ce0f71061a335147f7d1683628a677ff796bfeb41e32

# Connecteur Kafka pour Flink SQL (Maven Central, org.apache.flink:flink-sql-connector-kafka:3.4.0-1.20)
ADD --checksum=sha256:b860724fd97d7da0901bfc3859680442f4c1aa2b35ab944407558b393a1cf93e --chmod=644 \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.4.0-1.20/flink-sql-connector-kafka-3.4.0-1.20.jar \
    /opt/flink/lib/

# Connecteur MongoDB pour Flink SQL (Maven Central, org.apache.flink:flink-sql-connector-mongodb:2.0.0-1.20.0)
ADD --checksum=sha256:c2f4cd63fa4ac539300e1d07453e7f3f1f723e48e48774cdb9b0c3eb2e115335 --chmod=644 \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-mongodb/2.0.0-1.20.0/flink-sql-connector-mongodb-2.0.0-1.20.0.jar \
    /opt/flink/lib/

# Dossier des points de contrôle : le volume Docker monté dessus reprend son propriétaire (l'utilisateur « flink », pas root).
RUN mkdir -p /flink-data/checkpoints /flink-data/savepoints && chown -R flink:flink /flink-data
