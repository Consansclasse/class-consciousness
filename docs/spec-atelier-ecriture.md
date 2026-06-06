# Spec — Atelier d'écriture (rédaction longue ancrée sur le corpus)

> Spec testable, ancrée sur une vérification du code réel (file:line ci-dessous).
> Statut : proposée. Complète `plan-agentique.md` (le RAG Q&A) par un **3ᵉ mode**
> in-app : développer un **article/dissertation long**, au-delà du question-réponse.

## 1. Contexte & problème

`/chat` répond à *« que dit le corpus ? »* en **un tour** (1 question → 1 dissertation
de 4-5 paragraphes), explicitement **mono-tour, sans mémoire** (`models/conversation.py:9-11`).
C'est puissant pour interroger, **insuffisant pour travailler** : impossible de
*construire* un texte long, de *développer* un argument section par section, de
mêler **sa propre analyse** à des **passages sourcés vérifiés**, ni d'**exporter**.
L'utilisateur plafonne sur le Q&A.

L'Atelier comble ce manque **sans jamais affaiblir la règle d'or** (`.claude/rules/no-unsourced-rag.md`).

## 2. Objectif / Non-objectifs

**Objectif.** Un mode in-app où un **utilisateur connecté** développe un article
long ancré sur le corpus : plan → dossier de sources → rédaction section par
section (blocs **sourcés-vérifiés** générés + **voix-auteur** écrite par l'humain)
→ vérification d'ancrage → export.

**Non-objectifs (V1).** Publier l'article *dans* le corpus public (ingestion TEI) ;
éditeur WYSIWYG riche ; co-édition multi-utilisateurs ; export PDF/DOCX/CSL (Markdown
d'abord) ; mémoire conversationnelle injectée au moteur (l'ancrage reste par-phrase
sur les chunks corpus).

## 3. Le modèle d'intégrité (le cœur)

Le code ne connaît aujourd'hui que **deux états de phrase** : *exposable*
(`SUPPORTED`/`REFUSED_BY_LLM`) ou *écartée* (`citation.py:75-76`). Une prose tapée
par l'auteur serait classée `UNSOURCED` et supprimée. Il faut donc introduire une
**typologie de blocs**, distincte **en base** et **à l'écran** :

| Classe de bloc | Qui le produit | Vérification | Règle |
|---|---|---|---|
| **A — Sourcé-vérifié** | le moteur (`generate`→`verify_response`) | les 2 garde-fous ; seules les phrases `SUPPORTED` survivent | engage **le corpus** ; jamais exposé/exporté si non `SUPPORTED` |
| **B — Voix-auteur** | l'humain (texte libre) | **jamais** soumis au juge comme s'il prétendait au corpus | engage **l'auteur** ; marqué non-sourcé ; **jamais attribuable à Bilan** |
| **C — Citation directe** | sélection d'un passage du dossier | contrôle littéral (fuzzy) | reproduction mot pour mot + attribution |

**Invariants non négociables :**
1. Le **contexte d'ancrage du moteur reste STRICTEMENT les chunks corpus**
   (`rag.py:_build_context`). La voix-auteur peut servir de *consigne de
   style/plan*, **jamais** de source d'autorité factuelle (→ risque n°1).
2. **Éditer** une phrase d'un bloc A **invalide son verdict** → re-`verify_response`
   avant qu'elle puisse rester « sourcée » (→ risque n°2 ; cf. `citation-honest-vs-literal.md:16-28`).
3. Un bloc A citant un **adversaire** (IC/Trotsky, fréquent dans Bilan) conserve
   l'attribution explicite ; le verdict `CONTRADICTED` le refuse (→ risque n°3).
4. **Jamais** désactiver `rag_verifier_enabled` ni affaiblir `_JUDGE_SYSTEM`.

## 4. Architecture — réutilisation (vérifiée)

**Réutiliser TEL QUEL** (rien à toucher) :
- Récupération : `_retrieve` (`rag.py:390`), `_rerank_and_select` (`rag.py:482`),
  `_build_context` (`rag.py:303`), `RerankedChunk` + appareil de sources
  (`rag.py:160-168`, payload ARK/auteur/offsets).
- Vérification : `verify_response` + juge + contrôle littéral, verdicts, kill-switch
  (`citation.py:48-106,234-351`).
- Cœur du `SYSTEM_PROMPT` : la **règle d'or** + le tool `rediger_reponse` + la
  consigne d'attribution (`rag.py:88-127`, `anthropic.py:35-92`).
- Auth/session (`core/deps.py:29`, `main.py:64-70`), quota peek/consume
  (`services/quota.py:44-78`), facturation Stripe (`abonnement.py:255-286`,
  `clients/stripe.py:168-196`), **SSE** (`qa.py:448-553`), ownership+soft-delete
  (`services/conversation.py:37-133`), figeage `cited_chunks` (`rag_interaction.py:76-84`).
- Front : gabarit page-app (`compte.astro:19-48`), `requireAuth` client
  (`chat.astro:889-944`), `AccountMenu`, deep-link `?c=/?from=` (`chat.astro:567-574`).

**Réutiliser AVEC MODIFICATION :**
- `anthropic.generate` (`anthropic.py:303`) : ajouter un canal *plan + consigne de
  section + sections déjà écrites (style only)* ; **préserver** `cache_control`
  ephemeral sur le contexte corpus.
- `SYSTEM_PROMPT` → dériver un **prompt « atelier »** : garder la règle d'or +
  l'attribution, **rendre paramétrables le genre et la longueur** (supprimer le
  carcan « 4-5 paragraphes / 15-20 phrases » `rag.py:73-74`).
