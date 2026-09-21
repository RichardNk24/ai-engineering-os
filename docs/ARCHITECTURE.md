# Architecture V0.6

## Une tranche verticale vers V1

La roadmap fournie place « Implementer, worktrees, orchestration » entre V0.6 et V0.9. Cette version matérialise la première tranche : produire une modification isolée puis réunir des preuves avant intégration. Elle n'annonce ni une équipe autonome V1, ni la mémoire et la prédiction V2/V3.

| Couche | Module | Responsabilité |
|---|---|---|
| Interface | `cli.py`, `ui.py` | Commandes, rendu, confirmations et contrat JSON |
| Control plane | `engine.py` | Préconditions, transitions, validation et acceptation |
| Contrats | `models.py` | Sortie structurée, gates, configuration, usage |
| Modèle | `provider.py` | Adaptateur OpenAI ; protocole injectable dans les tests |
| Dépôt | `gitops.py`, `safety.py` | Git sans shell, périmètre de fichiers et contrôles locaux |
| Preuves | `storage.py` | SQLite WAL, événements, configuration, verrou et dossiers de run |
| API | `api.py` | Lecture authentifiée des métadonnées |

## Transitions

- `planning → dry_run` : préflight local seulement.
- `planning → applying → proposed` : appel unique au modèle, validation de son contrat puis génération du patch dans le worktree.
- `proposed → validating → validated | validation_failed` : commandes configurées, puis re-vérification de l'empreinte du patch.
- `validation_failed → validating` : reprise possible si les fichiers sont intacts (par exemple après installation d'une dépendance manquante).
- `validated → accepted` : configuration des gates inchangée, worktree intact, dépôt source propre et même commit de base.
- Un échec de génération devient `failed`, une interruption interceptée devient `interrupted`.
- `discarded` conserve les preuves, supprime le worktree à la demande explicite de l'utilisateur.

`validated` signifie **tous les gates configurés ont retourné 0 sur ce patch**. Ce statut ne prouve ni l'absence de bug ni une revue sémantique. Sans gate, la validation est refusée. Un timeout, une commande absente ou une mutation produite par les tests invalide le résultat.

## Contexte et confidentialité

Les fichiers sélectionnés sont suivis par Git et le dépôt doit être propre. Les nouveaux chemins `--write` ont une valeur de contexte `null`. Les chemins cachés, symlinks, chemins absolus, traversées de répertoire, variantes Windows ambiguës et certaines extensions sensibles sont refusés. Les fichiers sont lus intégralement, avec limites strictes ; pas de troncature silencieuse du code.

Un scanner heuristique bloque quelques formes de secrets avant le réseau. Il ne détecte pas tous les formats et peut produire des faux positifs. Le modèle reçoit uniquement la demande et les fichiers choisis ; `--allow-remote` est explicite. Le prompt traite les sources comme des données non fiables, et la sortie reste soumise à l'allowlist locale. Cela réduit l'impact de prompt injections, sans garantir leur élimination.

`store=False` est fourni à la Responses API ; cela ne constitue pas une promesse de « zero data retention » du fournisseur. La politique du compte et du service s'applique.

SQLite contient des identifiants, chemins, empreintes, états et mesures. La proposition complète et le patch sont volontairement conservés **localement** pour être examinés. Les logs des tests peuvent contenir des secrets imprimés par le projet : aucune redaction universelle n'est revendiquée. Le dossier n'est pas chiffré ; ses protections dépendent du système de fichiers et du compte local.

## Modèle économique mesuré

Un seul appel d'implémentation, aucun retry implicite du SDK (`max_retries=0`). Tokens et latence sont enregistrés quand une réponse complète est obtenue. Les tarifs sont configurables ; pas de tarif ou de modèle présumé actuel. Un échec réseau peut néanmoins avoir un coût côté fournisseur sans métrique récupérable ; `usage=null` signifie indisponible. `max_output_tokens` borne la sortie, pas une facture totale en dollars.

## Git : garanties et limites

Le worktree est créé en mode détaché sur le commit exact de départ. Les hooks et fsmonitor sont désactivés dans les appels Git du moteur. Les commandes ne passent pas par un shell. Les réglages Git et filtres du dépôt restent ceux d'un dépôt local de confiance.

Le patch est figé et haché. L'intégration emploie `git apply --check --index`, puis `git apply --index`, après vérification du même HEAD et d'un arbre propre. Il n'y a pas de merge automatique de conflits ou de rebase. Si le dépôt avance, il faut régénérer. Évite d'autres opérations Git simultanées : le verrou sérialise AEO, pas tous les processus Git externes. Un arrêt brutal entre l'application Git et l'écriture SQLite peut nécessiter une réconciliation manuelle.

Le worktree n'est **pas un sandbox**. Les tests exécutent du code local avec tes droits et peuvent accéder au disque/réseau. Une sélection limitée de variables est héritée ; la clé OpenAI n'est pas transmise aux gates, mais un processus peut toujours lire d'autres secrets accessibles sur le disque. Les délais interrompent le groupe de processus sous POSIX et demandent `taskkill /T` sous Windows ; cela n'offre pas les garanties d'un conteneur/Job Object sécurisé.

Les gates reçoivent un `PYTHONPATH` privilégiant le `src` du worktree puis sa racine. Vérifie néanmoins la configuration de tes outils si tu utilises une installation éditable complexe ou un environnement extérieur. Les logs ne sont pas plafonnés sur disque dans cette version. Les fichiers ignorés créés par les tests ne sont pas des fichiers livrés par le patch ; ils ne constituent pas une attestation d'exécution reproductible.

## Références de protocole

- [OpenAI — Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) : contrat Pydantic via `responses.parse`.
- [Git — worktree](https://git-scm.com/docs/git-worktree) : worktree détaché et gestion de son cycle de vie.

L'adaptateur a été testé avec une simulation du SDK installé. La capacité effective de ton modèle, tes limites de compte et un appel distant réel restent à valider dans ton environnement.
