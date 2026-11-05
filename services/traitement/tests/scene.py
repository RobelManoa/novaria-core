"""Un client de test et ses comptes : de quoi provoquer une erreur précise (BE-06)."""

from dataclasses import dataclass

from app.models import Role
from tests.fakes import bearer

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


@dataclass
class Scene:
    client: object
    repo: object

    def token(self, role: Role) -> dict[str, str]:
        """Jeton d'un compte de ce rôle ; le compte est créé au premier appel."""
        name = f"compte-{role.value}"
        account = self.repo.get_by_username(name) or self.repo.make(name, role)
        return bearer(account)

    def request(self, method: str, path: str, *, role: Role | None = None, **kwargs):
        headers = self.token(role) if role else {}
        url = path.replace("{user_id}", UNKNOWN_ID).replace("{indicator_id}", "inconnu")
        return self.client.request(method.upper(), url, headers=headers, **kwargs)
