from setuptools import setup, find_packages

setup(
    name="entity-resolution-pipeline",
    version="1.0.0",
    description="Deterministic entity resolution pipeline: maps source IDs to canonical golden records.",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.10",
    install_requires=[
        "pandas>=2.2,<3.0",
        "Faker>=37.0,<38.0",
        "PyYAML>=6.0,<7.0",
        "python-dotenv>=1.0,<2.0",
    ],
    extras_require={
        "test": ["pytest>=8.3,<9.0"],
        "mssql": ["SQLAlchemy>=2.0,<3.0", "pyodbc>=5.2,<6.0"],
    },
    entry_points={
        "console_scripts": [
            "entity-resolution=src.pipeline:main",
        ],
    },
)

