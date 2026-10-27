export declare const SERVICES: string[];
/** Contenu attendu de chaque fichier généré, par chemin relatif à frontend/. */
export declare function renderApiTypes(): Promise<Record<string, string>>;
/** Fichiers générés absents ou différents du contrat. */
export declare function outOfDate(): Promise<string[]>;
/** Services qui ont un contrat et que la passerelle expose (tous sauf collecte). */
export declare function exposedContracts(): Promise<string[]>;
