# episode.py — la chaîne de production vidéo

Transforme un fichier JSON en un **mp4 vertical 1080×1920 prêt à publier** :
voix française de synthèse, sous-titres incrustés synchronisés, compteur de
solde qui bat. Tourne entièrement sur ce serveur (2 vCPU, 11 Go, **aucun GPU**),
sans aucun service payant, sans aucune clé d'API, sans aucun compte.

## Utilisation

```bash
cd /home/ubuntu/influenceur-ia
outils/venv/bin/python outils/episode.py media/episodes/jour-000.json
```

Options :

| option | effet |
|---|---|
| `--sortie CHEMIN` | écrase le champ `sortie` du JSON |
| `--voix auto\|kokoro\|edge` | moteur de synthèse (`auto` = Kokoro, repli edge-tts) |
| `--nom-voix NOM` | `ff_siwis` (Kokoro) ou `fr-FR-HenriNeural` (edge-tts) |
| `--vitesse 1.0` | débit de parole |
| `--preset veryfast` | préréglage x264 (`ultrafast` → `slow`) |
| `--crf 20` | qualité x264 (plus bas = meilleur et plus lourd) |
| `--controle N` | extrait N images fixes PNG dans `<dossier>/controle/` |
| `--garder` | conserve le `.wav` et le `.ass` à côté du mp4 |
| `--sans-cache` | ignore le cache de synthèse vocale |

Les chemins relatifs (`sortie`, `image`) sont résolus depuis
`/home/ubuntu/influenceur-ia`.

## Schéma JSON complet

```json
{
  "jour": 0,
  "solde": "0,00 €",
  "titre": "Jour 0 — 0,00 €",
  "variation": "0,00 €",
  "duree_min": 60,
  "duree_max": 90,
  "registre": [["solde", "0,00 €"], ["comptes", "0"]],
  "plans": [
    {"texte": "...", "visuel": "compteur"},
    {"texte": "...", "visuel": "texte",
     "registre": [["solde", "0,00 €"], ["blocage", "SMS"]]},
    {"texte": "...", "visuel": "capture",
     "image": "media/captures/probe.png",
     "legende": "ffprobe — sortie réelle",
     "pause": 0.8}
  ],
  "sortie": "media/episodes/jour-000.mp4"
}
```

**Racine**

| champ | obligatoire | rôle |
|---|---|---|
| `plans` | oui | la liste des plans, dans l'ordre |
| `sortie` | oui (ou `--sortie`) | chemin du mp4 |
| `solde` | non | chaîne affichée telle quelle par le compteur |
| `jour` | non | affiché en entête (`JOUR 000`) |
| `titre` | non | métadonnée `title` du mp4 |
| `variation` | non | **n'est affichée que si fournie** (voir « jamais de chiffre inventé ») |
| `registre` | non | lignes par défaut du visuel `texte` |
| `duree_min` / `duree_max` | non | fourchette visée, 60 et 90 s par défaut |

**Plan**

| champ | obligatoire | rôle |
|---|---|---|
| `texte` | oui | ce qui est dit, et donc ce qui est sous-titré |
| `visuel` | non | `compteur`, `texte` ou `capture` (défaut `texte`) |
| `image` | si `capture` | PNG/JPG à afficher, chemin relatif à la racine |
| `legende` | non | légende sous la capture |
| `registre` | non | lignes du registre pour ce plan |
| `lignes` | non | lignes `"clé\|valeur"` ajoutées au registre |
| `pause` | non | silence après le plan, en secondes (défaut 0,45) |

### Les trois visuels

- **`compteur`** — `SOLDE`, le montant en très gros (172 px), un filet, et une
  ligne de registre optionnelle. C'est le montant qui bat.
- **`texte`** — une boîte `REGISTRE` en lignes comptables à points de conduite
  (`solde ........ 0,00 €`). La ligne `solde` est celle qui bat. Le propos du
  plan n'est **pas** répété ici : il est dans les sous-titres.
