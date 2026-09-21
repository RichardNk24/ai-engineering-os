# Reprise et dépannage

## « Run aeo6 init first »

Place-toi dans le dépôt cible, puis `aeo6 init`. La configuration V0.5 n'est pas la configuration V0.6. `doctor` affiche le chemin exact.

## Aucun modèle / requête refusée

Renseigne `model` ou `--model`, installe l'extra `[ai]`, vérifie la variable `OPENAI_API_KEY`, le réseau, les quotas et la compatibilité avec les sorties structurées. Aucune clé n'est affichée par `doctor`. Un message d'erreur du fournisseur n'est pas réimprimé intégralement car il peut contenir des éléments de requête. Les erreurs ne sont pas des succès ; consulte `runs` pour l'état persisté.

## Verrou abandonné

Une interruption Python ordinaire libère le verrou. Une extinction brutale du processus peut laisser `operation.lock` dans le dossier donné par `doctor`. Vérifie que le PID inscrit ne correspond plus à un processus AEO actif. Seulement ensuite, supprime **ce fichier de verrou**, pas la base ni le répertoire Git. Crée une nouvelle proposition ; aucune reprise automatique d'une écriture partielle n'est supposée sûre.

## `failed`, `interrupted`, `applying` ou `validating` après crash

L'historique est conservé. Inspecte le worktree et les preuves avec `show`. Une proposition interrompue n'est pas acceptable. Utilise `discard ID` si tu veux supprimer son worktree, puis recommence. `discard` efface aussi les modifications manuelles que tu aurais faites dans ce worktree ; une confirmation est requise.

## Tests échoués

Les commandes s'exécutent à la racine du worktree, avec les dépendances disponibles dans l'interpréteur configuré. Installe les dépendances manquantes ; `aeo6 validate ID --trust-code` peut réexécuter les gates si la proposition est intacte. Si tu modifies le code manuellement, la preuve est périmée : repars sur une nouvelle proposition.

Les logs sont `gate-N.log` dans le dossier du run. Ils restent locaux et peuvent contenir ce que ton projet imprime. Les réexécutions remplacent ces fichiers de logs ; les transitions et résultats courants restent dans SQLite. Ce n'est pas encore un stockage immuable de chaque tentative.

## HEAD a changé / arbre sale

AEO ne tente pas de résoudre automatiquement un conflit. Committe ou stash ton travail, puis régénère la proposition sur le nouveau HEAD. Il n'y a pas de bouton « forcer » contournant l'empreinte de validation.

## Arrêt après acceptation Git mais avant enregistrement SQLite

Inspecte `git diff --cached` et compare avec `change.patch`. Le code peut avoir été appliqué alors que l'état indique encore `validated`. N'essaie pas de l'appliquer une seconde fois. La présence de changements indexés empêchera une seconde acceptation automatique. Réconcilie manuellement le dépôt et conserve l'historique comme preuve d'une opération interrompue.

## Annuler / nettoyer

Avant acceptation : `aeo6 discard ID` supprime le worktree et garde patch/proposition/historique. Après acceptation : AEO ne supprime pas tes modifications source ; utilise les outils Git habituels après examen. Les worktrees acceptés sont conservés pour inspection. Quand tu n'en as plus besoin, utilise `git worktree remove <chemin>` ; Git peut demander une option force pour les changements conservés dans ce worktree. Vérifie soigneusement le chemin. La démo affiche un dépôt temporaire séparé que tu peux supprimer une fois l'examen terminé.
