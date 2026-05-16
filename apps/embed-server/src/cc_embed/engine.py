# SPDX-License-Identifier: AGPL-3.0-or-later
"""Moteur d'inférence Qwen3 — embeddings + reranking sur GPU.

Embeddings : Qwen3-Embedding, pooling du dernier token réel + normalisation L2,
conformément à la fiche modèle officielle (padding à gauche, dernier état caché).

Reranking : Qwen3-Reranker, modèle causal jugeant une paire (requête, document)
par les logits « yes » / « no » du dernier token.

Chargement paresseux : l'embedder est chargé au démarrage du serveur (lifespan),
le reranker au premier appel `/rerank`. Sur RTX A2000 12 Go, l'embedder 8-bit
(~9 Go) et le reranker 4-bit (~3 Go) ne cohabitent pas confortablement — le
reranker n'est donc chargé qu'à la demande.

Les forward passes sont protégées par un verrou : un seul lot GPU à la fois,
les requêtes HTTP concurrentes sont sérialisées plutôt que de risquer un OOM.
"""

from __future__ import annotations

import threading

import structlog
import torch
from torch.nn.functional import normalize
from transformers import (
    AutoModel,
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)

from cc_embed.config import settings

log = structlog.get_logger(__name__)

# Instruction de requête (corpus francophone : revue Bilan, théorie marxiste).
# Les documents (chunks) sont embeddés sans instruction — convention Qwen3.
QUERY_INSTRUCTION = (
    "Étant donné une question, retrouve les passages du corpus marxiste "
    "qui permettent d'y répondre."
)
RERANK_INSTRUCTION = "Détermine si le document répond à la question posée."


def _quant_config(quant: str) -> BitsAndBytesConfig | None:
    """Traduit `8bit`/`4bit`/`none` en `BitsAndBytesConfig` (ou None)."""
    if quant == "8bit":
        return BitsAndBytesConfig(load_in_8bit=True)
    if quant == "4bit":
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
    if quant == "none":
        return None
    raise ValueError(f"quant inconnu : {quant!r} (attendu 8bit | 4bit | none)")


