-- 0003 · Service d'alerte usager (schéma alertes).
-- Aucune clé étrangère vers le schéma dwh : chaque service reste propriétaire de ses données
-- (ADR-008, règle 1). Les références inter-services (tronçon, épisode) sont des identifiants textuels.
-- Cycle de vie d'une alerte : CREATED → NOTIFIED → ACKNOWLEDGED → RESOLVED (ADR-028).

CREATE TABLE alertes.alert_rule (
    rule_id    text PRIMARY KEY CHECK (rule_id ~ '^[a-z0-9_.-]{3,60}$'),
    kind       text NOT NULL CHECK (kind IN ('CONGESTION', 'TRAFFIC_ANOMALY', 'SENSOR_FAULT')),
    enabled    boolean NOT NULL DEFAULT true,
    params     jsonb NOT NULL DEFAULT '{}'::jsonb,
    min_gap_s  integer NOT NULL DEFAULT 300 CHECK (min_gap_s >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE alertes.alert_rule IS 'Règles d''alerte configurables. min_gap_s : délai minimal entre deux notifications pour un même tronçon.';

CREATE TABLE alertes.alert (
    alert_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id         text NOT NULL REFERENCES alertes.alert_rule (rule_id),
    kind            text NOT NULL CHECK (kind IN ('CONGESTION', 'TRAFFIC_ANOMALY', 'SENSOR_FAULT')),
    road_segment_id text NOT NULL,
    intersection_id text NOT NULL,
    episode_id      uuid,
    run_id          text NOT NULL,
    source_type     text NOT NULL CHECK (source_type IN ('REAL_LIVE', 'REAL_HISTORICAL', 'SIMULATED')),
    severity        text NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    cause           text NOT NULL DEFAULT 'UNKNOWN' CHECK (cause IN ('UNKNOWN', 'CONFIRMED_INCIDENT', 'ROADWORKS', 'SPECIAL_EVENT', 'SENSOR_FAULT')),
    state           text NOT NULL DEFAULT 'CREATED' CHECK (state IN ('CREATED', 'NOTIFIED', 'ACKNOWLEDGED', 'RESOLVED')),
    opened_at       timestamptz NOT NULL,
    notified_at     timestamptz,
    acknowledged_at timestamptz,
    acknowledged_by text,
    resolved_at     timestamptz,
    resolution      text CHECK (resolution IN ('AUTO', 'MANUAL')),
    correlation_id  text,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((state = 'RESOLVED') = (resolved_at IS NOT NULL)),
    CHECK ((state = 'RESOLVED') = (resolution IS NOT NULL)),
    CHECK (state NOT IN ('ACKNOWLEDGED') OR acknowledged_at IS NOT NULL),
    CHECK (resolved_at IS NULL OR resolved_at >= opened_at)
);
COMMENT ON TABLE alertes.alert IS 'Une alerte par épisode : jamais une alerte par mesure (ADR-028).';
COMMENT ON COLUMN alertes.alert.cause IS 'UNKNOWN tant qu''aucun événement confirmé n''existe : une baisse de vitesse ne prouve pas un accident.';

-- Anti-doublon : au plus une alerte ouverte par type, tronçon et exécution.
CREATE UNIQUE INDEX alert_one_open_per_segment_idx
    ON alertes.alert (kind, road_segment_id, run_id)
    WHERE state <> 'RESOLVED';
CREATE INDEX alert_state_opened_idx ON alertes.alert (state, opened_at DESC);
CREATE INDEX alert_segment_idx ON alertes.alert (road_segment_id, opened_at DESC);

CREATE TABLE alertes.alert_history (
    history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_id   uuid NOT NULL REFERENCES alertes.alert (alert_id) ON DELETE CASCADE,
    from_state text CHECK (from_state IN ('CREATED', 'NOTIFIED', 'ACKNOWLEDGED', 'RESOLVED')),
    to_state   text NOT NULL CHECK (to_state IN ('CREATED', 'NOTIFIED', 'ACKNOWLEDGED', 'RESOLVED')),
    changed_at timestamptz NOT NULL DEFAULT now(),
    actor      text NOT NULL,
    details    jsonb
);
CREATE INDEX alert_history_alert_idx ON alertes.alert_history (alert_id, changed_at);

-- Motif « outbox » (ADR-009) : l'événement est écrit dans la même transaction que le changement d'état,
-- puis publié sur Kafka par un relais ; aucun événement n'est perdu si la publication échoue.
CREATE TABLE alertes.outbox_event (
    outbox_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic        text NOT NULL,
    event_key    text NOT NULL,
    event_id     text NOT NULL UNIQUE,
    payload      jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
COMMENT ON COLUMN alertes.outbox_event.event_id IS 'Identifiant de l''événement (attribut id de l''enveloppe) : unique, garantit l''idempotence côté consommateur.';
CREATE INDEX outbox_unpublished_idx ON alertes.outbox_event (created_at) WHERE published_at IS NULL;

INSERT INTO alertes.alert_rule (rule_id, kind, params, min_gap_s) VALUES
    ('congestion.persistante',  'CONGESTION',      '{"state": "CONGESTED", "min_windows": 1}'::jsonb, 300),
    ('anomalie.circulation',    'TRAFFIC_ANOMALY', '{"min_windows": 3}'::jsonb,                      600),
    ('capteur.muet',            'SENSOR_FAULT',    '{"silence_s": 60}'::jsonb,                       900);
