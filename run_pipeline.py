#!/usr/bin/env python3
"""
Convenience runner for the Entity Resolution Pipeline.

Usage:
    python run_pipeline.py
    python run_pipeline.py --input data/input/synthetic_records.csv
    python run_pipeline.py --force
    python run_pipeline.py --input data/input/source_records.csv --force --db data/pipeline.db
"""
from src.pipeline import main

if __name__ == "__main__":
    main()

