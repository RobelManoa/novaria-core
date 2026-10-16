export interface Health {
  status: string;
  version: string;
  revision: string;
  environment: string;
}

export async function getHealth(): Promise<Health> {
  const response = await fetch("/api/v1/health");
  if (!response.ok) throw new Error(`API indisponible (${response.status})`);
  return (await response.json()) as Health;
}