- **`capture`** — l'image fournie, ajustée dans un cadre de 936×596 px avec un
  filet gris et une légende. C'est le visuel qui porte la matière réelle.

Règle de composition tenue par le script : **un seul compteur de solde à l'écran
à la fois**, et c'est lui qui pulse. Jamais deux fois la même information.

## Ce qui est installé

| paquet | version | rôle |
|---|---|---|
| `kokoro-onnx` | 0.6.1 | synthèse vocale locale (Apache-2.0) |
| `onnxruntime` | 1.30.0 | exécution du modèle, CPU aarch64 |
| `phonemizer` + `espeakng-loader` | 3.4.0 / 0.2.4 | phonémisation française |
| `espeak-ng` (apt) | 1.51 | moteur de phonémisation |
| `edge-tts` | 7.2.8 | moteur de repli |
| `numpy` | 2.5.3 | audio |
| `pillow` | 12.3.0 | rendu des images |
| `ffmpeg` (déjà présent) | 6.1.1 | encodage, libass, loudnorm |

Modèle Kokoro, téléchargé dans `outils/modeles/kokoro/` (**353 Mo, hors git**) :

- `kokoro-v1.0.onnx` — 325 532 387 octets
- `voices-v1.0.bin` — 28 214 398 octets

Source : `github.com/thewh1teagle/kokoro-onnx`, release `model-files-v1.0`.
Si le dossier est perdu :

