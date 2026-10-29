// Exécuté UNE SEULE FOIS par l'image MongoDB, au premier démarrage d'un volume vide
// (dossier /docker-entrypoint-initdb.d, exécuté avec mongosh sous le compte administrateur).
// Crée les collections avec leurs validateurs, les index (dont les index à durée de vie),
// les rôles à droits minimaux et un utilisateur par service (ADR-024).
// Les mots de passe viennent des variables d'environnement : aucun secret dans ce fichier.

const dbName = process.env.MONGO_DB;
if (!dbName) {
  throw new Error("Variable manquante : MONGO_DB");
}
const secret = (name) => {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Variable manquante : ${name}`);
  }
  return value;
};
const seconds = (name, fallback) => {
  const value = Number(process.env[name] || fallback);
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${name} doit être un nombre entier de secondes positif`);
  }
  return value;
};

const database = db.getSiblingDB(dbName);
const SOURCES = ["SIMULATED", "REAL_HISTORICAL", "REAL_LIVE"];

// --- Collections et validateurs --------------------------------------------------------------
// Les validateurs refusent un document mal formé (échec visible à l'écriture, ADR-012).
// Les champs inconnus restent permis : le contrat d'événement prévoit des ajouts compatibles.
const collections = {
  // Événements bruts validés, tels que publiés sur iot.raw (propriétaire : service de collecte).
  raw_events: {
    $jsonSchema: {
      bsonType: "object",
      required: ["id", "type", "source", "time", "schema_version", "domain", "received_at", "data"],
      properties: {
        id: { bsonType: "string", minLength: 1, maxLength: 200 },
        type: { bsonType: "string", pattern: "^novaria\\.[a-z0-9_.]+\\.v[0-9]+$" },
        source: { bsonType: "string", minLength: 1 },
        subject: { bsonType: "string" },
        time: { bsonType: "date" },
        schema_version: { bsonType: "string" },
        domain: { bsonType: "string" },
        correlation_id: { bsonType: "string" },
        received_at: { bsonType: "date" },
        data: {
          bsonType: "object",
          required: ["provenance"],
          properties: {
            provenance: {
              bsonType: "object",
              required: ["source_type"],
              properties: {
                source_type: { enum: SOURCES },
                run_id: { bsonType: "string" },
                scenario_id: { bsonType: "string" },
                seed: { bsonType: "number" },
              },
            },
          },
        },
      },
    },
  },
  // Archive du topic d'erreurs errors.dlq : message rejeté, motif et charge d'origine.
  rejects: {
    $jsonSchema: {
      bsonType: "object",
      required: ["source_topic", "rejected_at", "reason", "original_payload"],
      properties: {
        source_topic: { bsonType: "string" },
        rejected_at: { bsonType: "date" },
        reason: { bsonType: "string", minLength: 1 },
        service: { bsonType: "string" },
        attempts: { bsonType: "number" },
      },
    },
  },
  // Journal d'audit : qui a fait quoi, quand, avec quel résultat. Jamais de secret ni de donnée personnelle.
  audit_logs: {
    $jsonSchema: {
      bsonType: "object",
      required: ["ts", "service", "actor", "action", "outcome"],
      properties: {
        ts: { bsonType: "date" },
        service: { bsonType: "string" },
        actor: { bsonType: "string" },
        action: { bsonType: "string" },
        outcome: { enum: ["ok", "denied", "error"] },
        correlation_id: { bsonType: "string" },
        details: { bsonType: "object" },
      },
    },
  },
  // Compteurs d'usage de l'API par point d'accès et par tranche de temps.
  usage_stats: {
    $jsonSchema: {
      bsonType: "object",
      required: ["endpoint", "bucket_start", "count"],
      properties: {
        endpoint: { bsonType: "string" },
        bucket_start: { bsonType: "date" },
        count: { bsonType: "number", minimum: 0 },
      },
    },
  },
  // Statistiques de traitement : qualité, retards, rejets par fenêtre.
  processing_stats: {
    $jsonSchema: {
      bsonType: "object",
      required: ["kind", "window_start", "values"],
      properties: {
        kind: { enum: ["quality", "lateness", "rejects"] },
        window_start: { bsonType: "date" },
        road_segment_id: { bsonType: "string" },
        values: { bsonType: "object" },
      },
    },
  },
  // Journal des ingestions de jeux de données ouverts (DAT-03) : un document par fichier brut téléchargé.
  ingestion_runs: {
    $jsonSchema: {
      bsonType: "object",
      required: [
        "load_key", "run_id", "last_run_id", "dataset_id", "source_type", "source_url", "license",
        "window_start", "window_end", "file_path", "sha256", "bytes", "rows", "ingested_at", "last_seen_at",
        "executions",
      ],
      properties: {
        load_key: { bsonType: "string", minLength: 1 },
        run_id: { bsonType: "string", minLength: 1 },
        last_run_id: { bsonType: "string", minLength: 1 },
        dataset_id: { bsonType: "string", minLength: 1 },
        source_type: { enum: SOURCES },
        source_url: { bsonType: "string", pattern: "^https://" },
        source_modified_at: { bsonType: "date" },
        license: { bsonType: "string", minLength: 1 },
        window_start: { bsonType: "date" },
        window_end: { bsonType: "date" },
        file_path: { bsonType: "string", minLength: 1 },
        sha256: { bsonType: "string", pattern: "^[0-9a-f]{64}$" },
        bytes: { bsonType: "number", minimum: 0 },
        rows: { bsonType: "number", minimum: 0 },
        ingested_at: { bsonType: "date" },
        last_seen_at: { bsonType: "date" },
        executions: { bsonType: "number", minimum: 1 },
      },
    },
  },
  // Suivi des entraînements (MLOps, ADR-017) : un document par exécution.
  model_runs: {
    $jsonSchema: {
      bsonType: "object",
      required: ["run_id", "created_at", "git_sha", "dataset_sha256", "seed", "params", "metrics", "status"],
      properties: {
        run_id: { bsonType: "string" },
        created_at: { bsonType: "date" },
        git_sha: { bsonType: "string" },
        dataset_sha256: { bsonType: "string", pattern: "^[0-9a-f]{64}$" },
        seed: { bsonType: "number" },
        params: { bsonType: "object" },
        metrics: { bsonType: "object" },
        model_sha256: { bsonType: "string", pattern: "^[0-9a-f]{64}$" },
        status: { enum: ["trained", "rejected", "registered"] },
      },
    },
  },
};

