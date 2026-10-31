"""
Scalable Synthetic Data Generator for Entity Resolution Pipeline.

Generates realistic, reproducible datasets with controlled entity cross-references,
boundary values, and labeled anomaly scenarios:
1. Exact cross-system matches (CRM, ECOM, MARKETING).
2. Normalization variations (uppercase emails, whitespace padding).
3. Rule-based matches (same name + phone, differing email).
4. Email collisions (shared email with distinct names/phones).
5. Data quality rejects (missing source IDs, malformed emails).
6. Duplicate source keys (identical and conflicting).
7. Unresolved records (no email and no phone).
"""

import random
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd
from faker import Faker

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_PATH = BASE_DIR / "data" / "input" / "synthetic_records.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("data_generator")

SOURCE_SYSTEMS = ["CRM", "ECOM", "MARKETING", "SUPPORT", "PORTAL"]


def generate_synthetic_records(
    total_records: int = 1000,
    seed: int = 42,
    anomaly_rate: float = 0.15
) -> pd.DataFrame:
    """
    Generate synthetic dataset with realistic entity resolution patterns.
    """
    random.seed(seed)
    fake = Faker()
    Faker.seed(seed)

    records: List[Dict[str, Any]] = []

    # Base entity population (~50% of target size)
    base_population_size = max(10, int(total_records * 0.50))
    base_entities: List[Dict[str, str]] = []

    for i in range(base_population_size):
        name = fake.name()
        email_prefix = fake.user_name().lower()
        domain = fake.free_email_domain()
        phone = fake.numerify("9#########")
        base_entities.append({
            "name": name,
            "email": f"{email_prefix}_{i}@{domain}",
            "phone": phone
        })

    base_time = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)

    # 1. Generate core records from base entities
    id_counters: Dict[str, int] = {sys: 100 for sys in SOURCE_SYSTEMS}

    for i in range(base_population_size):
        ent = base_entities[i]
        sys_name = random.choice(SOURCE_SYSTEMS)
        id_counters[sys_name] += 1
        src_id = f"{sys_name[0]}{id_counters[sys_name]}"

        records.append({
            "source_system": sys_name,
            "source_id": src_id,
            "full_name": ent["name"],
            "email": ent["email"],
            "phone": ent["phone"],
            "source_updated_at": (base_time + timedelta(hours=i)).isoformat()
        })

    # 2. Generate multi-system touchpoints (exact email, normalization, name+phone matches)
    target_touchpoints = int(total_records * 0.35)
    for _ in range(target_touchpoints):
        parent_ent = random.choice(base_entities)
        sys_name = random.choice(SOURCE_SYSTEMS)
        id_counters[sys_name] += 1
        src_id = f"{sys_name[0]}{id_counters[sys_name]}"
        ts = (base_time + timedelta(days=random.randint(1, 10), hours=random.randint(1, 23))).isoformat()

        match_scenario = random.random()

        if match_scenario < 0.40:
            # Exact email match
            records.append({
                "source_system": sys_name,
                "source_id": src_id,
                "full_name": parent_ent["name"],
                "email": parent_ent["email"],
                "phone": parent_ent["phone"],
                "source_updated_at": ts
            })

        elif match_scenario < 0.70:
            # Exact email with case/whitespace noise
            noisy_email = parent_ent["email"].upper() if random.random() < 0.5 else f"  {parent_ent['email']}  "
            records.append({
                "source_system": sys_name,
                "source_id": src_id,
                "full_name": parent_ent["name"],
                "email": noisy_email,
                "phone": parent_ent["phone"],
                "source_updated_at": ts
            })

        else:
            # Rule match: Name + Phone match with alternative email
            alt_email = f"alt_{parent_ent['email']}"
            records.append({
                "source_system": sys_name,
                "source_id": src_id,
                "full_name": parent_ent["name"],
                "email": alt_email,
                "phone": parent_ent["phone"],
                "source_updated_at": ts
            })

    # 3. Generate controlled edge cases & anomalies
    remaining = total_records - len(records)
    shared_collision_emails = [f"household_{i}@shared-domain.com" for i in range(5)]

    for i in range(remaining):
        sys_name = random.choice(SOURCE_SYSTEMS)
        id_counters[sys_name] += 1
        src_id = f"{sys_name[0]}{id_counters[sys_name]}"
        ts = (base_time + timedelta(days=random.randint(10, 20))).isoformat()

        anomaly_type = random.choice([
            "email_collision",
            "duplicate_key",
            "missing_id",
            "invalid_email",
            "no_identifiers"
        ])

        if anomaly_type == "email_collision":
            # Distinct name & phone using a shared email
            records.append({
                "source_system": sys_name,
                "source_id": src_id,
                "full_name": fake.name(),
                "email": random.choice(shared_collision_emails),
                "phone": fake.numerify("9#########"),
                "source_updated_at": ts
            })

        elif anomaly_type == "duplicate_key" and records:
            # Re-emit an existing record key
            existing = random.choice(records)
            records.append({
                "source_system": existing["source_system"],
                "source_id": existing["source_id"],
                "full_name": existing["full_name"],
                "email": existing["email"],
                "phone": existing["phone"],
                "source_updated_at": ts
            })

        elif anomaly_type == "missing_id":
            # Data quality reject: missing primary key
            records.append({
                "source_system": sys_name,
                "source_id": "",
                "full_name": fake.name(),
                "email": fake.email(),
                "phone": fake.numerify("9#########"),
                "source_updated_at": ts
            })

        elif anomaly_type == "invalid_email":
            # Data quality reject: malformed email
            records.append({
                "source_system": sys_name,
                "source_id": src_id,
                "full_name": fake.name(),
                "email": "invalid_email_format@",
                "phone": fake.numerify("9#########"),
                "source_updated_at": ts
            })

        elif anomaly_type == "no_identifiers":
            # Unresolved: no email and no phone
            records.append({
                "source_system": sys_name,
                "source_id": src_id,
                "full_name": fake.name(),
                "email": "",
                "phone": "",
                "source_updated_at": ts
            })

    # Shuffle to simulate realistic interleaved stream
    random.shuffle(records)

    df = pd.DataFrame(records)
    logger.info("Generated %d synthetic records (Seed: %d)", len(df), seed)
    return df


def save_dataset(df: pd.DataFrame, output_path: Path):
    """Save generated dataset to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")
    logger.info("Saved synthetic dataset to: %s", output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Scalable Synthetic Dataset Generator for Entity Resolution."
    )
    parser.add_argument(
        "--count", "-n",
        type=int,
        default=1000,
        help="Number of records to generate (e.g. 100, 1000, 10000, 100000; default: 1000)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(DEFAULT_OUTPUT_PATH),
        help="Output CSV path (default: data/input/synthetic_records.csv)"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Fixed random seed for deterministic reproducibility (default: 42)"
    )

    args = parser.parse_args()
    out_path = Path(args.output)

    df = generate_synthetic_records(
        total_records=args.count,
        seed=args.seed
    )
    save_dataset(df, out_path)
    print(f"Generated {len(df)} records -> {out_path}")


if __name__ == "__main__":
    main()