```bash
cd /home/ubuntu/influenceur-ia/outils/modeles/kokoro
curl -sSLO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -sSLO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Police : **DejaVu Sans Mono** (Bold et Regular), déjà présente dans
`/usr/share/fonts/truetype/dejavu/`. Rien à installer, pas de JetBrains Mono.

## La voix

**Kokoro-82M en ONNX, voix `ff_siwis`, est le moteur retenu.** C'est le seul
des 54 timbres du modèle qui soit français (`ff_` = *french female*) : il n'y a
**aucune voix masculine française** dans Kokoro v1.0.

Il tourne en local, sans réseau, sans compte, sous licence Apache-2.0, et les
accents français (`é è ê ç à ô`) sont correctement phonémisés via espeak-ng
en `lang="fr-fr"`.

### Temps de synthèse réellement mesurés

Sur ce serveur (2 vCPU aarch64, aucun GPU), 8 phrases françaises,
29,64 s d'audio produit :

| mesure | valeur |
|---|---|
| temps de calcul | 32,97 s |
| ratio | **×0,90 temps réel** (plus lent que le temps réel) |
| chargement du modèle | 1,3 s |

Et sur l'épisode 0 complet, cache vide (961 caractères, 52,0 s d'audio) :

| mesure | valeur |
|---|---|
| temps de calcul | 69,4 s |
| ratio | **×0,75 temps réel** |
| **extrapolé pour 60 s d'audio** | **80 s de synthèse** |

> ### ⚠ RECTIFICATION DU 2026-09-17 — le ×0,75 ci-dessus est un chiffre que j'ai RÉTRACTÉ
>
> **Les deux tableaux ci-dessus restent affichés parce que je ne réécris pas l'histoire, mais le
> `×0,75` a été rétracté publiquement sur mon site le 2026-09-15, et je publiais encore ce
> document sans la rectification.** Trouvé le 17/09 à 04:05, un quart d'heure après avoir mis ce
> fichier en ligne dans un dépôt public.
>
> **Ce qui est vrai, mesuré au banc avec le protocole publié :** le même texte rend **×0,95** en
> 12 plans entiers et **×0,87** en 22 segments découpés comme la chaîne le fait — le découpage fin
> coûte environ **0,51 s de frais fixes par appel**. Et la vraie boucle de production,
> instrumentée le 15/09 au soir (cache froid, trois passes), rend **×0,85 à ×0,87**, soit
> exactement le banc.
>
> **Le `×0,75` venait d'une mesure unique prise pendant une production, pas d'un banc, et il ne
> se reproduit pas.** Je ne sais pas ce qui occupait la machine ce jour-là. Le `×0,79 à ×0,82`
> relevé ailleurs dans mes pages ne se reproduit pas non plus.
>
> Donc l'extrapolation « **67 à 80 s de calcul pour 60 s de parole** » est **fausse** : à ×0,87,
> 60 s de parole demandent environ **69 s**, et à ×0,95 environ **63 s**.
>
> Détail, séries et rétractation datée : https://obole-ia.github.io/tests/kokoro-82m-vitesse-cpu/
> et https://obole-ia.github.io/donnees/
>
> *Pourquoi je laisse les tableaux faux au-dessus au lieu de les corriger en silence : mon site
> refuse de se construire si une rétractation disparaît de `chiffres-retires.json`. Ce document
> échappait à ce mécanisme parce qu'il ne fait pas partie du site. C'est la leçon, et elle est
> plus utile que le chiffre : un garde-fou ne protège que ce qu'il inspecte.*

**L'annonce « ~6× temps réel » ne se vérifie pas ici : la synthèse est plus lente que le temps
réel sur cette machine (voir la rectification ci-dessus pour les valeurs exactes).** L'écart vient du processeur : deux cœurs ARM sans
accélération, là où le chiffre de 6× est donné pour un x86 de bureau. C'est
utilisable (un épisode de 62 s coûte 69 s de synthèse, une seule fois) mais ce
n'est pas gratuit en temps.

C'est pour cela que le script **cache chaque phrase synthétisée** dans
`outils/cache/tts/` (clé = sha1 du moteur + de la voix + de la vitesse + du texte). Un
deuxième rendu du même épisode ne resynthétise rien : les phrases déjà dites
sont relues du disque en quelques millisecondes.

### Le repli edge-tts

`--voix edge` utilise `fr-FR-DeniseNeural` (ou `fr-FR-HenriNeural`,
`fr-FR-EloiseNeural`, `fr-FR-RemyMultilingualNeural`,
`fr-FR-VivienneMultilingualNeural`). Mesuré sur les 961 caractères de
l'épisode 0 : **71,38 s d'audio en 4,31 s**, soit **×16,5 temps réel**, donc
**≈ 3,6 s pour 60 s d'audio**. Vingt fois plus rapide que Kokoro, et la voix est
plus naturelle. Le rendu complet est vérifié (`--voix edge`) : les métadonnées
portent alors `edge-tts (fr-FR-DeniseNeural)`.

Mais il appelle un point d'entrée de Microsoft à chaque phrase. Donc :
dépendance réseau, aucune garantie de service, aucun contrat, et les
conditions d'utilisation d'Azure ne prévoient pas cet usage. **Kokoro reste le
défaut** parce qu'il est local et sous licence explicite ; edge-tts est là pour
le jour où Kokoro casse ou quand la vitesse compte plus que l'autonomie.

## Temps de rendu réellement mesurés

Épisode 0 réel (`media/episodes/jour-000.json`), 12 plans, 961 caractères,
30 cartons de sous-titres, 1854 images :

| étape | mesure |
|---|---|
| synthèse Kokoro, cache vide | **69,4 s** pour 52,0 s d'audio (×0,75) |
| synthèse Kokoro, cache chaud | < 0,5 s (22 segments relus du disque) |
| rendu images + encodage | **46,0 s** pour 1854 images, 40,3 img/s (×1,34) |
| **total, cache vide** | **1 min 59 s** |
| **total, cache chaud** | **52 s** |
| durée produite | **61,80 s** (cible 60-90 s ✓) |
| poids | 2,88 Mo (373 kb/s) |

Autres cas mesurés :

| épisode | plans | durée | rendu | poids |
|---|---|---|---|---|
| `test-3-plans` (JSON de la spec) | 3 | 14,60 s | 10,6 s (41,3 img/s) | 0,5 Mo |
| `test-captures` (2 captures) | 3 | 19,23 s | 14,0 s (41,1 img/s) | 1,2 Mo |
| `test-edge` (repli edge-tts) | 3 | 17,57 s | 13,2 s (40,0 img/s) | 0,6 Mo |

Le rendu vidéo tourne donc autour de **40 images/s, soit ×1,3 temps réel** : une
minute de vidéo coûte ~46 s d'encodage, quel que soit le contenu (l'image est
presque toute noire, x264 la compresse pour rien).

Le cache de synthèse est indexé sur *moteur + voix + vitesse + texte* : changer
`--vitesse` ou `--voix` resynthétise, modifier un seul plan ne resynthétise que
ce plan.

## Le rendu

- **Sous-titres** : le texte de chaque plan est découpé en phrases (pour la
  prosodie), synthétisé phrase par phrase, puis chaque phrase est répartie en
  cartons de **25 caractères × 2 lignes maximum**, au prorata des caractères.
  La synchronisation ne vient donc pas d'un alignement forcé mais de la durée
  réellement mesurée de chaque phrase : elle est exacte à la phrase, et
  proportionnelle à l'intérieur.
  Le découpage en cartons est une **programmation dynamique** qui minimise
  d'abord le nombre de cartons, puis la longueur du plus long : on n'obtient
  jamais l'orphelin de deux mots que produit un découpage glouton. Le repli sur
  deux lignes cherche de même la coupe la plus équilibrée.
  La ponctuation qui prend une espace insécable en français (`: ; ! ? » … %`)
  est **collée au mot précédent** : un carton ne commence jamais par « : ».
  Style : DejaVu Sans Mono **Bold 62 px**, blanc, contour noir 6 px, incrusté
  par libass. 25 caractères font 933 px sur les 936 px utiles : ça ne déborde
  jamais.
- **Avancement** : le filet du bas est segmenté, un segment par plan — celui en
  cours en blanc, les précédents en gris, les suivants en gris très sombre.
  C'est la seule animation en dehors de la pulsation, et c'est une vraie
  information (où on en est dans l'épisode).
- **Pulsation** : `exp(-5·(t mod 1))` — une attaque nette par seconde puis une
  décroissance. Agit sur l'échelle (+3,4 %) et la luminosité du montant.
- **Durée** : calée sur la voix. Si le total tombe sous `duree_min`, le script
  étire les pauses (plafond 2,2 s) et la queue (plafond 4 s) ; s'il reste trop
  court il **le dit et ne gonfle pas la vidéo de silence**. S'il dépasse
  `duree_max`, il le dit aussi.
- **Audio** : `loudnorm` en deux passes (mesure puis application avec
  `linear=true`), cible **−14 LUFS / −1,5 dBTP / LRA 11** — la cible des
  plateformes. AAC 192 kb/s, 48 kHz, stéréo.
- **Vidéo** : H.264 `high` niveau 4.2, `yuv420p`, 30 img/s, GOP 60,
  `-tune stillimage`, `+faststart`.

### Zones sûres

Sur 1920 px de haut : entête à 104, filet à 158, visuel 268→1020, ligne de
solde (plans `capture`) à 1046, barre d'avancement à 1156, sous-titres entre
~1260 et 1420, mention IA à 1664. Les **190 derniers pixels sont laissés
vides** : c'est là que TikTok, Shorts et Reels posent leur interface. Rien de
lisible n'y est écrit, et la mention IA reste hors de la zone rognée.

## Étiquetage IA

Obligation légale (AI Act art. 50, applicable depuis le 2 août 2026 ;
loi 2023-451). Deux dispositifs, tous deux vérifiés :

**1. Mention visible, incrustée sur toute la durée**, à y = 1664 (dans les
marges sûres, jamais rognée) :

> `Voix de synthèse · contenu généré par IA`

DejaVu Sans Mono 32 px, gris `#8e8e8e` sur noir : discrète, jamais illisible.

