/**
 * Fichier généré par « npm run api:generate » depuis contracts/openapi/api-metier.openapi.yaml.
 * Ne pas le modifier à la main : changer le contrat, puis régénérer.
 */

export interface paths {
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Ouvrir une session
         * @description Vérifie les identifiants et émet un jeton d'accès. Limité en débit (voir `429`).
         */
        post: operations["login"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Identité de l'appelant */
        get: operations["getCurrentUser"];
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
    "/api/v1/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Lister les utilisateurs */
        get: operations["listUsers"];
        put?: never;
        /** Créer un utilisateur */
        post: operations["createUser"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/users/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: components["parameters"]["UserId"];
            };
            cookie?: never;
        };
        /** Lire un utilisateur */
        get: operations["getUser"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Modifier le rôle, l'état ou le mot de passe
         * @description Seuls les champs fournis changent. Un administrateur ne peut pas retirer son propre rôle `admin` (`409`).
         */
        patch: operations["updateUser"];
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
        LoginRequest: {
            password: string;
            username: string;
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
        /** @enum {string} */
        Role: "viewer" | "operator" | "admin";
        Token: {
            access_token: string;
            /** @description Durée de vie en secondes. */
            expires_in: number;
            /** @enum {string} */
            token_type: "bearer";
        };
        User: {
            created_at: components["schemas"]["UtcDateTime"];
            is_active: boolean;
            role: components["schemas"]["Role"];
            /** Format: uuid */
            user_id: string;
            username: string;
        };
        UserCreate: {
            password: string;
            role: components["schemas"]["Role"];
            username: string;
        };
        UserPage: components["schemas"]["PageInfo"] & {
            items: components["schemas"]["User"][];
        };
        UserUpdate: {
            is_active?: boolean;
            password?: string;
            role?: components["schemas"]["Role"];
        };
        /**
         * Format: date-time
         * @description Date et heure ISO 8601 en UTC, fuseau explicite (`Z`).
         * @example 2026-10-20T08:20:00Z
         */
        UtcDateTime: string;
    };
    responses: {
        /** @description État incompatible avec la demande (doublon, règle de gestion) ; code `CONFLICT`. */
        Conflict: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
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
        /** @description Taille de page, de 1 à 500. */
        Limit: number;
        UserId: string;
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
    login: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                /**
                 * @example {
                 *       "username": "operateur1",
                 *       "password": "mot-de-passe-d-exemple"
                 *     }
                 */
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Jeton émis. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "access_token": "eyJhbGciOi...",
                     *       "token_type": "bearer",
                     *       "expires_in": 1800
                     *     }
                     */
                    "application/json": components["schemas"]["Token"];
                };
            };
            /** @description Identifiants inconnus ou compte désactivé. Le message ne dit pas lequel des deux. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    /**
                     * @example {
                     *       "type": "https://novaria.local/problems/invalid-credentials",
                     *       "title": "Identifiants invalides",
                     *       "status": 401,
                     *       "code": "INVALID_CREDENTIALS",
                     *       "detail": "Identifiant ou mot de passe incorrect.",
                     *       "correlation_id": "7d2f0c9e-3b0a-4f0e-9a52-1c5c3c4e8a10"
                     *     }
                     */
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            422: components["responses"]["ValidationError"];
            429: components["responses"]["TooManyRequests"];
        };
    };
    getCurrentUser: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Utilisateur associé au jeton. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Unauthorized"];
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
    listUsers: {
        parameters: {
            query?: {
                /** @description Curseur opaque lu dans `next_cursor` de la page précédente. */
                cursor?: components["parameters"]["Cursor"];
                /** @description Taille de page, de 1 à 500. */
                limit?: components["parameters"]["Limit"];
                /** @description Ne garder que ce rôle. */
                role?: components["schemas"]["Role"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Une page d'utilisateurs. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            422: components["responses"]["ValidationError"];
        };
    };
    createUser: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserCreate"];
            };
        };
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Utilisateur créé. */
            201: {
                headers: {
                    /** @description Adresse de la ressource créée. */
                    Location?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["ValidationError"];
        };
    };
    getUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: components["parameters"]["UserId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Utilisateur. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
        };
    };
    updateUser: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: components["parameters"]["UserId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserUpdate"];
            };
        };
        responses: {
            "5XX": components["responses"]["ServerError"];
            /** @description Utilisateur modifié. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            401: components["responses"]["Unauthorized"];
            403: components["responses"]["Forbidden"];
            404: components["responses"]["NotFound"];
            409: components["responses"]["Conflict"];
            422: components["responses"]["ValidationError"];
        };
    };
}
