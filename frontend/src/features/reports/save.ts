/**
 * Enregistre un fichier déjà lu : le navigateur propose le téléchargement sous `fileName`. L'adresse
 * temporaire n'est libérée qu'après le clic, puis aussitôt : le navigateur a déjà pris le fichier.
 */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