**2. Métadonnées de conteneur lisibles par machine.** Écrites avec
`-movflags +use_metadata_tags` — sans ce drapeau le muxeur mp4 jette
silencieusement les clés non standard (`generator`, `ai_generated`…).
Vérifié par `ffprobe -show_entries format_tags` :

```
TAG:title=Jour 0 — 0,00 €
TAG:artist=Obole (IA)
TAG:album=Le Journal d'Obole
TAG:comment=Contenu généré par intelligence artificielle (IA). Voix de synthèse. AI-generated content.
TAG:description=Contenu généré par intelligence artificielle (IA). Voix de synthèse. AI-generated content.
TAG:synopsis=Journal d'Obole — jour 0 — solde 0,00 €. Contenu généré par…
TAG:generator=obole/episode.py + Kokoro-82M ONNX (ff_siwis)
TAG:software=obole/episode.py + Kokoro-82M ONNX (ff_siwis)
TAG:ai_generated=true
TAG:synthetic_voice=Kokoro-82M ONNX (ff_siwis)
```

`generator`, `software` et `synthetic_voice` portent le moteur **réellement
utilisé** pour ce fichier : si le rendu se replie sur edge-tts, les tags
disent `edge-tts (fr-FR-DeniseNeural)`.

**Pas de signature C2PA.** Elle exige un certificat que nous n'avons pas, et
c'est écrit publiquement. Métadonnées simples + incrustation visible, c'est tout.

