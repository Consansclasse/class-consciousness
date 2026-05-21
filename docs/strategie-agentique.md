# Stratégie agentique — class-consciousness

> Document de référence. Synthèse de quatre recherches conduites le 2026-05-19
> (fondations de l'IA agentique, doctrine Y Combinator, RAG agentique, concept
> d'« application IA-native »). Sert de base au futur chantier de refonte du
> pipeline RAG. **Ce document n'est pas un plan d'implémentation** : il acte un
> diagnostic, une synthèse de l'état de l'art et un cap. Le plan détaillé,
> découpé en lots, fera l'objet d'un document séparé à valider avant tout code.

## 1. Objet

Le porteur vise à hisser `class-consciousness` au niveau d'une application
« IA-native » et « agentique » au sens de l'écosystème Y Combinator. La question
posée à l'audit était : *où en sommes-nous, et qu'est-ce que cela impliquerait ?*

Réponse courte : le projet est un **RAG hybride pré-agentique**. Il a déjà le
plus difficile — le moat (corpus + double vérification). Il lui manque la
**boucle de contrôle** qui définit l'agentique. Et — point décisif — combler ce
manque ne contredit pas la règle d'or anti-hallucination : cela la sert.

## 2. Diagnostic — l'état du pipeline RAG

Le pipeline actuel (`services/rag.py`) : `embed → retrieve (Qdrant + FTS, RRF)
→ rerank → generate → juge sémantique`. Il dépasse déjà le RAG classique pur
(reranking cross-encoder, décomposition de question optionnelle, juge
d'entailment en aval). Mais les étapes sont **câblées dans le code** : c'est un
*workflow*, pas un *agent*.

Échelle d'autonomie (d'après Barnacle.ai, 2025) :

| Niveau | Type | Boucle de contrôle |
|---|---|---|
| 1 | Outil augmenté par IA | aucune |
| 2 | **Workflow piloté par IA** ← *nous sommes ici* | fixée dans le code |
| 3 | Planification dynamique | vraie boucle, adaptation |
| 4 | Travailleur autonome | long-horizon, aspirationnel |

La distinction fondatrice est celle d'Anthropic (« Building Effective Agents »,
déc. 2024) : un **workflow** orchestre LLM et outils via des chemins prédéfinis ;
un **agent** dirige dynamiquement son propre processus et l'usage de ses outils.
Devenir agentique (niveau 3) = laisser le LLM décider, à chaque tour : *ai-je
assez de matière ? dois-je chercher autrement ? ma réponse est-elle assez
soutenue pour être publiée — ou dois-je refuser ?*

## 3. L'insight décisif — agentique ↔ règle d'or ↔ budget

C'est le résultat le plus important de l'audit. Les patterns agentiques se
divisent en deux familles aux effets opposés sur la fidélité aux sources :

**Patterns qui RÉDUISENT l'hallucination** — routage de complexité, évaluation
des passages (CRAG), récupération itérative bornée, juge d'entailment,
abstention apprise. L'agent peut *chercher mieux* ou *refuser proprement* au
lieu de combler un trou. Dans un **corpus clos**, l'agentique réduit donc le
risque : les hallucinations naissent d'un contexte insuffisant ou bruité —
l'agentique traite les deux.

**Patterns qui AUGMENTENT l'hallucination** — chaînes d'agents longues, mémoire
de travail non contrôlée, raisonnement libre sans ancrage. AbstentionBench
(arXiv 2506.09038) le démontre : le raisonnement intensif *dégrade* l'abstention
de 24 % en moyenne — le modèle fabrique une argumentation plausible plutôt que
d'avouer son ignorance.

**Conséquence** : les patterns « sûrs » sont aussi les moins chers ; les
patterns « risqués » sont aussi les plus coûteux. Il n'y a donc **pas de dilemme
budget ↔ fidélité**. Le vrai choix est : pipeline figé actuel *vs* **agentique
ciblée et bornée**. La règle d'or n'interdit pas l'agentique — elle sélectionne
laquelle.

## 4. État de l'art — l'agentic RAG

RAG classique = pipeline linéaire déterministe, aveugle à sa propre qualité.
RAG agentique = la récupération devient une **décision**. Patterns concrets :

- **Routage de complexité (Adaptive-RAG)** — un classifieur léger trie les
  questions : simple → une passe ; complexe → boucle. Un SVM sur TF-IDF atteint
  93 % de F1 et économise ~28 % de tokens, sur CPU, en <10 ms.
- **CRAG (Corrective RAG)** — un évaluateur léger classe les passages récupérés
  (correct / ambigu / insuffisant) *avant* la génération ; déclenche une
  re-recherche ou une reformulation si la matière est faible.
- **Récupération itérative (FAIR-RAG, IRCoT)** — l'agent identifie les lacunes,
  formule des sous-requêtes ciblées, relance. Optimum empirique : **2–3
  itérations**, cap dur à 3 (au-delà : rendements décroissants, dérive).
- **Self-RAG** — vérification endogène par tokens de réflexion. Idéal mais exige
  un fine-tuning (GPU) : hors de portée ici.
- **Multi-agent RAG** — agents spécialisés (orchestrateur, retrievers, critic).
  Qualité maximale, coût ×5–10 : hors budget en production générale.

Notre juge sémantique actuel est déjà le successeur fonctionnel de CRAG et du
pattern *evaluator-optimizer* — une brique agentique partiellement en place.

