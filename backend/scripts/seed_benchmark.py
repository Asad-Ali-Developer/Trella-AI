"""Synthetic benchmark dataset generator and fast batched chunk/embedding seeder."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import random
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.auth.models import User
from app.modules.connections.models import ProviderAccount, WorkspaceConnection
from app.modules.context.chunker import (
    CHUNKER_VERSION,
    CardBodyInput,
    Chunk,
    CommentInput,
    CommitInput,
    chunk_card_body,
    chunk_comments,
    chunk_commits,
    compute_content_hash,
)
from app.modules.context.models import EMBEDDING_DIMENSIONS, ContextChunkRecord
from app.modules.github.models import GithubCommit, GithubRepository
from app.modules.trello.models import (
    TrelloCard,
    TrelloClientRecord,
    TrelloComment,
    TrelloMember,
    TrelloSource,
)
from app.modules.workspaces.models import Membership, MembershipRole, Workspace
from scripts.bench_db import (
    assert_bench_database_isolated,
    create_bench_engine,
    create_bench_session_maker,
    prepare_bench_database,
)

FAKE_EMBEDDING_MODEL = "fake-bench-768"
BENCH_WORKSPACE_PREFIX = "BENCH-"
BENCH_USER_EMAIL_PREFIX = "bench-owner-"
BATCH_INSERT_SIZE = 1000

TOPICS: tuple[str, ...] = (
    "payments",
    "onboarding",
    "reporting",
    "auth",
    "mobile_app",
    "notifications",
    "integrations",
    "analytics",
    "security",
    "billing",
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "payments": (
        "payments",
        "payment",
        "stripe",
        "paddle",
        "checkout",
        "settlement",
        "refund",
        "payout",
        "chargeback",
        "gateway",
        "ach",
        "sepa",
    ),
    "onboarding": (
        "onboarding",
        "onboard",
        "signup",
        "welcome",
        "wizard",
        "activation",
        "kyc",
        "provisioning",
        "walkthrough",
        "checklist",
    ),
    "reporting": (
        "reporting",
        "report",
        "export",
        "csv",
        "pdf",
        "digest",
        "scheduled",
        "executive",
        "summary",
        "ledger",
    ),
    "auth": (
        "auth",
        "authentication",
        "sso",
        "saml",
        "oauth",
        "pkce",
        "mfa",
        "totp",
        "jwt",
        "session",
        "passkey",
    ),
    "mobile_app": (
        "mobile_app",
        "mobile",
        "ios",
        "android",
        "react-native",
        "swift",
        "kotlin",
        "biometric",
        "offline",
        "push",
    ),
    "notifications": (
        "notifications",
        "notification",
        "webhook",
        "alert",
        "slack",
        "email",
        "unsubscribe",
        "bounce",
        "throttle",
        "digest-delivery",
    ),
    "integrations": (
        "integrations",
        "integration",
        "trello",
        "github",
        "jira",
        "salesforce",
        "hubspot",
        "connector",
        "sync",
        "cursor",
    ),
    "analytics": (
        "analytics",
        "funnel",
        "cohort",
        "retention",
        "attribution",
        "telemetry",
        "warehouse",
        "bigquery",
        "clickhouse",
        "metrics",
    ),
    "security": (
        "security",
        "encryption",
        "fernet",
        "aes",
        "kms",
        "audit",
        "pentest",
        "vulnerability",
        "rbac",
        "isolation",
    ),
    "billing": (
        "billing",
        "subscription",
        "invoice",
        "proration",
        "metering",
        "quota",
        "overage",
        "dunning",
        "tier",
        "plan-limit",
    ),
}

TOPIC_SENTENCES: dict[str, tuple[str, ...]] = {
    "payments": (
        "Client payment settlement gateway encountered intermittent webhook timeouts on high-volume checkout flows.",
        "Reconcile ACH and SEPA payout batches with automated refund and chargeback ledger entries.",
        "Ensure idempotency keys are persisted before dispatching payment capture requests to the gateway.",
        "Add multi-currency settlement reporting for cross-border merchant checkout transactions.",
    ),
    "onboarding": (
        "New enterprise customer onboarding wizard stalls during workspace provisioning and KYC verification.",
        "Streamline signup activation checklist so trial teams connect their first board within five minutes.",
        "Pre-populate guided walkthrough templates and role invitations during initial tenant onboarding.",
        "Track onboarding funnel drop-off between organization creation and first data source sync.",
    ),
    "reporting": (
        "Weekly executive reporting digest needs CSV and PDF export with timezone-aware delivery windows.",
        "Include stakeholder risk matrix and milestone velocity charts in the automated client report.",
        "Optimize large ledger summary queries so scheduled reporting runs complete under thirty seconds.",
        "Allow custom fiscal calendar filtering when generating quarterly client performance reports.",
    ),
    "auth": (
        "Enterprise SAML SSO and OAuth PKCE authentication flow requires strict session rotation and MFA.",
        "Enforce TOTP and WebAuthn passkey verification for administrative workspace operations.",
        "Fix refresh token race condition when concurrent browser tabs rotate HttpOnly auth cookies.",
        "Validate audience and issuer claims on inbound OIDC identity tokens during federated login.",
    ),
    "mobile_app": (
        "iOS and Android mobile app offline queue drops delta sync mutations when network connectivity flaps.",
        "Reduce cold-start bundle latency on React Native client overview screens with virtualized lists.",
        "Support FaceID and biometric unlock for cached mobile workspace sessions.",
        "Fix push notification deep-linking into specific client cards on Android 14 devices.",
    ),
    "notifications": (
        "Slack Block Kit and email alert notifications must honor workspace quiet hours and List-Unsubscribe headers.",
        "Throttle bursty webhook notification dispatches using per-channel token bucket rate limits.",
        "Handle SMTP bounce callbacks and mark invalid recipient addresses inactive automatically.",
        "Support customizable notification routing rules by client priority and insight severity.",
    ),
    "integrations": (
        "Trello, GitHub, and Jira connector integrations need incremental cursor sync and HMAC webhook verification.",
        "Map external board lists and repository commits to unified workspace client records.",
        "Recover gracefully from upstream 429 rate-limit responses using exponential backoff with jitter.",
        "Deduplicate concurrent webhook bursts with distributed Redis locks per source connector.",
    ),
    "analytics": (
        "Cohort retention and funnel attribution analytics pipeline aggregates daily telemetry into ClickHouse.",
        "Expose p50 and p95 feature adoption metrics segmented by customer tier and workspace size.",
        "Backfill historical event streams into the analytics warehouse without blocking live ingestion.",
        "Add anomaly detection on weekly active client engagement scores across connected boards.",
    ),
    "security": (
        "Rotate Fernet encryption keys for stored provider credentials and verify tenant RBAC isolation.",
        "Record immutable audit log entries for every credential connect, disconnect, export, and deletion.",
        "Sanitize untrusted card and comment text before prompt assembly to mitigate injection vectors.",
        "Enforce strict Content-Security-Policy and origins check on all state-changing API endpoints.",
    ),
    "billing": (
        "Subscription billing metering tracks monthly skill runs, active boards, and seat overage quotas.",
        "Handle mid-cycle plan upgrades with accurate proration and automated invoice generation.",
        "Trigger dunning workflow emails when recurring subscription renewal charges fail.",
        "Enforce hard workspace tier limits before enqueueing expensive background AI runs.",
    ),
}

_TOKEN_RE = re.compile(r"[a-z0-9_-]+")


def detect_topics(text: str) -> list[str]:
    """Deterministically detect matching benchmark topics from text."""
    lowered = text.lower()
    tokens = set(_TOKEN_RE.findall(lowered))
    scores: list[tuple[int, str]] = []
    for topic in TOPICS:
        keywords = TOPIC_KEYWORDS[topic]
        hits = sum(1 for kw in keywords if kw in tokens or kw in lowered)
        if f"topic:{topic}" in lowered or f"[{topic}]" in lowered:
            hits += 5
        if hits > 0:
            scores.append((hits, topic))
    scores.sort(key=lambda item: (-item[0], TOPICS.index(item[1])))
    return [topic for _, topic in scores]


class DeterministicFakeEmbedder:
    """Deterministic, hash-seeded 768-dim unit vector embedder with strong topic clustering.

    No API calls, no network access, zero cost.
    Chunks/queries sharing a topic receive a high-weight topic centroid plus deterministic
    hash-seeded perturbations, normalized to unit length.
    """

    def __init__(
        self,
        *,
        dimensions: int = EMBEDDING_DIMENSIONS,
        seed: int = 42,
        cluster_weight: float = 0.88,
        noise_weight: float = 0.12,
    ) -> None:
        self.dimensions = dimensions
        self.seed = seed
        self.cluster_weight = cluster_weight
        self.noise_weight = noise_weight
        self._centroids: dict[str, list[float]] = {
            topic: self._build_centroid(topic) for topic in TOPICS
        }

    def _build_centroid(self, topic: str) -> list[float]:
        digest = hashlib.sha256(f"bench-centroid:{self.seed}:{topic}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        raw = [rng.gauss(0.0, 1.0) for _ in range(self.dimensions)]
        # Boost a dedicated subspace per topic so distinct topics are near-orthogonal
        topic_idx = TOPICS.index(topic)
        block_size = self.dimensions // len(TOPICS)
        start = topic_idx * block_size
        end = start + block_size
        for i in range(start, min(end, self.dimensions)):
            raw[i] += 6.0 * (1.0 if i % 2 == 0 else -1.0)
        return _normalize(raw)

    def _hash_noise_vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(f"bench-noise:{self.seed}:{text}".encode()).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        raw = [rng.gauss(0.0, 1.0) for _ in range(self.dimensions)]
        return _normalize(raw)

    def embed(self, text: str, *, topic_override: str | None = None) -> list[float]:
        """Return a deterministic 768-dimensional unit vector for `text`."""
        matched_topics = [topic_override] if topic_override in self._centroids else detect_topics(text)
        noise = self._hash_noise_vector(text)

        if not matched_topics:
            return noise

        primary_topic = matched_topics[0]
        assert primary_topic is not None
        centroid = self._centroids[primary_topic]

        # If a secondary topic is present, blend 85% primary + 15% secondary centroid
        if len(matched_topics) > 1 and matched_topics[1] in self._centroids:
            sec = self._centroids[matched_topics[1]]
            blended_centroid = _normalize(
                [0.85 * c1 + 0.15 * c2 for c1, c2 in zip(centroid, sec, strict=True)]
            )
        else:
            blended_centroid = centroid

        combined = [
            self.cluster_weight * c + self.noise_weight * n
            for c, n in zip(blended_centroid, noise, strict=True)
        ]
        return _normalize(combined)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts deterministically."""
        return [self.embed(t) for t in texts]