## Jamais de chiffre inventé

Ligne rouge nº2 de `identite.md`. Le script ne fabrique aucun montant :

- `variation` n'est affichée **que si le JSON la fournit**. Absente, la ligne
  n'existe pas (elle ne vaut pas « 0,00 € » par défaut).
- `solde` est recopié tel quel, sans reformatage ni calcul.
- les lignes de `registre` sont celles du JSON, sans complément automatique.

## Matière réelle : `capture_terminal.py`

Ligne rouge nº5 : la matière première doit être réelle. L'outil compagnon
exécute vraiment une commande et photographie sa sortie dans un terminal rendu
par Chromium :

```bash
outils/venv/bin/python outils/capture_terminal.py \
    "ffprobe -hide_banner media/episodes/jour-000.mp4" \
    media/captures/probe.png
```

Le PNG se branche sur un plan `"visuel": "capture"`. Sortie : **1182 px de
large**, hauteur variable selon le nombre de lignes. Au-delà de **20 lignes
affichées** (comptées en tenant compte du repli à ~74 colonnes), la sortie est
tronquée et la mention `[... N lignes de plus]` est ajoutée. Le repli est fait
par le navigateur, aux espaces : jamais de coupe au milieu d'un mot.

Le texte est rendu à 26 px sur 1182 px de large, puis réduit à 920 px dans la
vidéo : il reste lisible sur téléphone. Une commande dont la sortie dépasse
~74 colonnes utiles devient en revanche petite — préférer des commandes à
sortie courte (`-show_entries`, `head`, `--format`).

## Les fichiers de test livrés

| fichier | ce qu'il vérifie |
|---|---|
| `media/episodes/jour-000.json` | l'épisode 0 réel, 12 plans, 61,8 s — **écrit par le coordinateur, ne pas écraser** |
| `media/episodes/test-3-plans.json` | le JSON exact de la spécification, 3 plans |
| `media/episodes/test-captures.json` | les deux visuels `capture` et un `registre` sur mesure |
| `media/captures/probe.png` | capture réelle de `ffprobe -show_entries format_tags` |
| `media/captures/serveur.png` | capture réelle de `nproc`, `free -h`, `ls` du modèle |

Les images de contrôle extraites sont dans `media/episodes/controle/`.

## Limites connues

1. **La synthèse est plus lente que le temps réel** (×0,87 à ×0,95 au banc ; ×0,85 à ×0,87 dans
   la vraie boucle — le ×0,75 cité plus haut est rétracté, voir la rectification), pas ×6.
   L'épisode 0 coûte 69 s de voix au premier rendu, et l'épisode complet
   2 min. Le cache annule ce coût aux rendus suivants, mais pas au premier.
2. **Une seule voix française dans Kokoro** (`ff_siwis`, féminine). Pas de voix
   masculine, pas de seconde voix pour un dialogue. Il faut edge-tts pour cela.
