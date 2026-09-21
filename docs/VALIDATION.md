# Validation de la livraison V0.6

Vérifié le 21 septembre 2026 dans cet environnement Linux / Python 3.12.14.

## Résultats

- `python -m pytest -q` : **46 passed** en 4,64 secondes.
- `python -m ruff check .` : **All checks passed**.
- `python -m ruff format --check .` : conforme.
- Construction d’une wheel Python : réussie.
- Démo réelle : worktree détaché, patch généré et deux tests unittest réussis.
- Rendu terminal : aperçu Rich exporté, contrôlé visuellement ; test automatisé de largeur 48 colonnes.
- API : authentification, pagination, événements et interdiction des mutations vérifiés.

Une dépréciation provenant de Starlette/AnyIO est signalée par TestClient ; aucun test ne manque à cause de cet avertissement.

## Limites de validation

- Aucun appel OpenAI réel : contrat SDK simulé, aucune clé utilisateur utilisée.
- Windows/PowerShell documenté mais non exécuté sur Windows ; comportements natifs, rendu et taskkill restent à vérifier sur ta machine.
- Les modules historiques V0.5 absents de l’archive empêchent une validation de toute l’application historique.
- Ce sont des tests de fonctionnement et de protections ciblées, pas une certification de sécurité.

## Versions testées

| Package | Version |
|---|---|
| fastapi | 0.141.1 |
| starlette | 1.6.0 |
| typer | 0.27.2 |
| rich | 14.3.4 |
| pydantic | 2.13.5 |
| uvicorn | 0.53.0 |
| openai | 2.54.0 |
| pytest | 9.1.1 |
| httpx | 0.28.1 |
| ruff | 0.16.8 |
