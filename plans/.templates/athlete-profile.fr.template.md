# Fiche coureur — template

> Remplace chaque champ `<...>` par tes propres valeurs. Le skill `entraineur` lit ce fichier au début de chaque session de coaching et applique les règles qu'il contient. **Ne commite pas ce fichier** : il vit dans le dossier `plans/`, ignoré par git.

## 1. Profil

- **Nom / pseudo** : `<ton nom>`
- **Date de naissance** : `<YYYY-MM-DD>`
- **Sexe** : `<M | F | NB>`
- **Années de course régulière** : `<années>`
- **Activité pro / contraintes horaires** : `<description courte>`

## 2. Métriques actuelles

> Mets à jour après chaque test ou recalibrage. Date la ligne pour garder l'historique.

| Métrique | Valeur | Source / date |
|---|---|---|
| VDOT (Daniels) | `<VDOT>` | `<course ou test, YYYY-MM-DD>` |
| FC max (mesurée) | `<bpm>` | `<test ou max observée YYYY-MM-DD>` |
| FC repos | `<bpm>` | `<moyenne 7 derniers matins>` |
| Poids | `<kg>` | `<YYYY-MM-DD>` |
| FC au seuil | `<bpm>` | `<test ou estimation>` |

### Allures cibles dérivées (Daniels VDOT)

| Allure | Min/km | Source |
|---|---|---|
| Endurance (E) | `<m:ss-m:ss>` | Zone E Daniels |
| Marathon (M) | `<m:ss>` | Allure M Daniels |
| Seuil (T) | `<m:ss-m:ss>` | Allure T Daniels |
| Intervalle (I) | `<m:ss-m:ss>` | Allure I Daniels |
| Répétition (R) | `<m:ss-m:ss>` | Allure R Daniels |

## 3. Calendrier de courses

> Liste tes courses cibles. Le skill `entraineur` se base sur ces dates pour structurer les plans (phases base/build/peak/taper, placement des tests, pauses post-course).

| Date | Distance | Course | Statut | Cible chrono |
|---|---|---|---|---|
| `<YYYY-MM-DD>` | `<10K | semi | marathon | ultra Xkm>` | `<nom course>` | `<A | B | rep>` | `<HH:MM>` |

A = course objectif principal, B = secondaire, rep = répétition générale.

## 4. Contraintes physiques

> Liste les contraintes structurelles (anciennes blessures, fragilités, limitations). Le skill `entraineur` adapte les séances en conséquence (pas de côtes si un tendon est fragile, etc.).

- **Antécédents blessures** : `<blessure, côté, année>`
- **Zones fragiles** : `<zones à surveiller>`
- **À éviter** : `<types d'effort à proscrire>`
- **À pratiquer obligatoirement** : `<protocole de renfo, fréquence>`

## 5. Volumes & disponibilités

| Champ | Valeur |
|---|---|
| Volume hebdo max (peak) | `<km>` km/sem |
| Volume hebdo confort base | `<km>` km/sem |
| Jours de course / sem max | `<n>` |
| Convention semaine | `<FR : Lundi = jour 1 | US : Dimanche = jour 1>` |

### Disponibilités par jour (créneau typique)

| Jour | Durée max | Note |
|---|---|---|
| Lundi | `<min>` | `<contrainte récurrente éventuelle>` |
| Mardi | `<>` | |
| Mercredi | `<>` | |
| Jeudi | `<>` | |
| Vendredi | `<>` | |
| Samedi | `<>` | |
| Dimanche | `<min>` | `<ex. créneau sortie longue>` |

## 6. Préférences nutrition course

> Le skill `entraineur` propose des plans gels/hydratation alignés sur ces préférences sans les remettre en cause à chaque session.

- **Format gel préféré** : `<gel | liquide | barre>` — un seul format
- **Gel starter** : `<oui, H-x | non>`
- **Solide en course** : `<oui | non | selon terrain>`
- **Hydratation** : `<eau | iso | mix, concentration>`
- **Configuration du gilet (ultra)** : `<nb flasques, contenu>`
- **Caféinés** : `<nombre et moment | aucun>`
- **Préférences digestion** : `<intolérances, formats à éviter, marques validées>`

### Schéma type marathon route

`<gel toutes les X km / Y g/h cible / nb total>`

### Schéma type ultra avec gilet

`<gel toutes les X min / Y g/h cible / iso flasque / refill aux ravitos>`

## 7. Renfo & musculation

| Bloc | Jour | Durée | Focus |
|---|---|---|---|
| `<bloc 1>` | `<jour>` | `<min>` | `<zone ou protocole>` |
| `<bloc 2>` | `<jour>` | `<min>` | `<zone ou protocole>` |

## 8. Anti-patterns personnels (préférences figées)

> Le skill `entraineur` ne doit jamais re-proposer ces choses :

- ❌ `<chose à ne jamais re-proposer>`
- ❌ `<...>`
- ❌ `<...>`

## 9. Notes libres

`<champ libre pour tout ce qui ne rentre pas dans les sections ci-dessus>`
