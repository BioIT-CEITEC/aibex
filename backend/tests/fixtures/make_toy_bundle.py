"""Generate a small synthetic two-modality bundle (RNA-seq DE + RNA editing) for tests and offline demos.

Usage:  uv run python tests/fixtures/make_toy_bundle.py <data_dir>     → writes <data_dir>/toy/
The data are random but deterministic (seeded). No real data are involved.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import polars as pl
import yaml

N_GENES = 200
N_SITES = 300
SAMPLES = [("WT_1", "WT"), ("WT_2", "WT"), ("WT_3", "WT"), ("KO_1", "KO"), ("KO_2", "KO"), ("KO_3", "KO")]


def make_toy_bundle(data_dir: Path, bundle_id: str = "toy") -> Path:
    rnd = random.Random(42)
    out = Path(data_dir) / bundle_id
    (out / "tables").mkdir(parents=True, exist_ok=True)

    gene_ids = [f"ENSMUSG{i:011d}" for i in range(1, N_GENES + 1)]
    gene_names = [f"Gene_{i:03d}" for i in range(1, N_GENES + 1)]
    lfc = [rnd.gauss(0, 1.2) for _ in range(N_GENES)]
    # make the first 20 genes clearly significant
    padj = [
        10 ** -rnd.uniform(4, 12) if i < 20 else min(1.0, 10 ** -rnd.uniform(0, 2.5)) for i in range(N_GENES)
    ]
    de = pl.DataFrame(
        {
            "gene_id": gene_ids,
            "gene_name": gene_names,
            "baseMean": [round(10 ** rnd.uniform(1, 4), 2) for _ in range(N_GENES)],
            "log2FoldChange": [round(x, 4) for x in lfc],
            "padj": padj,
        }
    )
    de.write_parquet(out / "tables" / "de.parquet")

    counts = {"gene_id": gene_ids}
    for s, cond in SAMPLES:
        counts[s] = [
            max(0, int(rnd.gauss(500 * (2 ** (lfc[i] if cond == "KO" else 0)), 50))) for i in range(N_GENES)
        ]
    pl.DataFrame(counts).write_parquet(out / "tables" / "counts.parquet")

    site_gene = [gene_ids[rnd.randrange(N_GENES)] for _ in range(N_SITES)]
    edit_wt = [round(rnd.uniform(0.05, 0.9), 4) for _ in range(N_SITES)]
    edit_ko = [round(max(0.0, w - abs(rnd.gauss(0.3, 0.15))), 4) for w in edit_wt]
    editing = pl.DataFrame(
        {
            "site_id": [f"site_{i:04d}" for i in range(1, N_SITES + 1)],
            "gene_id": site_gene,
            "chrom": [f"chr{rnd.randint(1, 19)}" for _ in range(N_SITES)],
            "position": [rnd.randint(1_000_000, 150_000_000) for _ in range(N_SITES)],
            "edit_wt": edit_wt,
            "edit_ko": edit_ko,
            "delta": [round(k - w, 4) for w, k in zip(edit_wt, edit_ko)],
        }
    )
    editing.write_parquet(out / "tables" / "editing.parquet")

    pl.DataFrame({"sample": [s for s, _ in SAMPLES], "genotype": [c for _, c in SAMPLES]}).write_csv(
        out / "samples.tsv", separator="\t"
    )

    manifest = {
        "id": bundle_id,
        "title": "Toy bundle – synthetic RNA-seq + RNA editing",
        "description": "Synthetic data for tests (seeded random).",
        "organism": "Mus musculus",
        "modalities": ["rna-seq", "rna-editing"],
        "contrast": {"name": "KO_vs_WT", "numerator": "KO", "denominator": "WT"},
        "samples": "samples.tsv",
        "tables": {
            "de": {
                "file": "tables/de.parquet",
                "description": "differential expression, one row per gene",
                "key": "gene_id",
                "columns": {
                    "gene_id": {"type": "string"},
                    "gene_name": {"type": "string"},
                    "baseMean": {"type": "float"},
                    "log2FoldChange": {"type": "float"},
                    "padj": {"type": "float"},
                },
            },
            "counts": {
                "file": "tables/counts.parquet",
                "description": "normalised counts, genes x samples",
                "key": "gene_id",
                "columns": {"gene_id": {"type": "string"}},
            },
            "editing": {
                "file": "tables/editing.parquet",
                "description": "editing level per site",
                "key": "site_id",
                "columns": {
                    "site_id": {"type": "string"},
                    "gene_id": {"type": "string"},
                    "chrom": {"type": "string"},
                    "position": {"type": "int"},
                    "edit_wt": {"type": "float"},
                    "edit_ko": {"type": "float"},
                    "delta": {"type": "float"},
                },
            },
        },
        "links": [{"from": "editing.gene_id", "to": "de.gene_id"}, {"from": "counts.gene_id", "to": "de.gene_id"}],
    }
    (out / "bundle.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    assert not math.isnan(sum(padj))
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/toy-data")
    print(make_toy_bundle(target))
