# ADR-0004 — Modèle de données IFLA-LRM + séparation Postgres/Qdrant

- **Statut** : accepté
- **Date** : 2026-04-27

## Contexte

Marx publié × N traductions × M éditions critiques × P manuscrits. Les commentaires académiques requièrent de distinguer Œuvre (concept abstrait), Expression (langue/version), Manifestation (édition), Item (exemplaire). Le modèle relationnel doit refléter cette structure proprement.

Par ailleurs, séparation propre entre données de vérité (Postgres) et indices de recherche (Qdrant).

## Décision

### Modèle bibliographique

Inspiré de **IFLA-LRM** (ex-FRBR) :

```
authors           (id, ark, slug, name_canonical, name_variants[],
                   birth, death, wikidata_qid, viaf_id, idref_id, bnf_id, …)
works             (id, ark, slug, author_id, title_canonical, year_first_pub,
                   original_lang, lrm_form, wikidata_qid, …)
work_relations    (work_id, related_work_id, kind: continues|reply_to|critique_of)
expressions       (id, ark, work_id, language, kind: original|translation|critical_edition,
                   editor_or_translator_ids[])
manifestations    (id, ark, expression_id, publisher, place, year, isbn, csl_jsonb,
                   license, source_provenance, copyright_status)
items             (id, manifestation_id, source_url, ocr_pipeline, scan_iiif_manifest_url)
contributors      (id, ark, person_id, role: translator|editor|annotator|preface_writer)
```

### Documents et structure

```
documents         (id, ark, manifestation_id, tei_xml_path, tei_sha256,
                   ingestion_version, schema_version, signed_by, signed_at)
sections          (id, ark, document_id, parent_id, kind: book|part|chapter|section|paragraph|note,
                   label, ordinal, n_attr, page_start, page_end)
chunks            (id, ark, section_id, sequence, text, tokens_count,
                   qdrant_point_id uuid,         -- ref vers Qdrant
                   tei_xpath, char_start, char_end,
                   variant_witnesses[])
```

### Variantes textuelles

```
variants          (id, lemma_chunk_id, witness_sigil, reading_text,
                   kind: addition|omission|substitution, editorial_note_md)
```

### Taxonomie SKOS

```
concepts          (id, ark, slug, pref_label_fr, pref_label_en, alt_labels jsonb,
                   skos_uri, wikidata_qid, lcsh_id, rameau_id, definition_md)
concept_relations (subject_id, predicate: broader|narrower|related, object_id)
concept_occurrences (chunk_id, concept_id, confidence, validated_by, validated_at)
```

### Linked Open Data externe

```
external_links    (entity_kind, entity_id, source: wikidata|viaf|wikisource|gallica,
                   url, fetched_at)
```

### Commentaires et utilisateur

```
users             (id, email, role: reader|contributor|maintainer|steward,
                   verified_at, public_handle, gpg_pubkey_armored)
commentaries      (id, ark, user_id, target_kind, target_id, body_md,
                   sources_jsonb,             -- liste obligatoire de chunk_arks (CHECK NOT NULL)
                   signed_at, signature, status: draft|published|retracted)
```

### Releases et préservation

```
corpus_releases   (id, semver, manifest_sha256, sigstore_bundle, swh_id,
                   ipfs_cid, internet_archive_url, released_at, released_by)
```

### Q&A logs (anonymisés)

```
queries           (id, question_hash, retrieved_chunk_arks[], answer_text,
                   citations_jsonb, model_version, prompt_hash, latency_ms,
                   refused boolean, refusal_reason, created_at)
```

### Index Postgres

- B-tree : `chunks.ark`, `(section_id, sequence)`, FK partout
- Aucun index FTS, aucune colonne vectorielle

### Index Qdrant

Collection `chunks` avec deux vecteurs nommés :
- `dense` : 1024d cosine HNSW (m=16, ef_construct=64, ef_search=128)
- `sparse` : BM25 sur le texte
- Payload indexé : `chunk_ark`, `author_id`, `work_id`, `expression_lang`, `period`, `concept_ids[]`
- Quantization scalaire activée

### Séparation des responsabilités

- **Postgres** : vérité relationnelle, ACID, contraintes d'intégrité, audit
- **Qdrant** : recherche hybride uniquement (dense + sparse + filtres payload)

`chunks.qdrant_point_id` est l'unique pont. Une mise à jour de chunk déclenche un upsert Qdrant transactionnel (commit Postgres → upsert Qdrant ; rollback en cas d'échec).

## Conséquences

Bénéfices :
- Modèle bibliothéconomique standard, adopté par les bibliothèques universitaires
- Interopérabilité OAI-PMH, DTS, SPARQL natives
- Séparation Postgres/Qdrant : chacun fait ce qu'il fait le mieux

Coûts :
- 7+ tables pour modéliser un texte : verbeux mais nécessaire
- Synchronisation Postgres ↔ Qdrant à gérer (transactionnelle)

## Alternatives rejetées

- Document store unique (MongoDB-style) : perd l'intégrité référentielle
- Embedder dans Postgres avec pgvector : cf. ADR-0001 (perf et ergonomie sparse moindres)
- Modèle plat (un seul `texts` table) : insuffisant pour MEGA²-style
- FRBR original (ex-IFLA-LRM) : on prend la version moderne LRM