def _normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 1e-12:
        out = [0.0] * len(vec)
        if out:
            out[0] = 1.0
        return out
    return [float(v / norm) for v in vec]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 1e-12 or norm_b <= 1e-12:
        return 0.0
    return float(dot / (norm_a * norm_b))


@dataclass(frozen=True)
class SeedSummary:
    """Summary counts from a benchmark seed run."""

    workspaces: int
    clients: int
    sources: int
    repositories: int
    cards: int
    comments: int
    commits: int
    chunks: int
    elapsed_seconds: float


def _deterministic_uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def _batched(items: Sequence[dict[str, Any]], batch_size: int = BATCH_INSERT_SIZE) -> list[Sequence[dict[str, Any]]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


async def reset_bench_data(session: AsyncSession) -> int:
    """Delete all benchmark workspaces (prefixed `BENCH-`) and bench owner users."""
    ws_ids = list(
        (
            await session.scalars(
                select(Workspace.id).where(Workspace.name.like(f"{BENCH_WORKSPACE_PREFIX}%"))
            )
        ).all()
    )
    deleted_workspaces = len(ws_ids)
    if ws_ids:
        await session.execute(delete(Workspace).where(Workspace.id.in_(ws_ids)))
    await session.execute(
        delete(User).where(User.email.like(f"{BENCH_USER_EMAIL_PREFIX}%@bench.local"))
    )
    await session.commit()
    return deleted_workspaces


def build_synthetic_dataset(
    *,
    target_chunks: int = 20000,
    num_workspaces: int = 3,
    clients_per_workspace: int = 10,
    seed: int = 42,
) -> dict[str, list[dict[str, Any]]]:
    """Generate deterministic rows for users, workspaces, clients, sources, cards, comments, repos, commits, and chunks.

    Uses the real chunker (`chunk_card_body`, `chunk_comments`, `chunk_commits`) and
    `DeterministicFakeEmbedder` (`embedding_model = "fake-bench-768"`).
    """
    if num_workspaces < 1:
        raise ValueError("num_workspaces must be >= 1")
    if clients_per_workspace < 1:
        raise ValueError("clients_per_workspace must be >= 1")
    if target_chunks < num_workspaces:
        raise ValueError("target_chunks must be >= num_workspaces")

    rng = random.Random(seed)
    embedder = DeterministicFakeEmbedder(seed=seed)
    base_time = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    users_rows: list[dict[str, Any]] = []
    workspaces_rows: list[dict[str, Any]] = []
    memberships_rows: list[dict[str, Any]] = []
    provider_accounts_rows: list[dict[str, Any]] = []
    connections_rows: list[dict[str, Any]] = []
    clients_rows: list[dict[str, Any]] = []
    sources_rows: list[dict[str, Any]] = []
    repos_rows: list[dict[str, Any]] = []
    members_rows: list[dict[str, Any]] = []
    cards_rows: list[dict[str, Any]] = []
    comments_rows: list[dict[str, Any]] = []
    commits_rows: list[dict[str, Any]] = []
    chunks_rows: list[dict[str, Any]] = []

    list_names = ("Backlog", "In Progress", "Client Review", "Blocked", "Done")

    # Allocate target chunks across workspaces
    base_ws_target = target_chunks // num_workspaces
    ws_Remainder = target_chunks % num_workspaces

    global_proj_counter = 100

    for ws_idx in range(num_workspaces):
        ws_target_chunks = base_ws_target + (1 if ws_idx < ws_Remainder else 0)
        ws_Produced_chunks = 0

        user_id = _deterministic_uuid(rng)
        ws_id = _deterministic_uuid(rng)
        now_ts = base_time + timedelta(hours=ws_idx)

        users_rows.append(
            {
                "id": user_id,
                "email": f"{BENCH_USER_EMAIL_PREFIX}{seed}-{ws_idx + 1}@bench.local",
                "name": f"Bench Owner {ws_idx + 1}",
                "hashed_password": "bench_not_a_real_password_hash",
                "is_active": True,
                "is_verified": True,
                "created_at": now_ts,
                "updated_at": now_ts,
            }
        )

        ws_name = f"{BENCH_WORKSPACE_PREFIX}WS-{seed}-{ws_idx + 1:02d}"
        ws_slug = f"bench-ws-{seed}-{ws_idx + 1:02d}"
        workspaces_rows.append(
            {
                "id": ws_id,
                "name": ws_name,
                "description": f"Synthetic benchmark workspace {ws_idx + 1} (seed={seed})",
                "client_name": None,
                "slug": ws_slug,
                "owner_id": user_id,
                "created_at": now_ts,
                "updated_at": now_ts,
            }
        )

        memberships_rows.append(
            {
                "id": _deterministic_uuid(rng),
                "workspace_id": ws_id,
                "user_id": user_id,
                "role": MembershipRole.OWNER,
                "created_at": now_ts,
                "updated_at": now_ts,
            }
        )

        trello_acct_id = _deterministic_uuid(rng)
        github_acct_id = _deterministic_uuid(rng)
        provider_accounts_rows.extend(
            [
                {
                    "id": trello_acct_id,
                    "user_id": user_id,
                    "provider": "trello",
                    "encrypted_token": "bench-encrypted-trello-token",
                    "status": "active",
                    "external_account_id": f"bench-trello-acct-{ws_idx + 1}",
                    "external_username": f"bench_trello_{ws_idx + 1}",
                    "created_at": now_ts,
                    "updated_at": now_ts,
                },
                {
                    "id": github_acct_id,
                    "user_id": user_id,
                    "provider": "github",
                    "encrypted_token": "bench-encrypted-github-token",
                    "status": "active",
                    "external_account_id": f"bench-github-acct-{ws_idx + 1}",
                    "external_username": f"bench_github_{ws_idx + 1}",
                    "created_at": now_ts,
                    "updated_at": now_ts,
                },
            ]
        )

        trello_conn_id = _deterministic_uuid(rng)
        github_conn_id = _deterministic_uuid(rng)
        connections_rows.extend(
            [
                {
                    "id": trello_conn_id,
                    "workspace_id": ws_id,
                    "user_id": user_id,
                    "provider": "trello",
                    "status": "active",
                    "provider_account_id": trello_acct_id,
                    "created_at": now_ts,
                    "updated_at": now_ts,
                },
                {
                    "id": github_conn_id,
                    "workspace_id": ws_id,
                    "user_id": user_id,
                    "provider": "github",
                    "status": "active",
                    "provider_account_id": github_acct_id,
                    "created_at": now_ts,
                    "updated_at": now_ts,
                },
            ]
        )

        ws_clients: list[tuple[uuid.UUID, str]] = []
        for c_idx in range(clients_per_workspace):
            c_id = _deterministic_uuid(rng)
            c_name = f"Bench Client {ws_idx + 1:02d}-{c_idx + 1:02d}"
            ws_clients.append((c_id, c_name))
            clients_rows.append(
                {
                    "id": c_id,
                    "workspace_id": ws_id,
                    "name": c_name,
                    "created_at": now_ts,
                    "updated_at": now_ts,
                }
            )

        # Create 3 Trello sources (2 active, 1 excluded to test active-source filtering if needed,
        # while all benchmark chunks belong to active sources)
        ws_sources: list[tuple[uuid.UUID, str]] = []
        for s_idx in range(2):
            s_id = _deterministic_uuid(rng)
            s_name = f"BENCH Board {ws_idx + 1:02d}-{s_idx + 1}"
            ws_sources.append((s_id, s_name))
            sources_rows.append(
                {
                    "id": s_id,
                    "workspace_id": ws_id,
                    "connection_id": trello_conn_id,
                    "trello_board_id": f"bench-board-{seed}-{ws_idx + 1}-{s_idx + 1}",
                    "name": s_name,
                    "url": f"https://trello.com/b/bench{ws_idx + 1}{s_idx + 1}",
                    "excluded": False,
                    "sync_status": "completed",
                    "last_synced_at": now_ts,
                    "sync_error": None,
                    "webhook_id": None,
                    "created_at": now_ts,
                    "updated_at": now_ts,
                }
            )

        # Workspace members
        ws_member_names = (
            ("ext-mem-1", "alice_pm", "Alice Morgan", "internal"),
            ("ext-mem-2", "bob_eng", "Bob Chen", "internal"),
            ("ext-mem-3", "carol_client", "Carol Davis", "client"),
            ("ext-mem-4", "dan_qa", "Dan Ibrahim", "internal"),
        )
        for ext_id, uname, fname, role_tag in ws_member_names:
            members_rows.append(
                {
                    "id": _deterministic_uuid(rng),
                    "workspace_id": ws_id,
                    "trello_member_id": f"{ext_id}-{ws_idx + 1}",
                    "username": f"{uname}_{ws_idx + 1}",
                    "full_name": fname,
                    "role_tag": role_tag,
                    "created_at": now_ts,
                    "updated_at": now_ts,
                }
            )

        # Create 1 active GitHub repository and commits (~5% of workspace chunks, capped at 30 commits)
        repo_id = _deterministic_uuid(rng)
        repo_client_id, repo_client_name = ws_clients[0]
        repo_full_name = f"bench-org-{ws_idx + 1}/platform-core"
        repos_rows.append(
            {
                "id": repo_id,
                "workspace_id": ws_id,
                "connection_id": github_conn_id,
                "github_repo_id": f"bench-repo-{seed}-{ws_idx + 1}",
                "full_name": repo_full_name,
                "description": "Synthetic benchmark repository",
                "url": f"https://github.com/{repo_full_name}",
                "default_branch": "main",
                "private": True,
                "included": True,
                "client_id": repo_client_id,
                "sync_status": "completed",
                "last_synced_at": now_ts,
                "sync_error": None,
                "created_at": now_ts,
                "updated_at": now_ts,
            }
        )

        max_commit_groups = max(1, min(15, ws_target_chunks // 25))
        commit_inputs: list[CommitInput] = []
        if ws_target_chunks > 4:
            for day_idx in range(max_commit_groups):
                topic = TOPICS[day_idx % len(TOPICS)]
                commit_dt = base_time + timedelta(days=day_idx * 2, hours=14)
                for c_sub in range(2):
                    commit_id = _deterministic_uuid(rng)
                    sha_hex = hashlib.sha1(
                        f"bench-sha:{seed}:{ws_idx}:{day_idx}:{c_sub}".encode()
                    ).hexdigest()
                    proj_ref = f"PROJ-{100 + day_idx}"
                    sentence = TOPIC_SENTENCES[topic][c_sub % len(TOPIC_SENTENCES[topic])]
                    msg = f"fix({topic}): { proj_ref } {sentence}"
                    commits_rows.append(
                        {
                            "id": commit_id,
                            "workspace_id": ws_id,
                            "repository_id": repo_id,
                            "sha": sha_hex,
                            "message": msg,
                            "author_name": "Bob Chen",
                            "author_login": f"bob_eng_{ws_idx + 1}",
                            "committed_at": commit_dt + timedelta(minutes=c_sub * 15),
                            "url": f"https://github.com/{repo_full_name}/commit/{sha_hex}",
                            "additions": 25 + c_sub * 10,
                            "deletions": 5 + c_sub * 2,
                            "changed_files": 3,
                            "created_at": now_ts,
                            "updated_at": now_ts,
                        }
                    )
                    commit_inputs.append(
                        CommitInput(
                            commit_id=str(commit_id),
                            sha=sha_hex,
                            author_name="Bob Chen",
                            committed_at=commit_dt + timedelta(minutes=c_sub * 15),
                            message=msg,
                        )
                    )

        commit_chunks = chunk_commits(
            commit_inputs,
            client_name=repo_client_name,
            repo_name=repo_full_name,
        )
        for ch in commit_chunks:
            if ws_Produced_chunks >= ws_target_chunks - 1:
                break
            chunks_rows.append(
                _chunk_to_row(
                    rng=rng,
                    embedder=embedder,
                    workspace_id=ws_id,
                    client_id=repo_client_id,
                    source_id=None,
                    repository_id=repo_id,
                    source_type="github",
                    card_id=None,
                    chunk=ch,
                    created_at=now_ts,
                )
            )
            ws_Produced_chunks += 1

        # Generate Trello cards + comments until ws_Produced_chunks == ws_target_chunks
        card_idx = 0
        while ws_Produced_chunks < ws_target_chunks:
            remaining = ws_target_chunks - ws_Produced_chunks
            card_id = _deterministic_uuid(rng)
            source_id, source_name = ws_sources[card_idx % len(ws_sources)]
            client_id, client_name = ws_clients[card_idx % len(ws_clients)]
            topic = TOPICS[card_idx % len(TOPICS)]
            keywords = TOPIC_KEYWORDS[topic]
            sentences = TOPIC_SENTENCES[topic]
            list_name = list_names[card_idx % len(list_names)]

            global_proj_counter += 1
            proj_code = f"PROJ-{global_proj_counter}"
            commit_sha_ref = hashlib.sha1(
                f"card-sha:{seed}:{ws_idx}:{card_idx}".encode()
            ).hexdigest()[:10]

            # Spread occurred_at across 90 days (2026-01-01 to 2026-03-31)
            day_offset = (card_idx * 3) % 90
            occurred_at = base_time + timedelta(days=day_offset, hours=card_idx % 12)

            # Decide card size profile based on remaining budget and mix
            # Profile 0: tiny card (title only, 1 chunk)
            # Profile 1: normal card (1 body chunk + 1 comment group chunk = 2 chunks)
            # Profile 2: long card (2 body chunks + 1 comment group chunk = 3 chunks)
            if remaining == 1 or card_idx % 5 == 0:
                profile = "tiny"
            elif remaining >= 3 and card_idx % 4 == 1:
                profile = "long"
            else:
                profile = "medium"

            kw_pair = f"{keywords[0]} {keywords[1]} {keywords[2]}"
            card_title = (
                f"[{proj_code}] {topic.replace('_', ' ').title()}: "
                f"{sentences[0][:68]} ({kw_pair})"
            )

            if profile == "tiny":
                description = ""
                num_comments = 0
            elif profile == "medium":
                description = (
                    f"Identifier: {proj_code} | Commit: {commit_sha_ref} | Topic: {topic}\n"
                    f"{sentences[0]} {sentences[1]}\n"
                    f"Key terms: {', '.join(keywords[:6])}."
                )
                num_comments = 3 if remaining >= 2 else 0
            else:
                # Long description > 400 tokens (~1800+ chars) so chunk_card_body splits into 2 chunks
                para = (
                    f"Reference {proj_code} (commit {commit_sha_ref}) for {topic}: "
                    + " ".join(sentences)
                    + " Keywords: "
                    + ", ".join(keywords)
                    + "."
                )
                description = "\n\n".join(f"Section {idx + 1}: {para}" for idx in range(7))
                num_comments = 4 if remaining >= 3 else 0

            labels_json = [{"name": topic, "color": "blue"}]
            card_url = f"https://trello.com/c/{card_id.hex[:8]}"
            card_content_hash = compute_content_hash(f"{card_title}\n{description}")

            cards_rows.append(
                {
                    "id": card_id,
                    "workspace_id": ws_id,
                    "source_id": source_id,
                    "client_id": client_id,
                    "trello_card_id": f"bench-card-{seed}-{ws_idx + 1}-{card_idx + 1}",
                    "name": card_title,
                    "description": description,
                    "list_id": f"list-{card_idx % len(list_names)}",
                    "list_name": list_name,
                    "labels": labels_json,
                    "member_ids": [f"ext-mem-1-{ws_idx + 1}"],
                    "due_at": occurred_at + timedelta(days=7),
                    "last_activity_at": occurred_at,
                    "closed": False,
                    "url": card_url,
                    "content_hash": card_content_hash,
                    "created_at": now_ts,
                    "updated_at": now_ts,
                }
            )

            body_input = CardBodyInput(
                client_name=client_name,
                board_name=source_name,
                list_name=list_name,
                card_title=card_title,
                description=description,
                labels=[topic],
                checklists=(),
                occurred_at=occurred_at,
                metadata={
                    "card_id": str(card_id),
                    "trello_card_id": f"bench-card-{seed}-{ws_idx + 1}-{card_idx + 1}",
                    "proj_code": proj_code,
                    "commit_sha_ref": commit_sha_ref,
                    "topic": topic,
                    "list_name": list_name,
                    "closed": False,
                    "url": card_url,
                },
            )
            body_chunks = chunk_card_body(body_input)
            if len(body_chunks) > remaining:
                body_chunks = body_chunks[:remaining]

            for ch in body_chunks:
                chunks_rows.append(
                    _chunk_to_row(
                        rng=rng,
                        embedder=embedder,
                        workspace_id=ws_id,
                        client_id=client_id,
                        source_id=source_id,
                        repository_id=None,
                        source_type="trello",
                        card_id=card_id,
                        chunk=ch,
                        created_at=now_ts,
                        topic_override=topic,
                    )
                )
                ws_Produced_chunks += 1

            remaining_after_body = ws_target_chunks - ws_Produced_chunks
            if num_comments > 0 and remaining_after_body > 0:
                comment_inputs: list[CommentInput] = []
                for cm_idx in range(num_comments):
                    cm_id = _deterministic_uuid(rng)
                    cm_dt = occurred_at + timedelta(minutes=(cm_idx + 1) * 10)
                    cm_sentence = sentences[(cm_idx + 1) % len(sentences)]
                    cm_text = (
                        f"[{proj_code}] Follow-up on {topic} ({keywords[cm_idx % len(keywords)]}): "
                        f"{cm_sentence} Verified commit {commit_sha_ref}."
                    )
                    comments_rows.append(
                        {
                            "id": cm_id,
                            "workspace_id": ws_id,
                            "card_id": card_id,
                            "trello_action_id": f"bench-act-{seed}-{ws_idx + 1}-{card_idx + 1}-{cm_idx + 1}",
                            "author_id": f"ext-mem-{(cm_idx % 3) + 1}-{ws_idx + 1}",
                            "text": cm_text,
                            "created_at_trello": cm_dt,
                            "created_at": now_ts,
                            "updated_at": now_ts,
                        }
                    )
                    comment_inputs.append(
                        CommentInput(
                            comment_id=str(cm_id),
                            author_name="Alice Morgan" if cm_idx % 2 == 0 else "Carol Davis",
                            created_at=cm_dt,
                            text=cm_text,
                        )
                    )

                comment_chunks = chunk_comments(
                    comment_inputs,
                    client_name=client_name,
                    board_name=source_name,
                    list_name=list_name,
                    card_title=card_title,
                )
                for ch in comment_chunks[:remaining_after_body]:
                    # Merge topic/proj_code metadata for inspection
                    enriched_meta = dict(ch.metadata)
                    enriched_meta["topic"] = topic
                    enriched_meta["proj_code"] = proj_code
                    enriched_chunk = Chunk(
                        kind=ch.kind,
                        ordinal=ch.ordinal,
                        text=ch.text,
                        token_estimate=ch.token_estimate,
                        occurred_at=ch.occurred_at,
                        metadata=enriched_meta,
                        content_hash=ch.content_hash,
                        group_key=ch.group_key,
                    )
                    chunks_rows.append(
                        _chunk_to_row(
                            rng=rng,
                            embedder=embedder,
                            workspace_id=ws_id,
                            client_id=client_id,
                            source_id=source_id,
                            repository_id=None,
                            source_type="trello",
                            card_id=card_id,
                            chunk=enriched_chunk,
                            created_at=now_ts,
                            topic_override=topic,
                        )
                    )
                    ws_Produced_chunks += 1

            card_idx += 1

    return {
        "users": users_rows,
        "workspaces": workspaces_rows,
        "memberships": memberships_rows,
        "provider_accounts": provider_accounts_rows,
        "connections": connections_rows,
        "clients": clients_rows,
        "sources": sources_rows,
        "github_repositories": repos_rows,
        "members": members_rows,
        "cards": cards_rows,
        "comments": comments_rows,
        "github_commits": commits_rows,
        "chunks": chunks_rows,
    }


def _chunk_to_row(
    *,
    rng: random.Random,
    embedder: DeterministicFakeEmbedder,
    workspace_id: uuid.UUID,
    client_id: uuid.UUID | None,
    source_id: uuid.UUID | None,
    repository_id: uuid.UUID | None,
    source_type: str,
    card_id: uuid.UUID | None,
    chunk: Chunk,
    created_at: datetime,
    topic_override: str | None = None,
) -> dict[str, Any]:
    vector = embedder.embed(chunk.text, topic_override=topic_override)
    return {
        "id": _deterministic_uuid(rng),
        "workspace_id": workspace_id,
        "client_id": client_id,
        "source_id": source_id,
        "repository_id": repository_id,
        "source_type": source_type,
        "card_id": card_id,
        "group_key": chunk.group_key,
        "chunk_kind": chunk.kind,
        "ordinal": chunk.ordinal,
        "text": chunk.text,
        "token_estimate": chunk.token_estimate,
        "embedding": vector,
        "embedding_model": FAKE_EMBEDDING_MODEL,
        "chunker_version": CHUNKER_VERSION,
        "content_hash": chunk.content_hash,
        "occurred_at": chunk.occurred_at,
        "chunk_metadata": chunk.metadata,
        "created_at": created_at,
        "updated_at": created_at,
    }


async def insert_synthetic_dataset(
    session: AsyncSession,
    dataset: dict[str, list[dict[str, Any]]],
    *,
    batch_size: int = BATCH_INSERT_SIZE,
) -> None:
    """Insert all dataset tables using batched multi-row inserts (`insert(Model)`, never 1-by-1)."""
    table_Execution_order: list[tuple[Any, str]] = [
        (User, "users"),
        (Workspace, "workspaces"),
        (Membership, "memberships"),
        (ProviderAccount, "provider_accounts"),
        (WorkspaceConnection, "connections"),
        (TrelloClientRecord, "clients"),
        (TrelloSource, "sources"),
        (GithubRepository, "github_repositories"),
        (TrelloMember, "members"),
        (TrelloCard, "cards"),
        (TrelloComment, "comments"),
        (GithubCommit, "github_commits"),
        (ContextChunkRecord, "chunks"),
    ]

    for model_cls, key in table_Execution_order:
        rows = dataset.get(key, [])
        if not rows:
            continue
        for batch in _batched(rows, batch_size=batch_size):
            await session.execute(insert(model_cls), batch)
    await session.commit()


async def run_seed_benchmark(
    *,
    target_chunks: int = 20000,
    num_workspaces: int = 3,
    clients_per_workspace: int = 10,
    seed: int = 42,
    reset: bool = False,
    bench_url: str | None = None,
    engine: AsyncEngine | None = None,
    prepare_db: bool = True,
) -> SeedSummary:
    """Prepare the benchmark DB, optionally reset BENCH- data, and batch-seed synthetic rows."""
    t0 = time.perf_counter()
    isolated_url = assert_bench_database_isolated(bench_url=bench_url)
    if prepare_db and engine is None:
        await prepare_bench_database(bench_url=isolated_url)

    owns_engine = engine is None
    active_engine = engine if engine is not None else create_bench_engine(isolated_url)
    session_maker = create_bench_session_maker(active_engine)

    try:
        async with session_maker() as session:
            # Always clean up any prior BENCH- workspaces on --reset or matching slug collision
            if reset:
                await reset_bench_data(session)
            else:
                await reset_bench_data(session)

            dataset = build_synthetic_dataset(
                target_chunks=target_chunks,
                num_workspaces=num_workspaces,
                clients_per_workspace=clients_per_workspace,
                seed=seed,
            )
            await insert_synthetic_dataset(session, dataset)
    finally:
        if owns_engine:
            await active_engine.dispose()

    elapsed = time.perf_counter() - t0
    return SeedSummary(
        workspaces=len(dataset["workspaces"]),
        clients=len(dataset["clients"]),
        sources=len(dataset["sources"]),
        repositories=len(dataset["github_repositories"]),
        cards=len(dataset["cards"]),
        comments=len(dataset["comments"]),
        commits=len(dataset["github_commits"]),
        chunks=len(dataset["chunks"]),
        elapsed_seconds=elapsed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed synthetic workspaces, clients, Trello cards/comments, GitHub commits, and chunks into client_insights_bench."
    )
    parser.add_argument("--chunks", type=int, default=20000, help="Total chunks to generate (default: 20000)")
    parser.add_argument("--workspaces", type=int, default=3, help="Number of workspaces (default: 3)")
    parser.add_argument("--clients", type=int, default=10, help="Clients per workspace (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic RNG seed (default: 42)")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove existing BENCH- workspaces before seeding (or use --chunks 0 --reset to only clean up).",
    )
    parser.add_argument("--db-url", default=None, help="Optional BENCH_DATABASE_URL override.")
    args = parser.parse_args()

    async def _run() -> None:
        isolated_url = assert_bench_database_isolated(bench_url=args.db_url)
        await prepare_bench_database(bench_url=isolated_url)
        if args.chunks == 0 and args.reset:
            eng = create_bench_engine(isolated_url)
            try:
                sm = create_bench_session_maker(eng)
                async with sm() as session:
                    removed = await reset_bench_data(session)
                    print(f"Reset complete: removed {removed} BENCH- workspace(s).")
            finally:
                await eng.dispose()
            return

        summary = await run_seed_benchmark(
            target_chunks=args.chunks,
            num_workspaces=args.workspaces,
            clients_per_workspace=args.clients,
            seed=args.seed,
            reset=args.reset,
            bench_url=isolated_url,
            prepare_db=False,
        )
        print(
            f"Seeded {summary.chunks} chunks across {summary.workspaces} workspaces "
            f"({summary.clients} clients, {summary.cards} cards, {summary.comments} comments, "
            f"{summary.commits} commits) in {summary.elapsed_seconds:.2f}s "
            f"[model={FAKE_EMBEDDING_MODEL}]."
        )

    asyncio.run(_run())


if __name__ == "__main__":
    main()