for (const [name, validator] of Object.entries(collections)) {
  database.createCollection(name, { validator, validationLevel: "strict", validationAction: "error" });
}

// --- Index -----------------------------------------------------------------------------------
const rawTtl = seconds("RAW_EVENTS_TTL_SECONDS", 1209600); // 14 jours
const rejectsTtl = seconds("REJECTS_TTL_SECONDS", 2592000); // 30 jours

database.raw_events.createIndex({ id: 1 }, { unique: true, name: "uniq_event_id" }); // idempotence
database.raw_events.createIndex({ subject: 1, time: -1 }, { name: "subject_time" });
database.raw_events.createIndex({ received_at: 1 }, { expireAfterSeconds: rawTtl, name: "ttl_received_at" });

database.rejects.createIndex({ source_topic: 1, rejected_at: -1 }, { name: "topic_time" });
database.rejects.createIndex({ rejected_at: 1 }, { expireAfterSeconds: rejectsTtl, name: "ttl_rejected_at" });

database.audit_logs.createIndex({ ts: -1 }, { name: "ts_desc" });
database.audit_logs.createIndex({ actor: 1, ts: -1 }, { name: "actor_ts" });
database.audit_logs.createIndex({ correlation_id: 1 }, { name: "correlation", sparse: true });

database.usage_stats.createIndex({ endpoint: 1, bucket_start: -1 }, { unique: true, name: "uniq_endpoint_bucket" });

database.processing_stats.createIndex({ kind: 1, window_start: -1 }, { name: "kind_window" });

database.ingestion_runs.createIndex({ load_key: 1 }, { unique: true, name: "uniq_load_key" }); // idempotence
database.ingestion_runs.createIndex({ dataset_id: 1, ingested_at: -1 }, { name: "dataset_time" });

database.model_runs.createIndex({ run_id: 1 }, { unique: true, name: "uniq_run_id" });
database.model_runs.createIndex({ created_at: -1 }, { name: "created_desc" });

// --- Rôles à droits minimaux et utilisateurs de service ---------------------------------------
const grant = (collection, actions) => ({ resource: { db: dbName, collection }, actions });
const roles = {
  role_collecte: [grant("raw_events", ["find", "insert"]), grant("rejects", ["find", "insert"])],
  role_traitement: [
    grant("raw_events", ["find"]),
    grant("rejects", ["find", "insert"]),
    grant("processing_stats", ["find", "insert", "update"]),
    grant("ingestion_runs", ["find", "insert", "update"]), // pipelines ETL de data/etl (DAT-03)
  ],
  role_reponse: [grant("audit_logs", ["find", "insert"])],
  role_backend: [grant("audit_logs", ["find", "insert"]), grant("usage_stats", ["find", "insert", "update"])],
  role_ml: [
    grant("model_runs", ["find", "insert", "update"]),
    grant("raw_events", ["find"]),
    grant("processing_stats", ["find"]),
  ],
};
for (const [role, privileges] of Object.entries(roles)) {
  database.createRole({ role, privileges, roles: [] });
}

const users = {
  svc_collecte: ["MONGO_PASSWORD_COLLECTE", "role_collecte"],
  svc_traitement: ["MONGO_PASSWORD_TRAITEMENT", "role_traitement"],
  svc_reponse: ["MONGO_PASSWORD_REPONSE", "role_reponse"],
  svc_backend: ["MONGO_PASSWORD_BACKEND", "role_backend"],
  svc_ml: ["MONGO_PASSWORD_ML", "role_ml"],
};
for (const [user, [variable, role]] of Object.entries(users)) {
  database.createUser({ user, pwd: secret(variable), roles: [{ role, db: dbName }] });
}

print(`MongoDB initialisé : base ${dbName}, ${Object.keys(collections).length} collections, ${Object.keys(users).length} utilisateurs de service.`);
