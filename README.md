# MAAT v11

MAAT est une plateforme légère pour organiser un TP ou un mini-projet de programmation : dépôt d'archives ZIP, compilation/exécution dans Docker, extraction de métriques depuis la sortie standard, classements en direct et export de fin de séance.

![Accueil MAAT](docs/screenshots/page_accueil_maat.png)

## Points forts

- **Multi-plateformes côté enseignant** : Linux en priorité, usage possible via WSL/macOS selon l'installation Docker et Cloudflare.
- **Multi-langues côté interface** : français et anglais, sélectionnés dans `config.json`.
- **Multi-langages de programmation côté projets** : profils C++, Python et Java déclaratifs.
- **Simple à monter** : un serveur Flask local, Docker, puis éventuellement un tunnel Cloudflare.
- **Souple et générique** : chaque projet déclare ses données, instances, langage(s), métriques et format de sortie attendu.
- **Peu intrusif pour les étudiants** : ils déposent une archive ZIP contenant le point d'entrée attendu.
- **Rapide à mettre en œuvre** : deux projets exemples sont fournis avec données, solutions et archives ZIP de test.
- **Sécurité raisonnable pour TP supervisé** : exécution Docker isolée, limites CPU/RAM/PID, réseau coupé et filtrage pédagogique des appels dangereux.

MAAT n'est pas une plateforme SaaS multi-tenant, ni une sandbox infaillible, ni un remplacement complet de Moodle. C'est un serveur enseignant, local, conçu pour des séances encadrées.

## Démarrage rapide

Depuis la racine du bundle :

```bash
./manage-maat.sh install
./manage-maat.sh check
./manage-maat.sh start
```

Dans un autre terminal, pour exposer MAAT aux étudiants avec Cloudflare :

```bash
./manage-tunnel.sh start
```

ou, recommandé pendant un TP long :

```bash
./manage-tunnel.sh watch
```

Le mode `watch` redémarre le tunnel si l'URL publique cesse de répondre. Le script affiche désormais l'URL Cloudflare complète et l'URL raccourcie.

## Fichiers de configuration à modifier pour démarrer

Le serveur lit **`config.json`**. Le fichier **`config.example.json`** sert de modèle.

Attributs principaux à vérifier dans `config.json` :

```json
"interface":
{
  "language": {"value": "fr", "comment": "Default interface language: fr or en."}
},
"project":
{
  "active_project": {"value": "projects/tsp", "comment": "Path to the active MAAT project directory."}
},
"server":
{
  "listen_host": {"value": "0.0.0.0", "comment": "Network interface on which the Flask server listens."},
  "listen_port": {"value": 8000, "comment": "TCP port on which the Flask server listens."},
  "public_url":  {"value": "http://localhost:8000", "comment": "Public URL shown to users and in server summaries."},
  "admin_token": {"value": "CHANGE_ME", "comment": "Secret key required to open the administration page."}
}
```

Projet activé par défaut : **`projects/tsp`**.

Le script `manage-maat.sh` affiche l'URL locale, l'URL admin et le token admin. Le script `manage-tunnel.sh` affiche l'URL publique complète, l'URL raccourcie et rappelle la configuration `ntfy`.

## Arborescence

```text
maat/
├── maat_app/                 # application Flask et cœur d'évaluation
├── templates/                # pages HTML
├── static/                   # CSS/JS
├── translations/             # chaînes génériques FR/EN
├── languages/                # profils de langages : cpp, python, java
├── docker/                   # Dockerfiles des runners
├── projects/                 # projets pédagogiques
│   ├── tsp/
│   │   ├── project.json
│   │   ├── data/
│   │   ├── documents/        # étudiants factices, CSV généré, base locale
│   │   ├── results/          # snapshots, exports, classements
│   │   ├── sample_solution/
│   │   ├── submission/       # scripts + ZIP prêt à déposer sur l'UI
│   │   └── statement/
│   └── mnist_digits/
│       ├── project.json
│       ├── data/
│       ├── documents/
│       ├── results/
│       ├── sample_solution/
│       ├── submission/
│       └── statement/
├── scripts/                  # génération étudiants, checks, packaging
├── config.json               # configuration locale active
├── config.example.json       # modèle de configuration
├── manage-maat.sh            # installation, lancement, checks, projets
└── manage-tunnel.sh          # tunnel Cloudflare + watch + ntfy
```

Les fichiers JSON éditables utilisent le format `value` / `comment`. Les commentaires sont en anglais et servent uniquement à comprendre le rôle des attributs.

## Tunnel Cloudflare : point important

MAAT tourne localement sur la machine enseignante. Pour que les étudiants y accèdent depuis leur navigateur, le plus simple est d'ouvrir un tunnel temporaire :

```bash
./manage-tunnel.sh start
```

Le script affiche :

- l'URL complète `https://....trycloudflare.com` ;
- l'URL raccourcie, plus facile à recopier ;
- les informations `ntfy` pour recevoir une notification sur téléphone lorsqu'une nouvelle URL est publiée.

Pendant une séance, utiliser de préférence :

```bash
./manage-tunnel.sh watch
```

