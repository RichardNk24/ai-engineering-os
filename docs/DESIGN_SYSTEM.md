# AEO — identité terminal

## Direction

Un atelier d'ingénierie lisible : un signe compact, du rythme, des repères stables. Le terminal reste un terminal : défilement normal, sélection de texte, commandes copiables et sortie machine. Pas de plein écran imposé, pas de son, pas d'animation décorative ou de résultat inventé.

La signature `◈ A E O / WORKBENCH` identifie la surface. Le diamant est un repère typographique, pas une icône nécessitant une Nerd Font. Une police monospace standard suffit ; `AEO_ASCII=1` permet un remplacement plus simple.

| Token | Couleur | Usage |
|---|---|---|
| Brand | `#5EEAD4` | Identité, valeurs importantes, étapes accomplies |
| Ink | `#E2E8F0` | Texte principal |
| Muted | `#94A3B8` | Métadonnées, titres de colonnes |
| Line | `#334155` | Bordures discrètes |
| Good | `#86EFAC` | Validation réussie, acceptation |
| Warn | `#FBBF24` | Incertitude, interruption |
| Bad | `#FB7185` | Échec, action requise |

## Hiérarchie

1. Identité, version et contexte.
2. État du run en toutes lettres.
3. Quatre mesures : commit, contexte, tokens, coût estimé.
4. Étapes : context / propose / isolate / validate / accept.
5. Périmètre explicite et résultats des gates.
6. Prochaine commande concrète.

Un échec reste un échec : aucun badge vert ne remplace un test absent. Coût non configuré = `unpriced`. Le mode démo annonce son fournisseur de fixture hors ligne. Les panels proviennent du même module, ce qui facilite un futur thème clair ou un changement de marque.

## Compatibilité

Rich adapte les colonnes à la largeur. Les essais automatisés incluent un terminal de 48 colonnes. À très petite largeur, des chemins longs se replient : le JSON conserve leur valeur exacte. Le thème vise en priorité un terminal sombre ; utiliser `--plain`/`NO_COLOR` sur fond clair si les contrastes ne conviennent pas. Windows Terminal est adapté, sans être obligatoire.

Les décorations ASCII sont disponibles avec `AEO_ASCII=1`. Les titres et valeurs ne dépendent jamais uniquement de la couleur. Les chaînes issues du dépôt ou du modèle sont des objets Text littéraux, avec caractères de contrôle filtrés avant affichage ; elles ne peuvent pas injecter du markup Rich ou une séquence OSC de presse-papiers.

`--json` supprime bannière, panels et spinner. Le contenu JSON n'est pas mutilé pour le rendu : les caractères spéciaux restent échappés par l'encodeur JSON. Les erreurs de syntaxe de la commande sont gérées par Typer ; les erreurs métier ont une enveloppe `{"error": ...}`.

`terminal-preview.png` a été rendu à partir de la vraie sortie Rich d'un run de démonstration validé. Ce n'est pas une maquette d'une fonctionnalité future.
