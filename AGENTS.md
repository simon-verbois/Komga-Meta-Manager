# Consignes du projet

## Vision produit

Komga Meta Manager doit devenir une application simple et agréable pour gérer les métadonnées des bibliothèques Komga : mangas, webtoons et ebooks. L'objectif final est une GUI propre, cohérente et accessible, avec une bonne UX sur l'ensemble du parcours, de la première connexion au suivi des modifications.

- Privilégier les choix qui réduisent l'effort de l'utilisateur et rendent le résultat compréhensible.
- Permettre les opérations courantes depuis l'interface, sans édition manuelle de YAML, connaissance des API ou recours aux logs techniques.
- Concevoir les évolutions pour plusieurs types de bibliothèques. Distinguer cette vision des fonctionnalités réellement disponibles ; ne pas annoncer un support qui n'est pas implémenté.
- Livrer des parcours complets : une fonctionnalité doit être utilisable depuis la GUI, avec un retour clair sur son résultat.

## Bibliothèques et métadonnées

- Donner à l'utilisateur le contrôle des bibliothèques traitées et rendre visible la portée des modifications.
- Prévoir des réglages, sources et champs adaptés au type de contenu ; éviter d'imposer aux ebooks ou aux webtoons des hypothèses propres aux mangas.
- Automatiser la découverte et le préremplissage quand les informations sont disponibles dans Komga.
- Préserver les choix enregistrés, les métadonnées existantes et les champs verrouillés selon les règles configurées. Toute suppression ou réécriture doit être explicite et compréhensible.
- Garder des valeurs par défaut prudentes, une simulation accessible et une distinction claire entre simulation et application des changements.

## Interface et expérience utilisateur

- Soigner la hiérarchie visuelle, les espacements, la lisibilité et la cohérence des composants entre les écrans.
- Organiser la navigation autour des tâches de l'utilisateur. Présenter les réglages essentiels en premier et les options avancées progressivement.
- Utiliser des libellés simples et un vocabulaire cohérent. Conserver l'interface en anglais et centraliser les textes dans le système de traduction existant.
- Préférer des sélections et contrôles guidés aux saisies libres lorsque les valeurs peuvent être récupérées automatiquement.
- Afficher les états de chargement, listes vides, succès et erreurs. En cas d'échec, expliquer comment poursuivre et conserver les saisies et sélections.
- Rendre explicite quand une modification est enregistrée, quand elle prend effet et quelles bibliothèques elle concerne.
- Prévoir une interface adaptée aux petits écrans, utilisable au clavier, avec des labels accessibles, un focus visible et des contrastes lisibles.
- Pour toute modification de GUI, vérifier le parcours dans un navigateur, y compris les états pertinents et l'affichage sur petit écran.

## Mise en œuvre et vérification

- Respecter l'architecture existante et les changements déjà présents dans l'espace de travail.
- Choisir des solutions simples et maintenables, en séparant présentation, configuration et traitement des métadonnées.
- Exécuter les vérifications adaptées à la modification. Ajouter des tests utiles pour les changements de comportement, notamment le ciblage des bibliothèques et l'écriture des métadonnées.
- Ne considérer une tâche terminée qu'une fois les changements vérifiés, le changelog actualisé et le dev mis à jour.

## Changelog

- Mettre à jour `CHANGELOG.md` à chaque modification du projet, y compris les corrections, la documentation et la maintenance.
- Ajouter ou ajuster une entrée en anglais sous `## [Unreleased]`, dans la section appropriée (`Added`, `Changed`, `Fixed` ou `Maintenance`).
- Décrire le résultat concret de la modification. Inclure le changelog dans le même commit que les changements concernés.
- Laisser `VERSION` et les sections de versions publiées au script `scripts/release.sh`.

## Environnement de développement

- Après toute modification, exécuter les vérifications adaptées, puis mettre à jour l'environnement de dev avec `./start-kmm.sh` avant de terminer la tâche.
- Ce script reconstruit l'image et recrée le conteneur `komga-meta-manager-dev` avec `compose-testing.yml` (projet Compose `kmm-dev`).
- Vérifier ensuite que `http://localhost:8765/health` répond et que les fichiers applicatifs et ressources embarquées modifiés sont à jour dans le conteneur. Pour une modification de l'interface, vérifier également le rendu concerné.
- Signaler explicitement tout échec de reconstruction ou de démarrage ; ne pas annoncer une modification disponible sur le dev sans l'avoir vérifiée.
