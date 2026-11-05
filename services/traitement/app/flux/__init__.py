"""Traitement en flux (MS-09) : consomme `iot.raw`, agrège, publie `traffic.indicators`.

Le cœur (`cleaning`, `windows`, `classifier`, `indicators`) ne connaît ni Kafka, ni PostgreSQL,
ni MongoDB : il reçoit des octets et rend des décisions. `processor` le branche à des ports ;
`adapters/` fournit Kafka, l'entrepôt et MongoDB. Voir docs/03-donnees/flux.md.
"""
