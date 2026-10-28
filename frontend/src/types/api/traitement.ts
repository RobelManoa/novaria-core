/**
 * Fichier généré par « npm run api:generate » depuis contracts/openapi/traitement.openapi.yaml.
 * Ne pas le modifier à la main : changer le contrat, puis régénérer.
 */

export interface paths {
    "/api/v1/forecasts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Prévisions de vitesse à court terme
         * @description Ratio de vitesse prévu pour chaque tronçon demandé. Tant qu'aucun modèle ne bat la référence
         *     (persistance ou moyenne glissante), la réponse l'indique par `model.kind` égal à `REFERENCE`
         *     (ADR-015, IA-06). Un modèle entraîné sur le simulateur apprend le simulateur : `provenance`
         *     le rappelle.
         */
        get: operations["listForecasts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sonde de santé
         * @description Dit que le service tourne. Renvoie la version et la révision Git du code déployé.
         */
        get: operations["getHealth"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/indicators": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Lister les indicateurs par fenêtre
         * @description Un indicateur = un tronçon, une fenêtre de 1 ou 5 minutes, un run. Lecture seule, depuis les
         *     vues de l'entrepôt (séparation écriture et lecture, ADR-014). Tri : `window_start` décroissant.
         */
        get: operations["listIndicators"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/indicators/{indicator_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Lire un indicateur */
        get: operations["getIndicator"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/indicators/latest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dernier indicateur de chaque tronçon
         * @description Photographie courante du réseau pour le Tableau de bord : une fenêtre de 1 minute par tronçon.
         */
        get: operations["listLatestIndicators"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intersections": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Lister les carrefours */
        get: operations["listIntersections"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/intersections/{intersection_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                intersection_id: components["parameters"]["IntersectionId"];
            };
            cookie?: never;
        };
        /** Lire un carrefour et ses tronçons */
        get: operations["getIntersection"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/road-segments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Lister les tronçons
         * @description Un tronçon est une approche de carrefour ; c'est l'unité d'analyse de la circulation.
         */
        get: operations["listRoadSegments"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * @description État stabilisé d'un tronçon (hystérésis, ADR-028).
         *     `UNKNOWN` : données insuffisantes (complétude inférieure à 0,5).
         * @enum {string}
         */
        CongestionState: "UNKNOWN" | "FREE_FLOW" | "SLOW" | "CONGESTED";
        Forecast: {
            horizon_min: number;
            issued_at: components["schemas"]["UtcDateTime"];
            model: {
                /**
                 * @description `REFERENCE` : persistance ou moyenne glissante. `MODEL` : modèle entraîné qui a battu la référence.
                 * @enum {string}
                 */
                kind: "REFERENCE" | "MODEL";
                name: string;
                /** @description Identifiant du run d'entraînement (`model_runs`), qui remonte au code et aux données. */
                run_id?: string | null;
                version: string;
            };
            predicted_speed_ratio: number;
            predicted_state?: components["schemas"]["CongestionState"];
            provenance: components["schemas"]["Provenance"];
            road_segment_id: components["schemas"]["RoadSegmentId"];
            /** @description Instant prévu, égal à `issued_at` plus `horizon_min`. */
            target_time: components["schemas"]["UtcDateTime"];
        };
        Health: {
            /** @example local */
            environment: string;
            /** @description Révision Git du code construit. */
            revision: string;
            /** @enum {string} */
            status: "ok";
            /** @description Version du produit déployé. */
            version: string;
        };
        /**
         * @description Un tronçon, une fenêtre, un run. Mêmes champs et mêmes unités que l'événement `novaria.traffic.indicator.v1`.
         * @example {
         *       "indicator_id": "run-demo-0001:ROAD_001:60:1792484400000",
         *       "road_segment_id": "ROAD_001",
         *       "intersection_id": "INT_01",
         *       "window_start": "2026-10-20T08:20:00Z",
         *       "window_size_s": 60,
         *       "vehicle_count": 9,
         *       "flow_veh_per_min": 9,
         *       "average_speed_kmh": 11.4,
         *       "occupancy_rate": 0.78,
         *       "max_queue_length_m": 140,
         *       "speed_ratio": 0.228,
         *       "sample_count": 6,
         *       "expected_sample_count": 6,
         *       "completeness": 1,
         *       "congestion_state": "CONGESTED",
         *       "classifier_version": "regles-v0",
         *       "provenance": {
         *         "source_type": "SIMULATED",
         *         "run_id": "run-demo-0001",
         *         "scenario_id": "heure-de-pointe",
         *         "seed": 42
         *       }
         *     }
         */
        Indicator: {
            /** @description Moyenne pondérée par le nombre de véhicules ; `null` si aucun véhicule. */
            average_speed_kmh: number | null;
            /** @description Version de la règle ou du modèle qui a produit l'état (`regles-v0`). */
            classifier_version: string;
            /** @description min(1, sample_count / expected_sample_count). */
            completeness?: number;
            congestion_state: components["schemas"]["CongestionState"];
            expected_sample_count: number;
            flow_veh_per_min: number;
            /** @description Identifiant stable */
            indicator_id: string;
            intersection_id: components["schemas"]["IntersectionId"];
            max_queue_length_m?: number | null;
            occupancy_rate?: number | null;
            provenance: components["schemas"]["Provenance"];
            road_segment_id: components["schemas"]["RoadSegmentId"];
            sample_count: number;
            /** @description Vitesse moyenne divisée par la vitesse fluide du tronçon ; `null` si la vitesse est `null`. */
            speed_ratio: number | null;
            vehicle_count: number;
            window_size_s: components["schemas"]["WindowSize"];
            /** @description Début de la fenêtre ; elle couvre [window_start, window_start + window_size_s[. */
            window_start: components["schemas"]["UtcDateTime"];
        };
        IndicatorPage: components["schemas"]["PageInfo"] & {
            items: components["schemas"]["Indicator"][];
        };
        Intersection: {
            has_traffic_light: boolean;
            intersection_id: components["schemas"]["IntersectionId"];
            /** @description Vide pour le réseau fictif de démonstration. */
            latitude?: number | null;
            longitude?: number | null;
            name: string;
        };
        IntersectionDetail: components["schemas"]["Intersection"] & {
            road_segments: components["schemas"]["RoadSegment"][];
        };
        /** @example INT_01 */
        IntersectionId: string;
        IntersectionPage: components["schemas"]["PageInfo"] & {
            items: components["schemas"]["Intersection"][];
        };
        PageInfo: {
            /** @description Curseur de la page suivante ; `null` sur la dernière page. */
            next_cursor: string | null;
        };
        /** @description Corps unique de toute erreur (RFC 9457, `application/problem+json`). */
        Problem: {
            /**
             * @description Code stable lisible par une machine.
             * @enum {string}
             */
            code: "UNAUTHENTICATED" | "INVALID_CREDENTIALS" | "FORBIDDEN" | "NOT_FOUND" | "CONFLICT" | "VALIDATION_ERROR" | "INVALID_STATE_TRANSITION" | "COMMAND_IN_PROGRESS" | "UNSAFE_COMMAND" | "RATE_LIMITED" | "FORECAST_UNAVAILABLE" | "UPSTREAM_UNAVAILABLE" | "INTERNAL_ERROR";
            /** @description Identifiant de corrélation de la requête, à citer dans un signalement. */
            correlation_id: string;
            /** @description Explication pour une personne. Ne contient ni secret, ni trace d'exécution. */
            detail?: string;
            /** @description Un élément par champ invalide (`VALIDATION_ERROR`). */
            errors?: {
                /** @description Chemin du champ, par exemple `body.password` ou `query.limit`. */
                field: string;
                message: string;
            }[];
            /** @description Code HTTP, répété dans le corps. */
            status: number;
            /** @description Résumé court, identique pour un même `code`. */
            title: string;
            /**
             * Format: uri
             * @description Identifie la famille d'erreur.
             */
            type: string;
        };
        /** @description Origine de la donnée. Une donnée simulée n'est jamais présentée comme réelle (ADR-027). */
        Provenance: {
            /** @description Obligatoire si `REAL_HISTORICAL`. */
            dataset_id?: string;
            /** @description `live`, identifiant d'un run du simulateur ou d'un jeu historique. */
            run_id: string;
            /** @description Obligatoire si `SIMULATED`. */
            scenario_id?: string;
            /** @description Obligatoire si `SIMULATED` ; rend le run reproductible. */
            seed?: number;
            source_type: components["schemas"]["SourceType"];
        } & (unknown & unknown);
        RoadSegment: {
            /**
             * @description Côté d'où arrive la circulation.
             * @enum {string}
             */
            approach: "N" | "E" | "S" | "W";
            /** @description Vitesse en circulation fluide, dénominateur du ratio de vitesse. */
            free_flow_speed_kmh: number;
            intersection_id: components["schemas"]["IntersectionId"];
            lane_count: number;
            length_m: number;
            road_segment_id: components["schemas"]["RoadSegmentId"];
            /** @enum {string} */
            road_type: "MOTORWAY" | "ARTERIAL" | "COLLECTOR" | "LOCAL";
            speed_limit_kmh: number;
        };
        /** @example ROAD_001 */
        RoadSegmentId: string;
        RoadSegmentPage: components["schemas"]["PageInfo"] & {
            items: components["schemas"]["RoadSegment"][];
        };
        /** @enum {string} */
        SourceType: "SIMULATED" | "REAL_HISTORICAL" | "REAL_LIVE";
        /**
         * Format: date-time
         * @description Date et heure ISO 8601 en UTC, fuseau explicite (`Z`).
         * @example 2026-10-20T08:20:00Z
         */
        UtcDateTime: string;
        /**
         * @description Taille de la fenêtre en secondes.
         * @enum {integer}
         */
        WindowSize: 60 | 300;
    };
    responses: {
        /** @description Rôle insuffisant pour cette opération ; code `FORBIDDEN`. */
        Forbidden: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "https://novaria.local/problems/forbidden",
                 *       "title": "Droit insuffisant",
                 *       "status": 403,
                 *       "code": "FORBIDDEN",
                 *       "detail": "Le rôle `viewer` ne permet pas cette opération ; rôle requis `operator`.",
                 *       "correlation_id": "4c1d8f20-6e19-4a0c-bb6b-90d6f4f3a0de"
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Ressource inconnue ; code `NOT_FOUND`. */
        NotFound: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Erreur interne ou service en aval indisponible ; code `INTERNAL_ERROR` ou `UPSTREAM_UNAVAILABLE`. Aucun détail technique n'est exposé. */
        ServerError: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Jeton absent, invalide ou expiré ; code `UNAUTHENTICATED`. */
        Unauthorized: {
            headers: {
                "WWW-Authenticate"?: string;
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "https://novaria.local/problems/unauthenticated",
                 *       "title": "Authentification requise",
                 *       "status": 401,
                 *       "code": "UNAUTHENTICATED",
                 *       "detail": "Jeton absent, invalide ou expiré.",
                 *       "correlation_id": "7d2f0c9e-3b0a-4f0e-9a52-1c5c3c4e8a10"
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description Entrée invalide ; code `VALIDATION_ERROR`. `errors` liste chaque champ fautif. */
        ValidationError: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                /**
                 * @example {
                 *       "type": "https://novaria.local/problems/validation-error",
                 *       "title": "Entrée invalide",
                 *       "status": 422,
                 *       "code": "VALIDATION_ERROR",
                 *       "detail": "1 champ invalide.",
                 *       "errors": [
                 *         {
                 *           "field": "query.window_size_s",
                 *           "message": "La valeur doit être 60 ou 300."
                 *         }
                 *       ],
                 *       "correlation_id": "9a3b2c10-5d6e-4f70-8a91-b2c3d4e5f607"
                 *     }
                 */
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
    };
    parameters: {
        /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
        Cursor: string;
        IntersectionId: components["schemas"]["IntersectionId"];
        /** @description Taille de page, de 1 à 500. */
        Limit: number;
    };
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    listForecasts: {
        parameters: {
            query?: {
                /** @description Horizon de prévision en minutes, de 5 à 60. Défaut 15. */
                horizon_min?: number;
                /** @description Un ou plusieurs tronçons (paramètre répété). Tous les tronçons si absent. */
                road_segment_id?: components["schemas"]["RoadSegmentId"][];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une prévision par tronçon. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Forecast"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
            /** @description Modèle et référence indisponibles ; code `FORECAST_UNAVAILABLE`. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    getHealth: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Service en ligne. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "status": "ok",
                     *       "version": "0.1.0",
                     *       "revision": "4d1ca55",
                     *       "environment": "local"
                     *     }
                     */
                    "application/json": components["schemas"]["Health"];
                };
            };
        };
    };
    listIndicators: {
        parameters: {
            query?: {
                congestion_state?: components["schemas"]["CongestionState"];
                /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
                cursor?: components["parameters"]["Cursor"];
                /** @description Début de période inclus (`window_start >= from`), UTC. */
                from?: components["schemas"]["UtcDateTime"];
                intersection_id?: components["schemas"]["IntersectionId"];
                /** @description Taille de page, de 1 à 500. */
                limit?: components["parameters"]["Limit"];
                road_segment_id?: components["schemas"]["RoadSegmentId"];
                /** @description Ne garder que ce run (exécution du simulateur ou jeu historique). */
                run_id?: string;
                source_type?: components["schemas"]["SourceType"];
                /** @description Fin de période exclue (`window_start < to`), UTC. Doit être postérieure à `from`. */
                to?: components["schemas"]["UtcDateTime"];
                /** @description Taille de fenêtre. Défaut 60 (l'état d'alerte vient des fenêtres de 1 minute). */
                window_size_s?: components["schemas"]["WindowSize"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une page d'indicateurs. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IndicatorPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
        };
    };
    getIndicator: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /**
                 * @description Identifiant de l'indicateur, égal à l'attribut `id` de l'événement `novaria.traffic.indicator.v1`.
                 * @example run-demo-0001:ROAD_001:60:1792484400000
                 */
                indicator_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Indicateur. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Indicator"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    listLatestIndicators: {
        parameters: {
            query?: {
                intersection_id?: components["schemas"]["IntersectionId"];
                /** @description Run à lire. Par défaut, le run le plus récent. */
                run_id?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Un indicateur par tronçon. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Indicator"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
        };
    };
    listIntersections: {
        parameters: {
            query?: {
                /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
                cursor?: components["parameters"]["Cursor"];
                /** @description Ne garder que les carrefours à feux (`true`) ou sans feux (`false`). */
                has_traffic_light?: boolean;
                /** @description Taille de page, de 1 à 500. */
                limit?: components["parameters"]["Limit"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une page de carrefours. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntersectionPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
        };
    };
    getIntersection: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                intersection_id: components["parameters"]["IntersectionId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Carrefour avec ses quatre approches au plus. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntersectionDetail"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    listRoadSegments: {
        parameters: {
            query?: {
                /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
                cursor?: components["parameters"]["Cursor"];
                intersection_id?: components["schemas"]["IntersectionId"];
                /** @description Taille de page, de 1 à 500. */
                limit?: components["parameters"]["Limit"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une page de tronçons. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RoadSegmentPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
        };
    };
}
