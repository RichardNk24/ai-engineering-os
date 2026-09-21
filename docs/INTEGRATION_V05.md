# Raccordement V0.5 → V0.6

La V0.5 jointe est un upgrade partiel. Le package V0.6 est indépendant du namespace `aeo` pour rester exécutable et ne pas remplacer les modules historiques absents de l'archive.

## 1. Installer dans l'environnement existant

Dans ton dépôt AEO complet, avec son environnement Python actif :

```powershell
python -m pip install -e "C:\chemin\vers\aeo-v0.6-workbench[ai]"
python -m aeo_workbench.cli version
```

Si tu gères ce dépôt avec uv, ajoute plutôt la dépendance locale au projet, afin qu'un prochain `uv sync` ne la retire pas :

```powershell
uv add --editable C:\chemin\vers\aeo-v0.6-workbench --extra ai
uv run aeo6 version
```

Un chemin éditable doit rester présent sur le disque. Pour distribuer le produit, construis une wheel plutôt qu'une dépendance à ton répertoire personnel. N'installe pas la nouvelle archive en écrasant l'ancien `src/aeo`.

## 2. Un seul nom de produit : `aeo workbench`

Dans `src/aeo/cli.py`, ajoute cet import :

```python
from aeo_workbench.cli import app as workbench_app
```

Puis, **après la création de `app = typer.Typer(...)`**, ajoute :

```python
app.add_typer(workbench_app, name="workbench")
```

Tu obtiens :

```powershell
uv run aeo workbench init
uv run aeo workbench demo
uv run aeo workbench --json runs
uv run aeo workbench feature "Ma tâche" --write src/module.py --dry-run
```

Les commandes V0.5 (`aeo review`, `aeo guard`, `aeo task`, `aeo stats`) gardent leur comportement. Les nouvelles commandes utilisent le système visuel Workbench ; les sorties historiques ne sont pas automatiquement redessinées. Ce montage de sous-application est testé avec Typer, mais l'application historique complète ne peut pas être exécutée avec les seuls fichiers fournis.

## 3. Brancher les routes dans FastAPI

L'extension propose une factory ; aucune base n'est ouverte à l'import.

Dans ton application FastAPI existante, après la création de l'objet `app`, ajoute :

```python
import os
from pathlib import Path
from aeo_workbench.api import create_router

app.include_router(
    create_router(
        root=Path(os.environ["AEO_REPOSITORY"]),
        token=os.environ["AEO_API_TOKEN"],
    )
)
```

Variables PowerShell :

```powershell
$env:AEO_REPOSITORY = "C:\chemin\vers\ton-depot"
$env:AEO_API_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Chaque requête nécessite `Authorization: Bearer <token>` :

```powershell
Invoke-RestMethod http://127.0.0.1:8766/workbench/runs -Headers @{Authorization="Bearer $env:AEO_API_TOKEN"}
```

Routes :

| Méthode | Route | Résultat |
|---|---|---|
| GET | `/workbench/health` | Version et mode local |
| GET | `/workbench/runs?limit=20` | Historique, limite 1–200 |
| GET | `/workbench/runs/{id}` | Métadonnées du run |
| GET | `/workbench/runs/{id}/events` | Chronologie ordonnée |

La commande autonome `aeo6 serve` utilise le port 8766 par défaut et écoute uniquement en loopback. Les routes ne lancent ni modèle ni shell et ne retournent pas le contenu des fichiers. Elles retournent des métadonnées locales, dont les chemins. Le token est donc nécessaire même en lecture. Lors d'un montage dans ton propre serveur, sa politique réseau et son exposition restent sous ta responsabilité.

## 4. Utiliser le reviewer existant dès aujourd'hui

Le patch accepté est indexé. Dans ton dépôt source AEO complet et initialisé :

```powershell
uv run aeo review --staged --deep
uv run aeo guard --staged
```

Ces commandes V0.5 constituent un contrôle supplémentaire avant ton commit. V0.6 **ne les invoque pas automatiquement**, et leur résultat n'est pas agrégé à l'état `validated` du Workbench. N'exécute pas simplement `aeo review` dans le worktree sans y fournir la configuration V0.5 requise : cette configuration n'est pas copiée implicitement.

## 5. Données et migration

Aucune migration de ta base V0.5. La configuration, le verrou, SQLite et les preuves V0.6 vivent dans :

```text
<git-common-dir>/aeo-workbench/
```

`aeo6 doctor` donne le chemin exact, y compris dans un dépôt utilisant déjà des worktrees. La base de l'extension ne contient ni demandes brutes ni sources ; les propositions, patches et logs existent séparément sur le disque local. La sauvegarde de ton code via Git ne sauvegarde généralement pas ces données.
