/** Seule part de Node utilisée par les parcours : l'environnement (les types Node ne sont pas installés). */
declare const process: { env: Record<string, string | undefined> };
