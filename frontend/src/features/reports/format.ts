import { formatNumber } from "@/features/dashboard/format";

/** Taille d'un fichier en français (kilooctet, mégaoctet : puissances de 1000), par exemple « 12,3 ko ». */
export function formatFileSize(bytes: number): string {
  if (bytes < 1000) return `${formatNumber(bytes, 0)} o`;
  if (bytes < 1_000_000) return `${formatNumber(bytes / 1000, 1)} ko`;
  return `${formatNumber(bytes / 1_000_000, 1)} Mo`;
}

/** Début de l'empreinte SHA-256, assez long pour reconnaître un fichier ; l'empreinte entière reste dans l'infobulle. */
export function shortHash(sha256: string): string {
  return sha256.slice(0, 12);
}
