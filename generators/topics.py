"""Per-category seed topic banks + rotation/dedup.

Topics intentionally lean evergreen ("How X works", "Practical guide to Y")
rather than time-sensitive ("This week's news") so backfilled posts dated
2024-2026 don't make claims about events the LLM may hallucinate.

Public API:
    rotate_category(date_iso, categories=DEFAULT_ROTATION) -> str
        Deterministic round-robin: same date -> same category.

    pick_topic(category, *, existing_titles, seed=None) -> str
        Returns a topic seed phrase that hasn't been used (Jaccard < 0.5).

    is_duplicate(title, existing_titles, threshold=0.6) -> bool
"""
from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime


# Categories used in the rotation. `blog` is implicit on every post (the
# WP convention preserved in build.py); these are the *topical* categories.
DEFAULT_ROTATION = [
    "artificial-intelligence-ai",
    "technology",
    "machine-learning-ml",
    "security",
    "data-science",
    "cloud-computing",
    "management",
    "internet-of-things-iot",
    "blockchain",
    "drone",
    "robotics",
    "quantum-computing",
    "virtual-reality-vr",
]

# Seed topic banks. ~20 per category. Evergreen-leaning.
TOPIC_BANKS: dict[str, list[str]] = {
    "artificial-intelligence-ai": [
        "How transformer attention actually works, explained for engineers",
        "Practical prompt engineering patterns that survive model upgrades",
        "Retrieval-augmented generation: when it helps and when it hurts",
        "Evaluating LLM applications without falling for vibes-based testing",
        "The hidden cost of fine-tuning vs. prompting for production",
        "Open-source vs. proprietary LLMs: a decision framework",
        "Designing AI features that fail gracefully",
        "Why context windows are not the bottleneck you think",
        "AI agents in production: the orchestration patterns that work",
        "Small language models are quietly winning the enterprise",
        "Token economics: making LLM features sustainable",
        "Multi-modal AI: practical use cases beyond the demos",
        "The architecture of a modern RAG pipeline, end-to-end",
        "Guardrails for AI products: input filters, output validators, audit logs",
        "Synthetic data generation: an underrated production tool",
        "How embeddings encode meaning, and where the abstraction leaks",
        "Building a domain-specific evaluation harness for LLMs",
        "On-device AI: what runs locally in 2026 and what doesn't",
        "Hybrid search: lexical + vector retrieval done right",
        "AI red-teaming: structured adversarial testing for LLM apps",
    ],
    "technology": [
        "The quiet rise of WebAssembly outside the browser",
        "What developer experience actually means in 2026",
        "Edge computing patterns for low-latency apps",
        "Composable architecture: the next phase after microservices",
        "Why static-site generators are eating dynamic CMS",
        "Headless commerce: the architectural shift in retail tech",
        "Browser APIs that quietly changed the web platform",
        "The case for boring technology in startup stacks",
        "Local-first software: principles and current tooling",
        "Real-time collaboration: the architecture behind multiplayer apps",
        "Why HTTP/3 matters more than you think",
        "Service mesh fatigue: simpler alternatives that work",
        "Infrastructure-as-code patterns that scale to large teams",
        "Observability beyond logs, metrics, and traces",
        "Postgres as a platform: features that replace whole categories of tools",
        "The new generation of build tools: Vite, Turbopack, Bun explained",
        "Software supply chain security: practical hardening steps",
        "API design lessons from a decade of REST and GraphQL",
        "Why event-driven systems quietly dominate modern backends",
        "Container orchestration without Kubernetes: when it's a fit",
    ],
    "machine-learning-ml": [
        "Feature engineering in the age of foundation models",
        "MLOps without the buzzwords: the minimum viable platform",
        "Drift detection: methods that actually catch real-world drift",
        "Choosing the right loss function for imbalanced classification",
        "Active learning: getting more from each labeling dollar",
        "Bias and fairness audits in ML pipelines",
        "Time-series forecasting: when statistical models still beat deep learning",
        "Recommender systems beyond collaborative filtering",
        "The lifecycle of a production ML model, end-to-end",
        "Why feature stores became indispensable, and when they're overkill",
        "Cross-validation strategies that don't leak",
        "Hyperparameter tuning: budgets, Bayesian methods, and asymptotic returns",
        "Causal inference for ML practitioners: a working introduction",
        "Embedding model selection for retrieval tasks",
        "Anomaly detection in unlabeled telemetry streams",
        "Gradient boosting is still winning Kaggle. Here's why",
        "Building a personal ML reproducibility checklist",
        "Distillation in practice: shipping smaller, faster models",
        "Calibration: why your model's probabilities probably lie",
        "ML system design interviews, decoded",
    ],
    "security": [
        "Threat modeling for small engineering teams",
        "Zero-trust architecture beyond the marketing slides",
        "Secrets management: rotating keys without breaking production",
        "Supply chain attacks: the realistic defenses",
        "Phishing-resistant MFA: what's actually available in 2026",
        "Container security: a layered approach",
        "Cloud IAM hardening: the high-leverage policies",
        "Incident response runbooks every startup needs",
        "Securing CI/CD pipelines against malicious dependencies",
        "Network segmentation patterns for hybrid cloud",
        "Web app security: the OWASP top 10 in plain English",
        "Mobile app security: certificate pinning and beyond",
        "Detection engineering: writing better alerts",
        "Bug bounty programs: how to run one well",
        "Encryption at rest, in transit, and in use: a practical guide",
        "API security: rate limits, auth, and abuse prevention",
        "Securing remote workforce endpoints without locking them down",
        "Tabletop exercises: turning postmortems into preparedness",
        "The state of post-quantum cryptography migration",
        "AI in cybersecurity: separating capability from theater",
    ],
    "data-science": [
        "Storytelling with data: principles from journalism for analysts",
        "SQL patterns that distinguish senior data analysts",
        "Notebook discipline: when to graduate to scripts and tests",
        "Designing dashboards people actually use",
        "Cohort analysis: the methodology and the pitfalls",
        "Experimentation platforms: build vs. buy in 2026",
        "Statistical significance for product teams, without the jargon",
        "A working introduction to Bayesian A/B testing",
        "Data quality monitoring: the underrated reliability problem",
        "Modern data stack: components, costs, and trade-offs",
        "Reverse ETL: closing the loop from warehouse to operations",
        "Customer segmentation: from RFM to embedding-based clusters",
        "Funnel analytics: instrumentation patterns that scale",
        "Survival analysis for churn modeling",
        "The case for product analytics over event-warehouse sprawl",
        "Geospatial analytics: tools and techniques for non-experts",
        "Data contracts: bringing schema discipline to producers",
        "Sampling strategies for streaming analytics",
        "Why data lineage matters for trust",
        "Building a data team's first quarter from scratch",
    ],
    "cloud-computing": [
        "FinOps fundamentals: cutting cloud bills without slowing teams",
        "Multi-region architectures: what you give up and what you gain",
        "Serverless vs. containers: a 2026 decision framework",
        "Cold start economics: optimizing serverless for latency-sensitive workloads",
        "S3 anti-patterns that quietly inflate your bill",
        "Cloud-native databases: the trade-off matrix",
        "VPC design for SaaS startups",
        "Disaster recovery on a startup budget",
        "Right-sizing compute: the underused autoscaling levers",
        "Cross-cloud data egress: avoiding the worst surprises",
        "Infrastructure cost attribution: the tagging discipline",
        "Edge functions: when latency justifies the complexity",
        "Object storage as a primary database: emerging patterns",
        "Cloud security posture management without the platform sprawl",
        "Spot instances and preemptible workloads in production",
        "Logging at cloud scale without breaking the bank",
        "Kubernetes node pools: cost-aware scheduling patterns",
        "Hybrid cloud done well: the integration points that matter",
        "GitOps for infrastructure: workflows that don't paint you into a corner",
        "Cloud certifications: which ones still move the needle",
    ],
    "management": [
        "Async-first remote teams: the rituals that make it work",
        "Engineering manager career ladders, decoded",
        "Running 1:1s that actually develop people",
        "Performance reviews without the performance theater",
        "Hiring engineers: the interview loop redesign nobody talks about",
        "Onboarding plans that get engineers productive in 30 days",
        "The art of saying no in product roadmaps",
        "Cross-functional partnership: the EM-PM-design triangle",
        "Postmortems that change behavior, not paperwork",
        "Tech debt budgeting: a quarterly framework",
        "Scaling a team from 5 to 50: the inflection points",
        "Remote-first compensation: bands, geography, and fairness",
        "Building a culture of writing in engineering teams",
        "Delegating without abdicating: practical patterns",
        "Managing up: framing decisions for executives",
        "Founder mode vs. manager mode: when to switch",
        "Diversity in tech hiring: practices that move metrics",
        "Internal mobility programs that retain top talent",
        "The economics of office space in a hybrid era",
        "Coaching ICs into staff engineers",
    ],
    "internet-of-things-iot": [
        "Edge computing for IoT: where to run inference",
        "MQTT at scale: broker architecture patterns",
        "Securing IoT fleets: provisioning, rotation, attestation",
        "Industrial IoT in Pakistan: an emerging opportunity",
        "Sensor data pipelines: from ingest to insight",
        "LoRaWAN vs. cellular IoT: the trade-off matrix",
        "OTA updates for embedded fleets, done safely",
        "Digital twins: practical use cases beyond the hype",
        "Time-series databases for IoT workloads",
        "Predictive maintenance: from sensor stream to ROI",
        "Smart agriculture: IoT applications in South Asia",
        "Building energy management with IoT sensors",
        "Wearable health devices: the data architecture",
        "IoT in retail: from inventory to in-store analytics",
        "Edge AI on microcontrollers: what's possible today",
        "Provisioning IoT devices without manual touch",
        "IoT data privacy: regulatory landscape in 2026",
        "Mesh networking for resilient IoT deployments",
        "IoT for water management in growing cities",
        "Choosing an IoT platform: build, buy, or open source",
    ],
    "blockchain": [
        "Stablecoins for cross-border payments in emerging markets",
        "Layer-2 scaling: the 2026 landscape",
        "Zero-knowledge proofs: applications beyond privacy",
        "On-chain identity: the patterns that are working",
        "Smart contract auditing: a practitioner's checklist",
        "Tokenized real-world assets: regulatory and technical realities",
        "Decentralized storage: IPFS, Arweave, and Filecoin compared",
        "Account abstraction: what it changes for end users",
        "Building a wallet UX that doesn't scare normal users",
        "Crypto in remittances: the Pakistan corridor opportunity",
        "DAOs as governance experiments: what worked, what didn't",
        "Oracles: the trust layer that breaks DeFi",
        "Privacy coins in 2026: technical and regulatory snapshot",
        "NFT utility beyond JPEGs: tickets, credentials, memberships",
        "Cross-chain bridges: the security postmortem",
        "Permissioned blockchains in enterprise: the honest assessment",
        "MEV: what it is and why builders should care",
        "Restaking and shared security: the new primitives",
        "On-ramps and off-ramps: the unsexy infrastructure that matters",
        "Bitcoin as treasury: the corporate playbook",
    ],
    "drone": [
        "Drone delivery in cities: regulatory and engineering hurdles",
        "Beyond visual line of sight: the regulatory shift in 2026",
        "Drone swarms: coordination algorithms in practice",
        "Counter-drone systems: detection and mitigation",
        "Mapping and surveying with consumer-grade drones",
        "Drones in precision agriculture: ROI math",
        "Inspection drones for infrastructure: the workflow",
        "Drone batteries: chemistry trade-offs and field practices",
        "Drone autonomy stacks: open-source vs. proprietary",
        "Aerial photography for journalism: ethics and craft",
        "Drones in disaster response: case studies",
        "Cargo drones: the middle-mile opportunity",
        "Drone pilot certification: the global landscape",
        "FPV racing technology and its commercial spillover",
        "Underwater drones: an emerging category",
        "Drone-based wildlife monitoring",
        "Software-defined radio in drone communications",
        "Drone insurance: what operators need to know",
        "Building a drone fleet operations team",
        "Pakistan's drone industry: opportunities and constraints",
    ],
    "robotics": [
        "Humanoid robots in 2026: hype vs. deployment reality",
        "ROS 2 in production: the patterns that survive",
        "Robotic process automation vs. physical robots: when each wins",
        "Warehouse robotics: the architecture of fulfillment automation",
        "Surgical robotics: the regulatory and engineering bar",
        "Cobots: collaborative robots in small manufacturing",
        "Robot perception: the sensor stack",
        "Manipulation: still the hardest problem in robotics",
        "Sim-to-real transfer for robot learning",
        "Open-source robotics platforms worth a look",
        "Robotics for elder care: the human factors",
        "Agricultural robotics: harvesting at scale",
        "Robotics safety standards: a practitioner's overview",
        "Robot teleoperation: when remote control is the answer",
        "Soft robotics: applications beyond research",
        "Mobile robots in hospitals: logistics and disinfection",
        "Robotics in construction: the slow revolution",
        "Drone-mounted manipulators: the new frontier",
        "Robotics startups: the capital intensity problem",
        "Robotics curricula for South Asian universities",
    ],
    "quantum-computing": [
        "Quantum computing in 2026: where we actually are",
        "Quantum-resistant cryptography: the migration roadmap",
        "Variational quantum algorithms: the near-term toolkit",
        "Quantum machine learning: separating signal from noise",
        "Superconducting qubits vs. ion traps vs. photonics",
        "Error correction milestones and what they mean",
        "Quantum-as-a-service: the cloud landscape",
        "Quantum sensing: the underrated application",
        "Hybrid classical-quantum architectures in practice",
        "What quantum computing won't do, ever",
        "Quantum networking: the path to a quantum internet",
        "Quantum advantage claims: how to read them critically",
        "Career paths in quantum computing for software engineers",
        "Quantum chemistry simulations: the killer app?",
        "Open-source quantum frameworks compared",
        "Quantum random number generation in production",
        "Quantum optimization: combinatorial problems revisited",
        "Quantum cryptography vs. post-quantum cryptography",
        "Topological qubits: the long bet",
        "Educational pathways into quantum computing",
    ],
    "virtual-reality-vr": [
        "VR for enterprise training: where it actually pays off",
        "AR vs. VR vs. mixed reality: the 2026 spectrum",
        "Spatial computing: the design language emerging",
        "WebXR: building cross-platform immersive experiences",
        "Haptics in VR: the next frontier",
        "VR for remote collaboration: lessons from production deployments",
        "Locomotion in VR: comfort vs. immersion",
        "Eye tracking in VR: privacy and possibility",
        "VR for therapy: clinical evidence and gaps",
        "Building VR apps with Unity in 2026",
        "VR for education: the curricula that work",
        "Spatial audio: the underrated immersion lever",
        "Passthrough AR: the new default for headsets",
        "VR for architecture and real estate walkthroughs",
        "Avatars in social VR: identity, expression, and moderation",
        "VR fitness: the category that surprised the industry",
        "Headset hardware in 2026: a buyer's snapshot",
        "VR in healthcare beyond pain management",
        "Cinematic VR: the storytelling grammar",
        "Performance optimization for mobile VR",
    ],
}


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