- `verify_response` → pour vérifier une **prose collée par l'auteur** : étape amont
  de **segmentation en phrases + attribution de source_ids** (via `_retrieve`),
  puis `GeneratedAnswer` synthétique ; le moteur fuzzy+juge se réutilise tel quel.
- `enforce_rag_quota` (`qa.py:255-315`) → dépendance sœur, **identity distincte**
  `atelier:user:{id}` + settings free/cap dédiés.

**À CRÉER (20 manques confirmés) :** service `atelier.py`, modèle de données
document/section, endpoints `/atelier`, point d'entrée front, éditeur, export.

## 5. Modèle de données (nouvelles tables)

`conversations`/`rag_interactions` ne conviennent pas (mono-tour, échange figé —
`rag_interaction.py:50-85`). Nouvelles tables (migration Alembic après `20260606_0014`,
style `20260521_0012`) :

- **`atelier_documents`** : `id` PK ; `user_id` FK users CASCADE (indexé) ;
  `title` String(200) ; `status` String(16) (`brouillon|publie|archive`) ;
  `outline` JSONB (titres de sections + ordre) ; `created_at`/`updated_at`
  (`updated_at` = tri) ; `published_at` nullable ; `deleted_at` nullable (soft-delete).
- **`document_sections`** : `id` PK ; `document_id` FK CASCADE (indexé) ;
  `position` Integer (ordre réorganisable) ; `heading` String ;
  `author_body` Text (**bloc B**, voix-auteur, non vérifiée) ;
  `sourced_blocks` JSONB (**blocs A** : liste de phrases `SUPPORTED` figées avec
  `citations` + `cited_chunks` à la `rag_interaction.cited_chunks`, + `verdict` +
  `needs_reverify: bool`) ; `created_at`/`updated_at`.

Enregistrer dans `models/__init__.py`.

## 6. API — endpoints `/atelier`

Procédure `apps/api/CLAUDE.md` (schema → service → router → `include_router` `main.py:156`
→ test testcontainers). Tous `Depends(current_user)` + dépendance quota dédiée.

