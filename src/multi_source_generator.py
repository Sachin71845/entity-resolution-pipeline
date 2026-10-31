"""
Multi-Source Synthetic Dataset Generator.

Generates heterogeneous, realistic input datasets for three independent systems:
1. CRM (CSV) -> data/input/crm_customers.csv (Key format: CUST-00123)
2. Billing (JSON) -> data/input/billing_accounts.json (Key format: b_123)
3. ERP (CSV) -> data/input/erp_clients.csv (Key format: 00123)

Generates a master canonical customer population first, then derives cross-system records
with exact email matches, normalization noise, name+phone matches, email collisions,
duplicates, and data quality anomalies.

Exports a ground truth expected benchmark to: data/expected/multi_source_expected.csv
"""

import json
import random
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import pandas as pd
from faker import Faker

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = BASE_DIR / "data" / "input"
DEFAULT_EXPECTED_DIR = BASE_DIR / "data" / "expected"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("multi_source_generator")


def generate_multi_source_datasets(
    base_population: int = 30,
    seed: int = 42,
    input_dir: Optional[Path] = None,
    expected_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Generate CRM (CSV), Billing (JSON), and ERP (CSV) datasets derived from
    a common underlying customer population.
    """
    in_dir = Path(input_dir or DEFAULT_INPUT_DIR)
    exp_dir = Path(expected_dir or DEFAULT_EXPECTED_DIR)
    in_dir.mkdir(parents=True, exist_ok=True)
    exp_dir.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    fake = Faker()
    Faker.seed(seed)

    # --------------------------------------------------------------------------
    # 1. Generate Canonical Customer Population (Ground Truth Truth Anchor)
    # --------------------------------------------------------------------------
    customers: List[Dict[str, Any]] = []
    base_time = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)

    for i in range(1, base_population + 1):
        name = fake.name()
        username = fake.user_name().lower()
        domain = fake.free_email_domain()
        primary_email = f"{username}_{i}@{domain}"
        primary_phone = fake.numerify("9#########")

        customers.append({
            "anchor_id": f"CAN-{1000 + i}",
            "name": name,
            "email": primary_email,
            "phone": primary_phone,
            "crm_id": f"CUST-{10000 + i}",
            "billing_id": f"b_{100 + i}",
            "erp_id": f"{20000 + i:05d}",
        })

    # Output buckets
    crm_records: List[Dict[str, Any]] = []
    billing_records: List[Dict[str, Any]] = []
    erp_records: List[Dict[str, Any]] = []
    expected_mappings: List[Dict[str, Any]] = []

    # --------------------------------------------------------------------------
    # 2. Derive Records Across Systems
    # --------------------------------------------------------------------------

    # Group 1: 3-Way Cross-System Presence (Full Omnichannel Customers)
    # Appears in CRM (first -> NEW_ENTITY), Billing (exact email -> MAPPED), ERP (normalized email -> MAPPED)
    for i in range(0, 10):
        c = customers[i]
        t_crm = (base_time + timedelta(hours=i)).isoformat()
        t_bill = (base_time + timedelta(days=1, hours=i)).isoformat()
        t_erp = (base_time + timedelta(days=2, hours=i)).isoformat()

        # CRM Record (Ingested First)
        crm_records.append({
            "customer_id": c["crm_id"],
            "full_name": c["name"],
            "email_address": c["email"],
            "phone_number": c["phone"],
            "created_at": t_crm
        })
        expected_mappings.append({
            "source_system": "CRM",
            "source_id": c["crm_id"],
            "expected_outcome": "NEW_ENTITY",
            "expected_match_type": "new",
            "canonical_anchor_id": c["anchor_id"]
        })

        # Billing Record (Exact Email Match)
        billing_records.append({
            "account_id": c["billing_id"],
            "contact_name": c["name"],
            "billing_email": c["email"],
            "contact_phone": c["phone"],
            "last_invoice_date": t_bill
        })
        expected_mappings.append({
            "source_system": "BILLING",
            "source_id": c["billing_id"],
            "expected_outcome": "MAPPED",
            "expected_match_type": "exact_email",
            "canonical_anchor_id": c["anchor_id"]
        })

        # ERP Record (Exact Email After Normalization - uppercase & padded)
        noisy_email = f"  {c['email'].upper()}  "
        erp_records.append({
            "client_code": c["erp_id"],
            "company_or_person_name": c["name"],
            "primary_email": noisy_email,
            "telephone": f"+91 {c['phone']}",
            "updated_timestamp": t_erp
        })
        expected_mappings.append({
            "source_system": "ERP",
            "source_id": c["erp_id"],
            "expected_outcome": "MAPPED",
            "expected_match_type": "exact_email_after_normalization",
            "canonical_anchor_id": c["anchor_id"]
        })

    # Group 2: Secondary Rule Matches (Name + Phone Match with differing email)
    for i in range(10, 15):
        c = customers[i]
        t_crm = (base_time + timedelta(days=3, hours=i)).isoformat()
        t_erp = (base_time + timedelta(days=4, hours=i)).isoformat()

        # CRM: Original anchor
        crm_records.append({
            "customer_id": c["crm_id"],
            "full_name": c["name"],
            "email_address": c["email"],
            "phone_number": c["phone"],
            "created_at": t_crm
        })
        expected_mappings.append({
            "source_system": "CRM",
            "source_id": c["crm_id"],
            "expected_outcome": "NEW_ENTITY",
            "expected_match_type": "new",
            "canonical_anchor_id": c["anchor_id"]
        })

        # ERP: Different personal/business email, but same person name and phone!
        alt_email = f"work_{c['email']}"
        erp_records.append({
            "client_code": c["erp_id"],
            "company_or_person_name": c["name"],
            "primary_email": alt_email,
            "telephone": c["phone"],
            "updated_timestamp": t_erp
        })
        expected_mappings.append({
            "source_system": "ERP",
            "source_id": c["erp_id"],
            "expected_outcome": "MAPPED",
            "expected_match_type": "rule_name_phone",
            "canonical_anchor_id": c["anchor_id"]
        })

    # Group 3: Email Collision & Multiple Candidates
    # Customer 15 and 16 share the same email address (household/family sharing)
    shared_email = "shared_household@familymail.com"
    c15 = customers[15]
    c16 = customers[16]
    c17 = customers[17]

    crm_records.append({
        "customer_id": c15["crm_id"],
        "full_name": c15["name"],
        "email_address": shared_email,
        "phone_number": c15["phone"],
        "created_at": (base_time + timedelta(days=5, hours=1)).isoformat()
    })
    expected_mappings.append({
        "source_system": "CRM",
        "source_id": c15["crm_id"],
        "expected_outcome": "CONFLICT",
        "expected_match_type": "email_collision",
        "canonical_anchor_id": None
    })

    crm_records.append({
        "customer_id": c16["crm_id"],
        "full_name": c16["name"],
        "email_address": shared_email,
        "phone_number": c16["phone"],
        "created_at": (base_time + timedelta(days=5, hours=2)).isoformat()
    })
    expected_mappings.append({
        "source_system": "CRM",
        "source_id": c16["crm_id"],
        "expected_outcome": "CONFLICT",
        "expected_match_type": "email_collision",
        "canonical_anchor_id": None
    })

    # Third customer in Billing also using that collided email -> multiple_candidates
    billing_records.append({
        "account_id": c17["billing_id"],
        "contact_name": c17["name"],
        "billing_email": shared_email,
        "contact_phone": c17["phone"],
        "last_invoice_date": (base_time + timedelta(days=5, hours=3)).isoformat()
    })
    expected_mappings.append({
        "source_system": "BILLING",
        "source_id": c17["billing_id"],
        "expected_outcome": "CONFLICT",
        "expected_match_type": "multiple_candidates",
        "canonical_anchor_id": None
    })

    # Group 4: CRM Unique Customer (Only in CRM -> NEW_ENTITY)
    c18 = customers[18]
    crm_records.append({
        "customer_id": c18["crm_id"],
        "full_name": c18["name"],
        "email_address": c18["email"],
        "phone_number": c18["phone"],
        "created_at": (base_time + timedelta(days=6)).isoformat()
    })
    expected_mappings.append({
        "source_system": "CRM",
        "source_id": c18["crm_id"],
        "expected_outcome": "NEW_ENTITY",
        "expected_match_type": "new",
        "canonical_anchor_id": c18["anchor_id"]
    })

    # Group 5: Billing Unique Customer (Only in Billing -> NEW_ENTITY)
    c19 = customers[19]
    billing_records.append({
        "account_id": c19["billing_id"],
        "contact_name": c19["name"],
        "billing_email": c19["email"],
        "contact_phone": c19["phone"],
        "last_invoice_date": (base_time + timedelta(days=7)).isoformat()
    })
    expected_mappings.append({
        "source_system": "BILLING",
        "source_id": c19["billing_id"],
        "expected_outcome": "NEW_ENTITY",
        "expected_match_type": "new",
        "canonical_anchor_id": c19["anchor_id"]
    })

    # Group 6: ERP Unique Customer (Only in ERP -> NEW_ENTITY)
    c20 = customers[20]
    erp_records.append({
        "client_code": c20["erp_id"],
        "company_or_person_name": c20["name"],
        "primary_email": c20["email"],
        "telephone": c20["phone"],
        "updated_timestamp": (base_time + timedelta(days=8)).isoformat()
    })
    expected_mappings.append({
        "source_system": "ERP",
        "source_id": c20["erp_id"],
        "expected_outcome": "NEW_ENTITY",
        "expected_match_type": "new",
        "canonical_anchor_id": c20["anchor_id"]
    })

    # Group 7: Unresolved Record (no email and no phone)
    c21 = customers[21]
    crm_records.append({
        "customer_id": c21["crm_id"],
        "full_name": c21["name"],
        "email_address": "",
        "phone_number": "",
        "created_at": (base_time + timedelta(days=9)).isoformat()
    })
    expected_mappings.append({
        "source_system": "CRM",
        "source_id": c21["crm_id"],
        "expected_outcome": "UNRESOLVED",
        "expected_match_type": "no_identifiers",
        "canonical_anchor_id": None
    })

    # Group 8: Duplicate Key Record (Re-emitting CUST-10001)
    c_dup = customers[0]
    crm_records.append({
        "customer_id": c_dup["crm_id"],
        "full_name": c_dup["name"],
        "email_address": c_dup["email"],
        "phone_number": c_dup["phone"],
        "created_at": (base_time + timedelta(days=10)).isoformat()
    })
    expected_mappings.append({
        "source_system": "CRM",
        "source_id": c_dup["crm_id"],
        "expected_outcome": "DUPLICATE",
        "expected_match_type": "duplicate_source_key",
        "canonical_anchor_id": None
    })

    # Group 9: Data Quality Rejects
    # Reject 1: Missing primary key in CRM
    crm_records.append({
        "customer_id": "",
        "full_name": "Ghost Customer",
        "email_address": "ghost@example.com",
        "phone_number": "9000000099",
        "created_at": (base_time + timedelta(days=11)).isoformat()
    })
    expected_mappings.append({
        "source_system": "CRM",
        "source_id": "",
        "expected_outcome": "REJECTED",
        "expected_match_type": "missing_source_id",
        "canonical_anchor_id": None
    })

    # Reject 2: Invalid Email in ERP
    c22 = customers[22]
    erp_records.append({
        "client_code": c22["erp_id"],
        "company_or_person_name": c22["name"],
        "primary_email": "invalid_email_format@",
        "telephone": c22["phone"],
        "updated_timestamp": (base_time + timedelta(days=12)).isoformat()
    })
    expected_mappings.append({
        "source_system": "ERP",
        "source_id": c22["erp_id"],
        "expected_outcome": "REJECTED",
        "expected_match_type": "invalid_email",
        "canonical_anchor_id": None
    })

    # --------------------------------------------------------------------------
    # 3. Export to Target Files
    # --------------------------------------------------------------------------
    crm_file = in_dir / "crm_customers.csv"
    billing_file = in_dir / "billing_accounts.json"
    erp_file = in_dir / "erp_clients.csv"
    expected_file = exp_dir / "multi_source_expected.csv"

    # Save CRM (CSV)
    df_crm = pd.DataFrame(crm_records)
    df_crm.to_csv(crm_file, index=False, encoding="utf-8-sig")
    logger.info("Saved CRM dataset: %s (%d records)", crm_file.name, len(df_crm))

    # Save Billing (JSON)
    billing_payload = {
        "metadata": {
            "source": "BILLING",
            "format_version": "1.0",
            "record_count": len(billing_records),
            "generated_at": datetime.now(timezone.utc).isoformat()
        },
        "accounts": billing_records
    }
    with open(billing_file, "w", encoding="utf-8") as f:
        json.dump(billing_payload, f, indent=2)
    logger.info("Saved Billing dataset: %s (%d records)", billing_file.name, len(billing_records))

    # Save ERP (CSV)
    df_erp = pd.DataFrame(erp_records)
    df_erp.to_csv(erp_file, index=False, encoding="utf-8-sig")
    logger.info("Saved ERP dataset: %s (%d records)", erp_file.name, len(df_erp))

    # Save Ground Truth Expected Crosswalk
    df_expected = pd.DataFrame(expected_mappings)
    df_expected.to_csv(expected_file, index=False, encoding="utf-8")
    logger.info("Saved Expected Ground Truth Crosswalk: %s (%d records)", expected_file.name, len(df_expected))

    return {
        "crm_count": len(crm_records),
        "billing_count": len(billing_records),
        "erp_count": len(erp_records),
        "total_records": len(crm_records) + len(billing_records) + len(erp_records),
        "files": {
            "crm": str(crm_file),
            "billing": str(billing_file),
            "erp": str(erp_file),
            "expected": str(expected_file)
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate CRM, Billing, and ERP datasets from a common customer population."
    )
    parser.add_argument(
        "--population", "-p",
        type=int,
        default=30,
        help="Base customer population size (default: 30)"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Fixed random seed for deterministic reproducibility (default: 42)"
    )
    args = parser.parse_args()

    summary = generate_multi_source_datasets(
        base_population=args.population,
        seed=args.seed
    )

    print("\n" + "=" * 60)
    print("      MULTI-SOURCE DATASET GENERATION SUMMARY")
    print("=" * 60)
    print(f"CRM Records (CSV):      {summary['crm_count']}")
    print(f"Billing Records (JSON): {summary['billing_count']}")
    print(f"ERP Records (CSV):      {summary['erp_count']}")
    print(f"Total Combined Records: {summary['total_records']}")
    print("-" * 60)
    for k, v in summary["files"].items():
        print(f"  [{k.upper():8s}] {v}")
    print("=" * 60)


if __name__ == "__main__":
    main()