def rotate_category(date_iso: str, categories: list[str] = None) -> str:
    """Deterministic: day-of-year mod len(categories)."""
    cats = categories or DEFAULT_ROTATION
    dt = datetime.strptime(date_iso[:10], "%Y-%m-%d")
    return cats[dt.toordinal() % len(cats)]


# ---------------------------------------------------------------------------
# Topic selection + dedup
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "with",
    "is", "are", "be", "by", "from", "at", "as", "how", "what", "why",
    "this", "that", "your", "you", "it", "its", "i", "we", "us",
}


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD_RE.findall(s.lower()) if w not in _STOPWORDS and len(w) > 2}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_duplicate(title: str, existing_titles: list[str], threshold: float = 0.55) -> bool:
    return any(jaccard(title, t) >= threshold for t in existing_titles)


def pick_topic(
    category: str,
    *,
    existing_titles: list[str],
    seed: int | str | None = None,
) -> str:
    """Pick a topic seed not too similar to any existing title.

    Deterministic per (category, seed): same inputs always return the same
    topic. Falls back to the first topic if every option is too similar
    (caller can still ask the LLM to rephrase from a covered angle).
    """
    bank = TOPIC_BANKS.get(category)
    if not bank:
        raise ValueError(f"No topic bank for category {category!r}")

    # Deterministic shuffle keyed by (category, seed).
    seed_str = f"{category}::{seed}" if seed is not None else category
    key = int(hashlib.sha256(seed_str.encode()).hexdigest(), 16)
    rng = random.Random(key)
    order = list(bank)
    rng.shuffle(order)

    for topic in order:
        if not is_duplicate(topic, existing_titles):
            return topic
    return order[0]