## 5. Doctrine Y Combinator

YC consacre ~50 % de ses derniers batchs aux agents. RFS phares : « Software for
Agents », « AI Operating System for Companies ». La doctrine de Diana Hu
(playbook AI-native) : *closed-loop* (chaque interaction devient un artefact
réexploitable), organisation *queryable*, l'IA comme OS, *data flywheel*.

Les 7 moats d'une startup IA (Friedman/Hu/Taggar) : Process, Resource, Switching
Costs, Counter-Positioning, Brand & Trust, Network Effects, Scale.

**Ce que le projet coche déjà** :
- Corpus propriétaire = moat « Resource Power » ; passe l'*OpenAI test* (ChatGPT
  ne peut pas répliquer un corpus marxiste TEI sourcé).
- Double vérification citationnelle = *evals-as-moat* — exactement ce que fait
  Harvey (legal AI) pour ses citations.
- Refus explicite plutôt qu'hallucination = le conseil de production YC textuel
  *« le silence est préférable à la distorsion »*.
- Closed-loop + observabilité = construits dans les lots A–C de mai 2026
  (persistance `RagInteraction`, feedback, Prometheus).

**Ce qui manque** : la boucle agentique ; les interfaces *machine-first* (API
pensée pour des agents tiers) — secondaire.

## 6. AI-native OS — ce qui sert la mission, ce qui la trahirait

Le concept « l'IA comme OS » (Karpathy, *Software 3.0*) : le LLM comme noyau
d'orchestration, toute la donnée *queryable*, un flywheel fermé. L'application
la plus proche de notre cas est **NotebookLM** — RAG fermé sur corpus privé,
aucune connaissance extérieure.

**Sert la mission** : rendre *queryables les métadonnées du corpus* (couverture,
auteurs, lacunes) ; exploiter les traces d'échec (`NOT_SUPPORTED`, refus) pour
identifier les lacunes documentaires à combler ; les evals continues comme
garantie de fiabilité académique ; un agent *archiviste assistant* (notices TEI,
liens VIAF) dont les propositions sont validées par un humain.

**Trahirait la mission** : une interface « tout queryable » sans garde-fou de
corpus ; un flywheel de fine-tuning sur des interactions non vérifiées ; un
agent autonome modifiant le corpus sans validation humaine ; l'obsession du
volume sur la couverture vérifiable.

La formule juste : non pas « l'IA comme OS qui répond à tout », mais **l'IA
comme OS qui sait ce qu'il ne sait pas — et qui le documente**.

## 7. Le plan — patterns priorisés (valeur / coût)

| Rang | Pattern | Apport | Coût | Verdict |
|---|---|---|---|---|
| 1 | Routage de complexité | n'itère que si nécessaire ; ~−28 % tokens | quasi nul (CPU) | retenu |
| 2 | Cache sémantique (Redis) | ~40 % des questions sont des paraphrases | faible (Redis déjà là) | retenu |
| 3 | CRAG léger | filtre/évalue les passages avant génération | modéré (réutilise le reranker Qwen3) | retenu |
| 4 | Prompt caching des passages | −40 à −80 % de coût sur appels répétés | nul (API Anthropic) | retenu |
| 5 | Récupération itérative bornée | couvre les questions multi-hop (cap 3) | ×2–3 appels, amorti par cache | retenu (déclenché par le routage) |
| — | Multi-agent complet | qualité maximale | ×5–10 le coût | écarté (budget) |
| — | Self-RAG entraîné | vérification endogène | GPU requis | écarté (budget) |

**Architecture cible** : « System 1 + System 2 sélectif » — heuristiques rapides
(routage, reranking) pour la majorité des questions, boucle de raisonnement
lente *seulement* pour les cas complexes détectés. Le budget se dépense là où il
change le résultat, pas uniformément.

## 8. Garde-fous non négociables

1. **Juge sémantique en bout de chaîne** — invariant. Aucune optimisation de
   coût ne le désactive.
2. **Cap de 3 itérations** — invariant. Le raisonnement non borné dégrade
   l'abstention.
3. **Plafonds durs** de tokens, de temps et de budget par requête — contre le
   *« denial of wallet »* (boucle infinie qui vide le compte API).
4. **Corpus clos** — c'est un avantage, jamais une contrainte à contourner :
   aucune recherche web, aucune connaissance extérieure.
5. **Traçabilité** — chaque décision de l'agent (re-chercher, refuser, itérer)
   est journalisée et observable, comme l'exige déjà `/debug-rag`.

## 9. Sources principales

- Anthropic — *Building Effective Agents* : <https://www.anthropic.com/research/building-effective-agents>
- *Agentic RAG: A Survey* — arXiv 2501.09136
- *Corrective RAG (CRAG)* — arXiv 2401.15884
- *Self-RAG* — arXiv 2310.11511
- *Adaptive-RAG* (routage par complexité) — arXiv 2403.14403
- *FAIR-RAG* (itératif fidèle) — arXiv 2510.22344
- *AbstentionBench* — arXiv 2506.09038
- *Correctness is not Faithfulness in RAG* — arXiv 2412.18004
- YC — *Requests for Startups* : <https://www.ycombinator.com/rfs>
- YC — *The Playbook for Building an AI-Native Company* (Diana Hu)
- YC — *The 7 Most Powerful Moats for AI Startups*
- A. Karpathy — *Software Is Changing (Again)* (Software 3.0), YC AI Startup School 2025
