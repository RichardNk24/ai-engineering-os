# AEO Workbench V0.7 — Orchestrator

**Un changement. Des preuves reliées au même patch. Une décision humaine.**

La V0.6 proposait et testait un changement dans un worktree. La V0.7 enchaîne
les gates configurées, le Guardian V0.5 et le reviewer V0.5 avec vérification
des constats. Elle produit un compte rendu avant l'acceptation.

## Ce qui change

- `pipeline ID --trust-code --allow-remote` : gates → Guardian → reviewer.
  Une étape bloquante arrête la suite. `Guardian` reçoit `fix=False` ; aucun correctif silencieux.
- `report ID` : disponibilité réelle pour acceptation, constats, incertitudes,
  tests recommandés, tokens et coût estimé lorsque le fournisseur le fournit.
- `report ID --output CHEMIN` : export JSON vers un **nouveau** fichier.
- `bridge-check` : vérification des imports des services V0.5, sans appel IA.
- `demo --pipeline` : vrais Git et tests, **Guardian/reviewer simulés explicitement**.
  Ces résultats simulés ne permettent pas d'accepter le patch.
- Contrôle du patch **et de l'index** : une revue staged ne peut pas porter
  sur un autre contenu que celui montré et testé.
- Empreintes de configuration et de preuves contrôlées avant acceptation.
- Chaque tentative conserve un nouveau dossier de journaux et de résultats.
- Clé API refusée dans `model`/`review_model` ; clés reconnaissables masquées
  dans les métadonnées affichées, y compris les anciennes lignes d'historique.
- FastAPI : `GET /workbench/runs/{id}/report`, authentification obligatoire.
- Identité visuelle conservée : signature ◈ AEO, cyan, états lisibles, colonnes
  adaptatives, rendu littéral des textes, JSON et sortie sans couleur.

## Installation dans votre projet existant — Windows

**Ne copiez pas le `pyproject.toml` de cette archive à la racine de votre projet.**
Il décrit le paquet autonome utilisé pour développer et tester l'extension.
L'installateur conserve le nom, la version et les dépendances de votre cœur.

Téléchargez `AEO-V0.7-Orchestrator.zip` dans Downloads, puis exécutez :

```powershell
& {
    $ErrorActionPreference = "Stop"
    $Projet = Join-Path $env:USERPROFILE "Documents\ai-engineering-os"
    $Archive = Join-Path $env:USERPROFILE "Downloads\AEO-V0.7-Orchestrator.zip"
    $Extraction = Join-Path $env:USERPROFILE ("Documents\aeo-v07-package-" + [guid]::NewGuid())
    $Python = Join-Path $Projet ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
        throw "Le fichier ZIP attendu est absent de Downloads. Vérifiez son nom exact."
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "Le Python .venv du projet est introuvable."
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $Extraction
    $Paquet = Join-Path $Extraction "aeo-v0.7-workbench"
    & $Python (Join-Path $Paquet "scripts\install_into.py") --project $Projet
    if ($LASTEXITCODE -ne 0) { throw "Upgrade arrêté : lire la première erreur et le chemin BACKUP." }
    Set-Location $Projet
    & ".\.venv\Scripts\aeo.exe" workbench version
    & ".\.venv\Scripts\aeo.exe" workbench doctor
    & ".\.venv\Scripts\aeo.exe" workbench bridge-check
    if ($LASTEXITCODE -ne 0) { throw "Connexion au cœur à corriger avant un run réel." }
    & ".\.venv\Scripts\aeo.exe" workbench demo --pipeline
    if ($LASTEXITCODE -ne 0) { throw "Démonstration locale à corriger." }
}
```

L'installateur :

1. Vérifie le projet, son environnement `.venv`, son packaging et le reviewer V0.5.
2. Sauvegarde **chaque fichier remplacé** sous `Documents/aeo-upgrade-backups/`.
3. Met à jour `src/aeo_workbench`, ses trois fichiers de tests et le guide.
4. Ajoute le namespace au packaging du cœur et conserve `aeo` ; ajoute `aeo6` et `aeo7` comme alias.
5. Désinstalle l'ancienne distribution séparée `aeo-workbench` pour éviter deux sources concurrentes.
6. Réinstalle le cœur en editable et vérifie le chemin réellement importé.
7. Exécute tous les tests du dépôt. Aucun commit ni push automatique.

Les fichiers du cœur `src/aeo` restent en place ; seule la CLI est raccordée
si elle ne l'était pas déjà. `.aeo`, la configuration Workbench et les bases
existantes ne sont pas écrasées. Le script ne supprime pas les anciens dossiers
d'extraction de V0.6 : ils peuvent servir au retour arrière.

`aeo version` peut continuer à afficher **0.5.0** (cœur conservé).
`aeo workbench version` et `aeo7 version` doivent afficher **0.7.0**.
`doctor` indique le chemin `workbench_source` réellement utilisé.

Pour un préflight sans modification, ajoutez `--check-only` à l'appel de
`install_into.py`. Vous pouvez relancer l'installation : le packaging et le
raccordement CLI sont idempotents ; une nouvelle sauvegarde est créée.

## Configuration

Votre configuration existante reste utilisable. Les nouveaux champs absents
prennent ces valeurs :