- `POST /atelier/documents` — crée un document (optionnel `from_interaction_id` pour
  amorcer avec la matière sourcée d'une réponse `/chat`).
- `GET /atelier/documents` / `GET /atelier/documents/{id}` — liste / détail (ownership
  + 404 d'autrui, `qa.py:572-576`).
- `PATCH /atelier/documents/{id}` — titre, outline, status. `DELETE` — soft-delete.
- `PATCH /atelier/documents/{id}/sections/{sid}` — édite `author_body`/heading/position.
- `POST /atelier/documents/{id}/sections/{sid}/draft` — **SSE** (réutilise
  l'archi `qa.py:448-553`) : `_retrieve`/`_rerank` → prompt atelier → `generate`
  → `verify_response` → events `stage`/`result`/`error` ; **n'écrit dans le bloc A
  que les phrases `SUPPORTED`**. Facturable.
- `POST /atelier/documents/{id}/verify` — segmente + attribue + vérifie une prose
  fournie (V2) → renvoie des `Sentence` (verdicts) pour montrer à l'auteur ce qui
  est / n'est pas soutenu. Facturable.
- `GET /atelier/documents/{id}/export?format=markdown` — document + appareil de
  références vérifié (à partir des `cited_chunks` figés).

**Auth/quota/facturation** (gabarit `qa.py:255-349`, **inchangé sur le fond**) :
identity `atelier:user:{id}` ; ordre invariant *générer → consume_quota si succès →
persister → facturer* ; clé d'idempotence Stripe **`atelier-{doc}-{section}-{rev}`**
(jamais `qa-…`) ; agréger **tous** les `GenerationUsage` (génération + juge) puis
facturer `.billable_tokens`. Bornes d'entrée dédiées (la limite `question ≤ 500`
de `QaRequest` `schemas/qa.py:28` est trop courte).

## 7. Moteur — `services/atelier.py`

Fonctions sœurs de `answer_question` (ne PAS surcharger la passe unique) :
- `build_dossier(queries) -> list[RerankedChunk]` — `_retrieve` + `_rerank_and_select`,
  expose les chunks structurés (dossier de sources par section).
- `draft_section(*, heading, instruction, dossier, style_context) -> RagResult-like` —
  `generate` (prompt atelier, **contexte = chunks corpus uniquement**) →
  `verify_response`. `style_context` (sections déjà écrites) n'entre **que** comme
  consigne de style, **jamais** comme source.
- `verify_user_prose(text, *, dossier) -> list[Sentence]` (V2) — segmente, attribue
  via `_retrieve`, construit `GeneratedAnswer`, `verify_response`.

## 8. Front — page `/atelier`

- Page sur le gabarit app : `BaseLayout noHeader noFooter noindex` + `<SiteHeader barless />`
  + header minimal (`data-menu-open`, liens, `<AccountMenu>` ids uniques) +
  `#atelier-root[hidden]` dévoilé après `requireAuth()` (copie `compte.astro`/`chat.astro`).
- **Point d'entrée** : bouton « Développer en article » greffé dans `attachFeedback`
  (`chat.astro:453-518`), conditionné à `interactionId != null`, style `FB_BTN` →
  `/atelier?from=<interactionId>`.
- **Mutualiser** : extraire `renderAnswer`/`issueLabel`/types (`chat.astro:356-421,237-265`)
  vers `src/lib/` pour réutiliser l'appareil de citations vérifiées (et aligner les
  types sur le schéma serveur enrichi : `quotedText`, `verdict`).
- **Éditeur** : V1 = vanilla DOM (cohérent avec l'existant ; `islands/` vide, zéro
  React aujourd'hui). Distinction visuelle stricte **bloc A (sourcé, avec renvois
  ⁽ⁿ⁾) vs bloc B (voix-auteur, marqué « analyse personnelle »)**. Palette stricte,
  locators sémantiques (`cc-web-conventions`). Un îlot React n'est justifié que si
  l'éditeur devient riche (phase ultérieure).

## 9. Tranche V1 (fil rouge, build minimal)

1. Depuis une réponse `/chat` vérifiée → « Développer en article » crée un document
   amorcé avec la matière sourcée de cette réponse.
2. `/atelier` : titre + outline éditable (liste de sections) ; par section, un bouton
   **« Rédiger (ancré) »** (→ bloc A vérifié, SSE) **et** une zone **voix-auteur** libre.
3. Persistance document + sections (status `brouillon`).
4. **Export Markdown** avec appareil de références vérifié.

Exclus de V1 : `verify_user_prose`, publication corpus, éditeur riche, PDF/CSL.

## 10. Critères d'acceptation (testables)

- **CA-1 (règle d'or, bloc A).** GIVEN une section, WHEN je clique « Rédiger (ancré) »,
  THEN seules des phrases `SUPPORTED` entrent dans le bloc A ; aucune phrase non
  `SUPPORTED` n'est jamais affichée ni exportée (miroir `test_pipeline_rag.py:184,213`).
- **CA-2 (voix-auteur).** GIVEN du texte tapé en zone voix-auteur, THEN il est stocké
  dans `author_body`, **jamais** soumis au juge, et rendu **visuellement distinct**
  + jamais attribué à Bilan.
- **CA-3 (édition invalide le verdict).** GIVEN une phrase de bloc A éditée à la main,
  THEN elle passe `needs_reverify=true` et n'est ré-« sourcée » qu'après un
  `verify_response` réussi (miroir `citation-honest-vs-literal.md`).
- **CA-4 (adversaire).** GIVEN un draft qui prête à Bilan un propos qu'il combat
  (IC/Trotsky), THEN le verdict `CONTRADICTED` l'exclut du bloc A (miroir
  `test_pipeline_rag.py:302`).
- **CA-5 (auth).** GIVEN un visiteur anonyme, WHEN il appelle un endpoint `/atelier`,
  THEN 401 ; la page `/atelier` redirige vers `/login?next=`.
- **CA-6 (ownership).** GIVEN le document d'autrui, THEN 404 (ne révèle pas l'existence).
- **CA-7 (quota/facturation).** GIVEN dépassement du quota gratuit atelier sans
  abonnement, THEN 402 ; WHEN un draft réussit en PAYG, THEN un meter Stripe est émis
  avec idempotence `atelier-{doc}-{section}-{rev}`, agrégeant génération + juge ;
  un refus pré-génération ne coûte rien.