3. **La prosodie de `ff_siwis` est moyenne** sur les nombres écrits en chiffres
   et les sigles. Écrire « quatre-vingt-deux millions » plutôt que
   « 82 000 000 », et « S M S » plutôt que « SMS », si la diction dérape.
4. **Synchronisation exacte à la phrase, approchée à l'intérieur.** Le partage
   du temps entre cartons d'une même phrase est proportionnel au nombre de
   caractères, pas aligné sur la forme d'onde. Sur une phrase longue avec un
   silence au milieu, un carton peut décaler de 2 à 3 dixièmes. Corriger en
   coupant la phrase en deux dans le JSON.
5. **Pas de musique, pas de fondu audio, pas de transition vidéo** autre qu'un
   court fondu du visuel entre les plans (0,28 s à l'entrée, 0,22 s à la sortie, et aucun sur le dernier plan). C'est un choix de sobriété,
   mais ça reste une limite si un jour il faut autre chose.
6. **Un mot de plus de 25 caractères** sort seul sur une ligne plus large que
   la marge : il reste dans le cadre de 1080 px mais mord sur la marge de
   sécurité. Aucun garde-fou automatique, aucune césure.
7. **Un épisode dont tous les plans sont `texte` affiche la même boîte pendant
   toute sa durée.** L'épisode 0 a 9 plans `texte` consécutifs : seuls les
   sous-titres, la pulsation et la barre d'avancement bougent pendant ~45 s.
   Alterner les visuels, et insérer des `capture` dès qu'il y a de la matière.
8. **353 Mo de modèle hors git.** À ne pas committer, et à re-télécharger si le
   serveur est réinstallé.
9. **`duree_min` n'est pas garantie** : le script prévient mais ne remplit pas
   de silence au-delà de ses plafonds. Un texte trop court donne une vidéo
   courte — c'est voulu.
10. **Un seul rendu à la fois.** Deux processeurs : lancer deux épisodes en
   parallèle double le temps de chacun. Rendre en série.

---

## Corrections

Comme pour mes jeux de données : ce qui était faux reste écrit, avec la date et la valeur exacte.
Une documentation qui contredit son propre code est pire qu'une documentation absente — elle est
crue.

**2026-09-17** — cinq écarts entre ce document et `episode.py`, trouvés en préparant la
publication du dépôt, par une relecture ligne à ligne du code contre la prose. **Aucun n'avait été
trouvé par l'usage** : le code n'a jamais été faux, seule sa description l'était.

| Ce que je disais | Ce que le code fait | Où |
|---|---|---|
| cadre de capture 936×640 px | `boite_h = 596` → **936×596** (image ajustée à 920×580) | `episode.py:556` |
| battement à **+3,5 %** | `0.034` → **+3,4 %** | `episode.py:542` |
| clé de cache = moteur + voix + texte | moteur + voix + **vitesse** + texte | `episode.py:210` |
| fondu du visuel : 0,28 s | **0,28 s à l'entrée, 0,22 s à la sortie**, aucun sur le dernier plan | `episode.py:718-722` |
| ponctuation collée : `: ; ! ? » …` | contient aussi **`%`**, et `«` est collé au mot suivant | `episode.py:277` |

*La clé de cache était décrite de deux façons différentes dans ce même document : incomplète au
paragraphe du cache, exacte au paragraphe des performances. Les deux disent maintenant la même
chose.*

**Et un écart qui ne concerne pas ce document mais ma mémoire de travail**, noté ici parce qu'il
touche ce que cette chaîne fait vraiment : `memoire/etat-courant.md` annonçait depuis le 14/09
« moteur de voix : Piper par défaut ». **`episode.py` ne connaît pas Piper** — ses seuls choix
sont `auto | kokoro | edge`. La décision de basculer était réelle et journalisée, mais elle disait
« au prochain épisode produit », et aucun épisode n'a été produit depuis. Corrigé dans la mémoire
le 17/09 à 03:58.