```json
{
  "require_pipeline": true,
  "review_model": null,
  "bridge_timeout_seconds": 600
}
```

- `model` reste votre modèle de génération, par exemple celui déjà configuré.
- `review_model: null` réutilise `model` pour la revue **et sa vérification**.
  Le modèle du reviewer n'est pas remplacé par une valeur implicite du cœur V0.5.
- `require_pipeline: true` exige la chaîne complète, y compris pour accepter
  un ancien run V0.6. Une validation par les seuls tests ne suffit plus.
- Le mode avancé `require_pipeline: false` autorise des **nouveaux** runs avec
  gates seules. Un run créé avec la politique complète, ou ayant commencé une
  pipeline, conserve cette exigence même si ce réglage est ensuite désactivé.
- `bridge_timeout_seconds` limite chaque processus Guardian/reviewer.
- `gates` conserve vos commandes réelles et leurs délais.
- `OPENAI_API_KEY` reste une variable d'environnement. Ne mettez jamais une clé
  dans `model`, `review_model`, `.aeo/project.json` ou Git.

Le Guardian utilise vos checks V0.5 ; certains tests peuvent donc être exécutés
une seconde fois après les gates Workbench. C'est explicite : les configurations
restent indépendantes. Les constats bloquants du reviewer V0.5 gardent leur politique.
Une revue qui omet des fichiers bloque également l'acceptation V0.7.

Le dépôt doit ignorer `.aeo/` dans une règle **committée**. La pipeline copie
uniquement `.aeo/project.json` dans le worktree ; elle n'y copie pas votre base.
Guardian et reviewer produisent leur propre télémétrie dans ce worktree.
Les fichiers de politique du reviewer doivent être des fichiers suivis par Git,
accessibles dans le worktree et conformes aux chemins permis.

## Premier parcours réel

Après l'installation, inspectez `git diff` puis faites le commit d'upgrade.
Le dépôt doit être propre avant `feature`.

Choisissez une amélioration limitée et remplacez les chemins ci-dessous par
ceux de votre projet. Les fichiers à lire doivent déjà exister ; un chemin
`--write` peut désigner un nouveau fichier.

```powershell
$Aeo = (Resolve-Path ".\.venv\Scripts\aeo.exe").Path
& $Aeo workbench feature "Votre amélioration précise" `
    --read src/votre_module.py `
    --write src/votre_module.py `
    --write tests/test_votre_module.py `
    --dry-run
```

Après inspection de ce périmètre, relancez avec `--allow-remote` à la place de
`--dry-run`. Remplacez ensuite `ID_DU_RUN` par l'identifiant affiché :

```powershell
& $Aeo workbench show ID_DU_RUN --diff
& $Aeo workbench pipeline ID_DU_RUN --trust-code --allow-remote
& $Aeo workbench report ID_DU_RUN
```

`--allow-remote` de la pipeline autorise la transmission au reviewer du diff,
du code changé, des métadonnées projet et des fichiers de politique configurés.
La génération et la revue sont des appels distincts, potentiellement facturés.
Le pipeline ne déclenche pas de nouvelle tentative automatiquement ; le SDK du
provider V0.5 conserve ses propres réglages de retry et de stockage côté fournisseur.
La vérification de constats peut déclencher un second appel reviewer selon V0.5.
Aucun coût nul n'est promis : sans tarif renseigné, le coût est `unpriced`.

Si le compte rendu annonce que l'acceptation est possible et que vous approuvez :

```powershell
& $Aeo workbench accept ID_DU_RUN --yes
git diff --cached
```

L'acceptation applique et stage le patch. Vous gardez la décision du commit.
Une erreur se diagnostique avec `report` et le dossier `evidence_directory`.
Relancer `pipeline` crée une **nouvelle tentative complète**, sans réutiliser
silencieusement une ancienne revue et sans effacer les journaux précédents.

## Démonstration et limites vérifiées

`demo --pipeline` fonctionne sans clé API et sans cœur V0.5 installé. L'interface
annonce **OFFLINE FIXTURE** et bloque l'acceptation : ce blocage est attendu.
Les tests et opérations Git de cette démo sont réels ; les services de revue sont simulés.

La livraison est testée localement avec Python 3.12 sous Linux. Le cœur V0.5
fourni n'est qu'une archive d'upgrade partielle : les tests d'orchestration
utilisent des doubles de services pour Guardian/reviewer. **Ni l'intégration
complète sur votre Windows, ni un appel IA réel ne sont certifiés par ces tests.**
L'installateur lance vos tests complets ; `bridge-check` vérifie les imports,
mais seule une pipeline réelle vérifie aussi la compatibilité d'exécution des services.

Un worktree n'est pas une sandbox. Les tests et checks exécutent du code avec
les droits de l'utilisateur et peuvent lire le disque. L'environnement des
checks exclut la clé API, mais cela ne garantit pas l'isolation d'un code hostile.
Les empreintes détectent les modifications accidentelles ; elles ne forment pas
une signature inviolable face à un processus pouvant modifier toutes les preuves.
Les fichiers ignorés ordinaires ne sont pas attestés par le patch Git.

Le code complet, les tests, les limites détaillées et les journaux de validation
sont livrés dans cette archive. Aucune autre réécriture de `src/aeo/cli.py` n'est nécessaire.