- **CA-8 (export).** GIVEN un document avec blocs A + B, WHEN j'exporte en Markdown,
  THEN les passages sourcés portent leur appareil de références (auteur, titre, ARK,
  offsets) et la voix-auteur est typographiquement distincte.

## 11. Surface de test

`apps/api/tests/integration/` (testcontainers, pas de mocks) : `test_atelier_documents.py`
(CRUD + ownership + soft-delete), `test_atelier_draft.py` (CA-1/3/4, réutilise les
fixtures de `test_pipeline_rag.py`), `test_atelier_quota.py` (CA-5/6/7),
`test_atelier_export.py` (CA-8). Front : spec Playwright `e2e/specs/11-atelier.spec.ts`
(porte d'auth, point d'entrée depuis /chat, distinction A/B, export).

## 12. Risques & mitigations

| # | Risque | Mitigation |
|---|---|---|
| 1 | Contamination voix-auteur → sourcé | contexte moteur = chunks corpus **uniquement** ; voix-auteur = style/plan, jamais source |
| 2 | Phrase A éditée puis exportée comme corpus | `needs_reverify` + re-`verify_response` avant export |
| 3 | Propos d'adversaire (Bilan/IC/Trotsky) | juge `CONTRADICTED` + attribution explicite obligatoire |
| 4 | Surfacturation multi-appels | quota au niveau document, identity dédiée, idempotence par révision |
| 5 | Latence (N sections × generate+judge, `max_tokens=16000`) | SSE par section ; cache_control corpus ; pas de génération auto de tout l'article |

## 13. Hors-scope explicite

Publication dans le corpus public (TEI/ingestion `cc-corpus-ingest`), co-édition,
versionnement riche, export PDF/DOCX/CSL, mémoire conversationnelle injectée.

## 14. Phasage

- **V1** : §9 (preuve de valeur, build minimal, gratuit en dev via clé API de dev).
- **V2** : `verify_user_prose` (l'auteur voit ce qui n'est pas soutenu), export CSL.
- **V3** : publication vers le corpus (gate éditorial + intégrité), éditeur riche (îlot React).

## 15. Références vérifiées (extrait)

Moteur `services/rag.py:61-134,160-168,303-555,558-743` · vérif
`services/citation.py:48-106,234-351` · génération `clients/anthropic.py:35-92,303-394` ·
endpoints/quota/billing `routers/qa.py:255-553`, `services/quota.py:44-78`,
`services/abonnement.py:255-286` · données `models/conversation.py`,
`models/rag_interaction.py:50-101` · front `apps/web/src/pages/chat.astro`,
`compte.astro`, `corpus/[issue]/[article].astro` · règles
`.claude/rules/no-unsourced-rag.md`, `.claude/rules/citation-honest-vs-literal.md`.
