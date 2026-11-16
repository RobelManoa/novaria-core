"""Scripts mongosh du prototype : le compte d'écriture de Flink à droits minimaux, et la lecture des agrégats.

Les scripts sont des textes envoyés sur l'entrée standard de `mongosh` dans le conteneur : le mot de passe du nouveau compte
passe par l'environnement du conteneur (`-e`), jamais par un argument ni par un fichier du dépôt.
"""

from __future__ import annotations

import json

COLLECTION = "stream_window_aggregates"
ROLE = "role_flux_proto"
UTILISATEUR = "svc_flux_proto"
VARIABLE_MOT_DE_PASSE = "MONGO_PASSWORD_FLUX_PROTO"

# Le compte d'écriture du job : trois droits sur UNE collection (pas de suppression, pas d'autre collection). Index et
# validateur sont posés ici avec le compte administrateur ; le job n'a pas le droit de les modifier.
SCRIPT_PREPARATION = f"""
const base = db.getSiblingDB(process.env.MONGO_DB);
const collection = "{COLLECTION}";
if (!base.getCollectionNames().includes(collection)) {{
  base.createCollection(collection, {{
    validator: {{ $jsonSchema: {{
      bsonType: "object",
      required: ["_id", "window_end", "sample_count", "vehicle_count"],
      properties: {{
        window_end: {{ bsonType: "date" }},
        sample_count: {{ bsonType: ["int", "long"], minimum: 1 }},
        vehicle_count: {{ bsonType: ["int", "long"], minimum: 0 }},
      }},
    }} }},
    validationLevel: "strict", validationAction: "error",
  }});
}}
const cible = base.getCollection(collection);
cible.createIndex({{ window_end: -1 }}, {{ name: "fin_de_fenetre" }});
const droits = [{{ resource: {{ db: process.env.MONGO_DB, collection }}, actions: ["find", "insert", "update"] }}];
if (base.getRole("{ROLE}")) {{ base.updateRole("{ROLE}", {{ privileges: droits, roles: [] }}); }}
else {{ base.createRole({{ role: "{ROLE}", privileges: droits, roles: [] }}); }}
const compte = {{ pwd: process.env.{VARIABLE_MOT_DE_PASSE}, roles: [{{ role: "{ROLE}", db: process.env.MONGO_DB }}] }};
if (base.getUser("{UTILISATEUR}")) {{ base.updateUser("{UTILISATEUR}", compte); }}
else {{ base.createUser({{ user: "{UTILISATEUR}", ...compte }}); }}
print("PRET");
"""

SCRIPT_LECTURE = f"""
const base = db.getSiblingDB(process.env.MONGO_DB);
const documents = base.getCollection("{COLLECTION}").find({{}}).toArray();
print("DOCUMENTS=" + EJSON.stringify(documents, {{ relaxed: true }}));
"""

SCRIPT_VIDAGE = f"""
const base = db.getSiblingDB(process.env.MONGO_DB);
print("SUPPRIMES=" + base.getCollection("{COLLECTION}").deleteMany({{}}).deletedCount);
"""


def lire_documents(sortie: str) -> list[dict]:
    """Les documents de `SCRIPT_LECTURE` : la ligne « DOCUMENTS=… » de la sortie de mongosh."""
    for ligne in sortie.splitlines():
        if ligne.startswith("DOCUMENTS="):
            return json.loads(ligne.removeprefix("DOCUMENTS="))
    raise ValueError(f"la sortie de mongosh ne contient pas de ligne DOCUMENTS= (début : {sortie[:200]!r})")