Ce mode vérifie régulièrement l'URL publique et recrée le tunnel si nécessaire. L'URL du tunnel doit être partagée aux étudiants, par exemple au tableau ou dans un canal de cours.

## Accès administration

Après `./manage-maat.sh start`, le script affiche l'URL admin et le token admin. Par défaut :

```text
http://127.0.0.1:8000/admin
```

Pour un accès depuis le tunnel, utiliser l'URL publique suivie de `/admin` et saisir le token affiché par `manage-maat.sh`.

## Projets inclus

### `projects/tsp` — C++ / Traveling Salesman Problem

Objectif : trouver une tournée courte dans une matrice de distances.

- **Langage autorisé** : C++.
- **Entrée** : fichier texte contenant `n`, puis une matrice `n x n` de distances.
- **Algorithme exemple** : énumération des permutations avec ville de départ fixée, mise à jour du meilleur tour trouvé.
- **Paramètres principaux** : instance TSP, nombre de villes, matrice des distances.
- **Sortie attendue** : le programme affiche les caractéristiques de l'instance, la matrice des distances, la progression de la longueur du tour à chaque itération, puis :

```text
final tour length -> <number>
```

- **Métrique** : `tour_length`, somme sur les instances, à minimiser.
- **ZIP de test UI** : `projects/tsp/submission/tsp_cpp_sample_submission.zip`.
- **Scripts pour régénérer le ZIP** :

```bash
projects/tsp/submission/make_submission_linux.sh
projects/tsp/submission/make_submission_windows.bat
```

### `projects/mnist_digits` — Python / classification de chiffres manuscrits

Objectif : classifier des images de chiffres manuscrits de type MNIST.

- **Langage autorisé** : Python.
- **Entrée** : fichiers CSV `label,p0,...,p63` représentant des images 8x8 en niveaux de gris.
- **Données** : jeu hors-ligne MNIST-like issu du dataset digits de scikit-learn, fourni directement dans le bundle ; environ 2/3 entraînement et 1/3 test.
- **Algorithme exemple** : classifieur par centroïdes de classes et distance euclidienne au carré.
- **Paramètres principaux** : normalisation, métrique de distance, nombre de centroïdes, nombre de checkpoints de progression.
- **Sortie attendue** : le programme affiche les caractéristiques de l'instance, les paramètres de l'algorithme, la progression de l'accuracy, puis :

```text
final accuracy -> <percentage>
```

- **Métrique** : `accuracy`, moyenne sur les instances, à maximiser.
- **ZIP de test UI** : `projects/mnist_digits/submission/mnist_python_sample_submission.zip`.
- **Scripts pour régénérer le ZIP** :

```bash
projects/mnist_digits/submission/make_submission_linux.sh
projects/mnist_digits/submission/make_submission_windows.bat
```

## Changer de projet

Lister les projets :

```bash
./manage-maat.sh list-projects
```

Activer TSP :

```bash
./manage-maat.sh set-project tsp
```

Activer MNIST-like digits :

```bash
./manage-maat.sh set-project mnist_digits
```

Créer un nouveau squelette :

```bash
./manage-maat.sh new-project mon_projet
```

## Sécurité et données factices

Les fichiers `students.xlsx` fournis dans chaque projet sont **fictifs**. Ils servent uniquement à tester la génération des tokens, les dépôts et les classements.

MAAT exécute du code non fiable dans des conteneurs Docker avec :

- réseau désactivé ;
- capacités Linux supprimées ;
- `no-new-privileges` ;
- utilisateur non-root ;
- filesystem racine en lecture seule ;
- `/tmp` en `tmpfs` ;
- limites CPU, RAM et nombre de processus ;
- timeouts de compilation et d'exécution ;
- filtrage pédagogique de motifs dangereux dans les sources.

Ces mécanismes limitent les dégâts mais ne constituent pas une garantie absolue contre un attaquant déterminé. MAAT doit rester utilisé sur une machine contrôlée par l'enseignant, dans un contexte pédagogique supervisé.

## Notifications téléphone avec ntfy

Dans `config.json`, vérifier :

```json
"tunnel":
{
  "notifications_enabled": {"value": true, "comment": "Enable ntfy notifications for tunnel status changes."},
  "ntfy_server":           {"value": "https://ntfy.sh", "comment": "ntfy server used to send tunnel notifications."},
  "ntfy_topic":            {"value": "CHANGE_ME", "comment": "ntfy topic receiving notifications on a phone."}
}
```

Sur le téléphone : installer l'application ntfy, ajouter une souscription, saisir le serveur et le topic affichés par les scripts, puis garder le topic privé.

## Artefacts d'exécution

Les résultats, snapshots, documents générés et bases SQLite sont localisés par projet :

```text
projects/<project_id>/documents/
projects/<project_id>/results/
```

Les soumissions et runs temporaires sont à la racine :

```text
submissions/
runs/
logs/
```

## Licence et contribution

Le bundle contient `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md` et `CHANGELOG.md`. Avant publication publique, vérifier la licence choisie et remplacer les valeurs locales sensibles de `config.json`.
