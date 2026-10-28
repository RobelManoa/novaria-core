/**
 * Fichier généré par « npm run api:generate » depuis contracts/openapi/alerte.openapi.yaml.
 * Ne pas le modifier à la main : changer le contrat, puis régénérer.
 */

export interface paths {
    "/api/v1/alert-rules": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Lister les règles d'alerte */
        get: operations["listAlertRules"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alert-rules/{rule_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Activer, désactiver ou régler une règle */
        patch: operations["updateAlertRule"];
        trace?: never;
    };
    "/api/v1/alerts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Lister les alertes
         * @description Une alerte par épisode, jamais une par mesure (ADR-028). Tri : `opened_at` décroissant.
         */
        get: operations["listAlerts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: components["parameters"]["AlertId"];
            };
            cookie?: never;
        };
        /** Lire une alerte et son historique */
        get: operations["getAlert"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}/acknowledge": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: components["parameters"]["AlertId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Acquitter une alerte
         * @description Passe l'alerte à `ACKNOWLEDGED` ; l'appelant devient `acknowledged_by`. Possible depuis `CREATED` ou `NOTIFIED`. Répéter l'appel sur une alerte déjà acquittée renvoie `200` sans effet.
         */
        post: operations["acknowledgeAlert"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: components["parameters"]["AlertId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Résoudre une alerte à la main
         * @description Passe l'alerte à `RESOLVED` avec `resolution` égale à `MANUAL`. La résolution automatique se fait à la clôture de l'épisode, sans appel d'API.
         */
        post: operations["resolveAlert"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/events/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Flux d'événements en direct (SSE)
         * @description Connexion longue au format *Server-Sent Events*. Proposition : SSE plutôt que WebSocket, car la
         *     diffusion va dans un seul sens et OpenAPI sait décrire SSE (choix à confirmer, MS-11).
         *
         *     Chaque message a un `event` et un `data` JSON :
         *
         *     | `event` | `data` |
         *     |---|---|
         *     | `alert.state_changed` | schéma `Alert` |
         *     | `signal.status` | schéma `SignalState` |
         *     | `heartbeat` | `{ "time": "..." }` toutes les 30 s |
         *
         *     Le navigateur ne peut pas poser d'en-tête `Authorization` avec `EventSource` : le client utilise
         *     `fetch` avec lecture du flux, ou la passerelle fournit un jeton à usage unique (point ouvert).
         */
        get: operations["streamEvents"];
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
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** @description Mêmes valeurs que l'événement `novaria.alert.state_changed.v1` et la table `alertes.alert`. */
        Alert: {
            acknowledged_at?: components["schemas"]["UtcDateTime"] | null;
            /** @description Nom d'utilisateur de l'opérateur. */
            acknowledged_by?: string | null;
            /** Format: uuid */
            alert_id: string;
            cause: components["schemas"]["AlertCause"];
            /** Format: uuid */
            episode_id?: string | null;
            intersection_id: components["schemas"]["IntersectionId"];
            kind: components["schemas"]["AlertKind"];
            notified_at?: components["schemas"]["UtcDateTime"] | null;
            opened_at: components["schemas"]["UtcDateTime"];
            provenance: components["schemas"]["Provenance"];
            /**
             * @description Renseigné si et seulement si `state` vaut `RESOLVED`.
             * @enum {string|null}
             */
            resolution: "AUTO" | "MANUAL" | null;
            /** @description Renseigné si et seulement si `state` vaut `RESOLVED`. */
            resolved_at: components["schemas"]["UtcDateTime"] | null;
            road_segment_id: components["schemas"]["RoadSegmentId"];
            rule_id: components["schemas"]["RuleId"];
            severity: components["schemas"]["Severity"];
            state: components["schemas"]["AlertState"];
        };
        /**
         * @description `UNKNOWN` tant qu'aucun événement confirmé n'existe : une baisse de vitesse ne prouve pas un accident.
         * @enum {string}
         */
        AlertCause: "UNKNOWN" | "CONFIRMED_INCIDENT" | "ROADWORKS" | "SPECIAL_EVENT" | "SENSOR_FAULT";
        AlertDetail: components["schemas"]["Alert"] & {
            history: components["schemas"]["AlertHistoryEntry"][];
        };
        AlertHistoryEntry: {
            /** @description Nom d'utilisateur ou `system`. */
            actor: string;
            changed_at: components["schemas"]["UtcDateTime"];
            comment?: string | null;
            /** @enum {string|null} */
            from_state: "CREATED" | "NOTIFIED" | "ACKNOWLEDGED" | "RESOLVED" | null;
            to_state: components["schemas"]["AlertState"];
        };
        /** @enum {string} */
        AlertKind: "CONGESTION" | "TRAFFIC_ANOMALY" | "SENSOR_FAULT";
        AlertPage: components["schemas"]["PageInfo"] & {
            items: components["schemas"]["Alert"][];
        };
        AlertRule: {
            enabled: boolean;
            kind: components["schemas"]["AlertKind"];
            /** @description Délai minimal entre deux notifications pour un même tronçon. */
            min_gap_s: number;
            /** @description Paramètres propres à la règle (par exemple `silence_s` pour `capteur.muet`). */
            params: {
                [key: string]: unknown;
            };
            rule_id: components["schemas"]["RuleId"];
            updated_at: components["schemas"]["UtcDateTime"];
        };
        AlertRuleUpdate: {
            enabled?: boolean;
            min_gap_s?: number;
            params?: {
                [key: string]: unknown;
            };
        };
        /** @enum {string} */
        AlertState: "CREATED" | "NOTIFIED" | "ACKNOWLEDGED" | "RESOLVED";
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
        /** @example INT_01 */
        IntersectionId: string;
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
        /** @example ROAD_001 */
        RoadSegmentId: string;
        /** @example congestion.persistante */
        RuleId: string;
        /** @enum {string} */
        Severity: "INFO" | "WARNING" | "CRITICAL";
        /** @enum {string} */
        SourceType: "SIMULATED" | "REAL_HISTORICAL" | "REAL_LIVE";
        /**
         * Format: date-time
         * @description Date et heure ISO 8601 en UTC, fuseau explicite (`Z`).
         * @example 2026-10-20T08:20:00Z
         */
        UtcDateTime: string;
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
        AlertId: string;
        /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
        Cursor: string;
        /** @description Taille de page, de 1 à 500. */
        Limit: number;
    };
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    listAlertRules: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Règles configurées (`congestion.persistante`, `anomalie.circulation`, `capteur.muet`). */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["AlertRule"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    updateAlertRule: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                rule_id: components["schemas"]["RuleId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AlertRuleUpdate"];
            };
        };
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Règle modifiée. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertRule"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["ValidationError"];
        };
    };
    listAlerts: {
        parameters: {
            query?: {
                /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
                cursor?: components["parameters"]["Cursor"];
                intersection_id?: components["schemas"]["IntersectionId"];
                kind?: components["schemas"]["AlertKind"];
                /** @description Taille de page, de 1 à 500. */
                limit?: components["parameters"]["Limit"];
                opened_from?: components["schemas"]["UtcDateTime"];
                opened_to?: components["schemas"]["UtcDateTime"];
                road_segment_id?: components["schemas"]["RoadSegmentId"];
                severity?: components["schemas"]["Severity"];
                state?: components["schemas"]["AlertState"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une page d'alertes. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
        };
    };
    getAlert: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: components["parameters"]["AlertId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Alerte avec ses changements d'état. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertDetail"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    acknowledgeAlert: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: components["parameters"]["AlertId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Alerte à l'état `ACKNOWLEDGED`. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Alert"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            /** @description Alerte déjà résolue ; code `INVALID_STATE_TRANSITION`. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
        };
    };
    resolveAlert: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: components["parameters"]["AlertId"];
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": {
                    /** @description Motif de la résolution, conservé dans l'historique. */
                    comment?: string;
                };
            };
        };
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Alerte à l'état `RESOLVED`. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Alert"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            /** @description Alerte déjà résolue ; code `INVALID_STATE_TRANSITION`. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            422: components["responses"]["ValidationError"];
        };
    };
    streamEvents: {
        parameters: {
            query?: {
                /** @description Types à recevoir, séparés par des virgules. Tous si absent. */
                types?: ("alert.state_changed" | "signal.status")[];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Flux ouvert. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example event: alert.state_changed
                     *     data: {"alert_id":"3f6c7f1e-0d2b-4c55-9c0e-6a1a4b3f2d10","state":"NOTIFIED"}
                     */
                    "text/event-stream": string;
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
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
}
