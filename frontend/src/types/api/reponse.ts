/**
 * Fichier généré par « npm run api:generate » depuis contracts/openapi/reponse.openapi.yaml.
 * Ne pas le modifier à la main : changer le contrat, puis régénérer.
 */

export interface paths {
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
    "/api/v1/signals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * État des feux de tous les carrefours équipés
         * @description **Schémas provisoires.** Les contrats d'événements `traffic.recommendations` et `signal.status`
         *     ne sont pas encore écrits (MS-03, MS-12) ; cette partie suivra leur rédaction.
         */
        get: operations["listSignals"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/signals/{intersection_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                intersection_id: components["parameters"]["IntersectionId"];
            };
            cookie?: never;
        };
        /** État des feux d'un carrefour */
        get: operations["getSignal"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/signals/{intersection_id}/commands": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                intersection_id: components["parameters"]["IntersectionId"];
            };
            cookie?: never;
        };
        /**
         * Historique des commandes
         * @description Lit le journal d'audit des commandes (acceptées et refusées). Tri : `requested_at` décroissant.
         */
        get: operations["listSignalCommands"];
        put?: never;
        /**
         * Envoyer une commande manuelle
         * @description La commande manuelle est prioritaire sur les recommandations. Le service de réponse extérieure
         *     applique des garde-fous : durée minimale de phase, interdiction des verts conflictuels.
         *     Une commande dangereuse est **refusée et journalisée** (`422`, code `UNSAFE_COMMAND`).
         *     Le modèle ne commande jamais seul un équipement (ADR-008, ADR-015).
         */
        post: operations["sendSignalCommand"];
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
        SignalCommand: {
            /** @enum {string} */
            action: "SET_PHASE" | "RESUME_AUTOMATIC";
            /** Format: uuid */
            command_id: string;
            duration_s?: number | null;
            intersection_id: components["schemas"]["IntersectionId"];
            phase_id?: string | null;
            reason: string;
            /** @description Renseigné si `status` vaut `REFUSED`. */
            refusal_reason?: string | null;
            requested_at: components["schemas"]["UtcDateTime"];
            requested_by: string;
            /** @enum {string} */
            status: "ACCEPTED" | "APPLIED" | "REFUSED" | "EXPIRED";
        };
        SignalCommandPage: components["schemas"]["PageInfo"] & {
            items: components["schemas"]["SignalCommand"][];
        };
        SignalCommandRequest: {
            /**
             * @description `SET_PHASE` impose une phase ; `RESUME_AUTOMATIC` rend la main aux recommandations.
             * @enum {string}
             */
            action: "SET_PHASE" | "RESUME_AUTOMATIC";
            /** @description Obligatoire avec `SET_PHASE`. */
            duration_s?: number;
            /** @description Obligatoire avec `SET_PHASE`. */
            phase_id?: string;
            /** @description Motif */
            reason: string;
        } & unknown;
        SignalPhase: {
            duration_s: number;
            /** @description Approches au vert pendant cette phase. Deux phases en conflit ne se recouvrent jamais. */
            green_approaches: ("N" | "E" | "S" | "W")[];
            /** @description Durée minimale de sécurité. */
            min_duration_s: number;
            /** @example P1 */
            phase_id: string;
        };
        /** @description Provisoire, à aligner sur le contrat `signal.status` (MS-12). */
        SignalState: {
            current_phase_id: string;
            intersection_id: components["schemas"]["IntersectionId"];
            /**
             * @description `AUTOMATIC` : suit les recommandations. `MANUAL` : commande d'un opérateur en cours.
             *     `DEGRADED_FIXED_PLAN` : retour au plan à durées fixes quand les recommandations manquent.
             * @enum {string}
             */
            mode: "AUTOMATIC" | "MANUAL" | "DEGRADED_FIXED_PLAN";
            phases: components["schemas"]["SignalPhase"][];
            provenance?: components["schemas"]["Provenance"];
            updated_at: components["schemas"]["UtcDateTime"];
        };
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
        /** @description Limite de débit atteinte ; code `RATE_LIMITED`. */
        TooManyRequests: {
            headers: {
                "Retry-After": components["headers"]["RetryAfter"];
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
    headers: {
        /** @description Secondes à attendre avant de réessayer. */
        RetryAfter: number;
    };
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
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
    listSignals: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Un état par carrefour à feux. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["SignalState"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
        };
    };
    getSignal: {
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
            /** @description État courant. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SignalState"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    listSignalCommands: {
        parameters: {
            query?: {
                /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
                cursor?: components["parameters"]["Cursor"];
                /** @description Taille de page, de 1 à 500. */
                limit?: components["parameters"]["Limit"];
            };
            header?: never;
            path: {
                intersection_id: components["parameters"]["IntersectionId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une page de commandes. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SignalCommandPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            422: components["responses"]["ValidationError"];
        };
    };
    sendSignalCommand: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                intersection_id: components["parameters"]["IntersectionId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                /**
                 * @example {
                 *       "action": "SET_PHASE",
                 *       "phase_id": "P2",
                 *       "duration_s": 30,
                 *       "reason": "Évacuation après incident confirmé"
                 *     }
                 */
                "application/json": components["schemas"]["SignalCommandRequest"];
            };
        };
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Commande acceptée ; son application se lit dans `GET /api/v1/signals/{intersection_id}`. */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SignalCommand"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            /** @description Une autre commande manuelle est en cours ; code `COMMAND_IN_PROGRESS`. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description Corps invalide (`VALIDATION_ERROR`) ou commande refusée par les garde-fous (`UNSAFE_COMMAND`). */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            429: components["responses"]["TooManyRequests"];
        };
    };
}
