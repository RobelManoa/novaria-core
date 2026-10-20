-- 0004 · Données de référence de l'entrepôt : origines, états de circulation, calendrier.

INSERT INTO dwh.dim_source (source_type, description) VALUES
    ('SIMULATED',       'Donnée produite par le simulateur ou un générateur : jamais présentée comme une mesure réelle.'),
    ('REAL_HISTORICAL', 'Observation réelle issue d''un jeu de données ouvert historique, avec référence de la source.'),
    ('REAL_LIVE',       'Mesure réelle d''un capteur en service (hors périmètre du projet : prévu pour la suite d''UrbanHub).');

INSERT INTO dwh.dim_congestion_state (state_code, severity_rank, label_fr) VALUES
    ('UNKNOWN',    0, 'Inconnu'),
    ('FREE_FLOW',  1, 'Fluide'),
    ('SLOW',       2, 'Ralenti'),
    ('CONGESTED',  3, 'Congestionné');

-- Calendrier de 2012 à 2030 : couvre les jeux historiques envisagés (2012 à 2018) et la période du projet.
INSERT INTO dwh.dim_date (date_key, full_date, year, month, day, iso_day_of_week, iso_week, is_weekend)
SELECT (extract(year FROM d)::integer * 10000) + (extract(month FROM d)::integer * 100) + extract(day FROM d)::integer,
       d::date,
       extract(year FROM d)::smallint,
       extract(month FROM d)::smallint,
       extract(day FROM d)::smallint,
       extract(isodow FROM d)::smallint,
       extract(week FROM d)::smallint,
       extract(isodow FROM d) IN (6, 7)
FROM generate_series('2012-01-01'::date, '2030-12-31'::date, interval '1 day') AS g(d);