def _last_token_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Pooling Qwen3-Embedding : état caché du dernier token réel de chaque séquence.

    Avec un padding à gauche, le dernier token est toujours réel → `[:, -1]`.
    Le cas padding à droite est géré par robustesse.
    """
    left_padding = bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item())
    if left_padding:
        return last_hidden[:, -1]
    seq_len = attention_mask.sum(dim=1) - 1
    batch = last_hidden.shape[0]
    return last_hidden[torch.arange(batch, device=last_hidden.device), seq_len]


class Embedder:
    """Qwen3-Embedding — embeddings normalisés L2, prêts pour la distance cosinus."""

    def __init__(self) -> None:
        self.model_name = settings.embed_model
        self._lock = threading.Lock()
        log.info("embedder.loading", model=self.model_name, quant=settings.embed_quant)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, padding_side="left")
        quant = _quant_config(settings.embed_quant)
        self.model = AutoModel.from_pretrained(
            self.model_name,
            quantization_config=quant,
            device_map=settings.device,
            dtype=torch.bfloat16,
        )
        self.model.eval()
        self.dim = int(self.model.config.hidden_size)
        log.info("embedder.loaded", model=self.model_name, dim=self.dim)

    @torch.inference_mode()
    def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        """Embedde une liste de textes. `input_type` ∈ {query, document}.

        Les textes sont tokenisés puis regroupés par longueur croissante : dans
        un lot, le padding s'aligne sur le plus long élément, donc rassembler
        des longueurs voisines minimise le calcul gaspillé en tokens de padding.
        L'ordre d'entrée est restitué dans le résultat.
        """
        if input_type not in ("query", "document"):
            raise ValueError(f"input_type invalide : {input_type!r} (attendu query | document)")
        prepared = (
            [f"Instruct: {QUERY_INSTRUCTION}\nQuery:{t}" for t in texts]
            if input_type == "query"
            else list(texts)
        )
        token_ids: list[list[int]] = self.tokenizer(
            prepared, truncation=True, max_length=settings.embed_max_tokens
        )["input_ids"]
        order = sorted(range(len(prepared)), key=lambda i: len(token_ids[i]))
        batches = self._pack_batches(order, token_ids)
        out: list[list[float]] = [[] for _ in prepared]
        with self._lock:
            for idx in batches:
                enc = self.tokenizer.pad(
                    {"input_ids": [token_ids[i] for i in idx]},
                    padding=True,
                    return_tensors="pt",
                ).to(self.model.device)
                hidden = self.model(**enc).last_hidden_state
                pooled = _last_token_pool(hidden, enc["attention_mask"])
                pooled = normalize(pooled, p=2.0, dim=1)
                for pos, vec in zip(idx, pooled.float().cpu().tolist(), strict=True):
                    out[pos] = vec
        return out

    @staticmethod
    def _pack_batches(order: list[int], token_ids: list[list[int]]) -> list[list[int]]:
        """Empaquette les indices (triés par longueur croissante) en lots.

        Un lot est clos quand `nb x longueur_paddée` dépasserait le budget de
        tokens ou que le plafond de cardinalité est atteint. Comme `order` est
        croissant, le dernier indice ajouté fixe la longueur de padding du lot.
        """
        budget = settings.embed_token_budget
        max_count = settings.embed_batch_max
        batches: list[list[int]] = []
        current: list[int] = []
        for i in order:
            length = len(token_ids[i])
            if current and (
                (len(current) + 1) * length > budget or len(current) >= max_count
            ):
                batches.append(current)
                current = []
            current.append(i)
        if current:
            batches.append(current)
        return batches


class Reranker:
    """Qwen3-Reranker — score de pertinence ∈ [0,1] d'une paire (requête, document).

    Le modèle est causal : on lui fait juger « yes » / « no » et on prend la
    probabilité softmax du token « yes » au dernier pas de temps.
    """

    _PREFIX = (
        "<|im_start|>system\nJudge whether the Document meets the requirements "
        'based on the Query and the Instruct provided. Note that the answer '
        'can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    )
    _SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def __init__(self) -> None:
        self.model_name = settings.rerank_model
        self.device = settings.rerank_device
        self._lock = threading.Lock()
        log.info(
            "reranker.loading",
            model=self.model_name,
            quant=settings.rerank_quant,
            device=self.device,
        )
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, padding_side="left")
        # bitsandbytes ne quantifie que sur GPU : sur CPU, chargement fp32.
        on_cpu = self.device == "cpu"
        quant = None if on_cpu else _quant_config(settings.rerank_quant)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            quantization_config=quant,
            device_map=self.device,
            dtype=torch.float32 if on_cpu else torch.bfloat16,
        )
        self.model.eval()
        self._true_id = self.tokenizer.convert_tokens_to_ids("yes")
        self._false_id = self.tokenizer.convert_tokens_to_ids("no")
        self._prefix_ids = self.tokenizer.encode(self._PREFIX, add_special_tokens=False)
        self._suffix_ids = self.tokenizer.encode(self._SUFFIX, add_special_tokens=False)
        log.info("reranker.loaded", model=self.model_name)

    @torch.inference_mode()
    def score(self, query: str, documents: list[str]) -> list[float]:
        """Score chaque document vs `query` — probabilité de pertinence ∈ [0,1]."""
        scores: list[float] = []
        size = settings.rerank_batch_size
        content_max = settings.rerank_max_tokens - len(self._prefix_ids) - len(self._suffix_ids)
        with self._lock:
            # VRAM serrée (embedder 8B co-résident) : on récupère les blocs
            # caches libérables avant les forward passes du reranker.
            if self.device == "cuda":
                torch.cuda.empty_cache()
            for start in range(0, len(documents), size):
                batch = documents[start : start + size]
                pairs = [
                    f"<Instruct>: {RERANK_INSTRUCTION}\n<Query>: {query}\n<Document>: {doc}"
                    for doc in batch
                ]
                enc = self.tokenizer(
                    pairs,
                    add_special_tokens=False,
                    truncation=True,
                    max_length=content_max,
                )
                input_ids = [self._prefix_ids + ids + self._suffix_ids for ids in enc["input_ids"]]
                padded = self.tokenizer.pad(
                    {"input_ids": input_ids}, padding=True, return_tensors="pt"
                ).to(self.model.device)
                logits = self.model(**padded).logits[:, -1, :]
                pair_logits = torch.stack(
                    [logits[:, self._false_id], logits[:, self._true_id]], dim=1
                )
                probs = torch.softmax(pair_logits, dim=1)[:, 1]
                scores.extend(probs.float().cpu().tolist())
        return scores


_embedder: Embedder | None = None
_reranker: Reranker | None = None
_embedder_lock = threading.Lock()
_reranker_lock = threading.Lock()


def get_embedder() -> Embedder:
    """Singleton embedder (chargé au démarrage via le lifespan FastAPI)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                _embedder = Embedder()
    return _embedder


def get_reranker() -> Reranker:
    """Singleton reranker — chargé paresseusement au premier appel `/rerank`."""
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = Reranker()
    return _reranker
