# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pydeseq2>=0.4",
#   "pandas>=2",
#   "pyarrow>=15",
#   "pyyaml>=6",
#   "certifi",
# ]
# ///
"""Build the public `airway` results bundle (docs/bundle-format.md).

Data: Himes et al. 2014 (GEO GSE52778), airway smooth muscle cells from 4 donors, untreated vs dexamethasone –
the dataset of the Bioconductor `airway` package. The gene x sample count table, sample sheet and GRCh38 gene
annotation are taken as CSV from the public bioconnector workshop repository (derived from the `airway` package), so
no R is needed. Differential expression is computed here with pydeseq2 (design `~ cell + dex`, treated vs control);
pydeseq2 stays a dependency of this script only, never of the backend.

Usage (needs network on the first run; downloads are cached in `<out>/source/`):

    uv run scripts/make_airway_bundle.py                 # → $AIBEX_DATA_DIR/airway (default: data/airway)
    uv run scripts/make_airway_bundle.py --out /tmp/airway

Output:
    bundle.yaml, samples.tsv (sample, dex, cell, geo_id),
    tables/de.parquet      one row per gene: DESeq2 results + symbol, biotype, location
    tables/counts.parquet  DESeq2 size-factor normalised counts (matrix table: gene_id + one column per sample)
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
import urllib.request
from pathlib import Path

import certifi
import pandas as pd
import yaml

BASE = "https://raw.githubusercontent.com/bioconnector/workshops/master/data/"
FILES = {
    "counts": "airway_scaledcounts.csv",
    "metadata": "airway_metadata.csv",
    "genes": "annotables_grch38.csv",
}
MIN_TOTAL_COUNT = 10  # genes with fewer reads over all samples are dropped (as in the DESeq2 vignette)


def default_out() -> Path:
    data = os.getenv("AIBEX_DATA_DIR") or str(Path(__file__).resolve().parent.parent / "data")
    return Path(data) / "airway"


def download(source_dir: Path) -> dict[str, Path]:
    source_dir.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context(cafile=certifi.where())
    paths = {}
    for key, name in FILES.items():
        path = source_dir / name
        if not path.exists() or path.stat().st_size == 0:
            print(f"downloading {BASE + name}", file=sys.stderr)
            with urllib.request.urlopen(BASE + name, timeout=60, context=ctx) as r:
                tmp = path.with_suffix(".part")
                tmp.write_bytes(r.read())
                tmp.replace(path)
        paths[key] = path
    return paths


def load(paths: dict[str, Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    counts = pd.read_csv(paths["counts"]).rename(columns={"ensgene": "gene_id"}).set_index("gene_id")
    meta = pd.read_csv(paths["metadata"]).rename(columns={"id": "sample", "celltype": "cell"})
    meta = meta[["sample", "dex", "cell", "geo_id"]]
    if list(meta["sample"]) != list(counts.columns):
        counts = counts[list(meta["sample"])]
    genes = (
        pd.read_csv(paths["genes"], dtype={"chr": str})
        .drop_duplicates("ensgene")
        .rename(columns={"ensgene": "gene_id", "symbol": "gene_name", "chr": "chrom"})
    )
    genes = genes[["gene_id", "gene_name", "biotype", "chrom", "start", "end", "description"]]
    genes["description"] = genes["description"].str.replace(r"\s*\[Source:.*\]$", "", regex=True)
    return counts, meta, genes


def run_deseq(counts: pd.DataFrame, meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    from pydeseq2.dds import DeseqDataSet
    from pydeseq2.ds import DeseqStats

    counts = counts.round().astype(int)
    counts = counts[counts.sum(axis=1) >= MIN_TOTAL_COUNT]
    md = meta.set_index("sample")[["dex", "cell"]]
    md["dex"] = pd.Categorical(md["dex"], categories=["control", "treated"])
    try:  # pydeseq2 >= 0.5: formula design
        dds = DeseqDataSet(counts=counts.T, metadata=md, design="~cell + dex", quiet=True)
    except TypeError:  # older pydeseq2
        dds = DeseqDataSet(
            counts=counts.T, metadata=md, design_factors=["cell", "dex"], ref_level=["dex", "control"]
        )
    dds.deseq2()
    stats = DeseqStats(dds, contrast=["dex", "treated", "control"], quiet=True)
    stats.summary()
    res = stats.results_df.rename_axis("gene_id").reset_index()
    normed = pd.DataFrame(dds.layers["normed_counts"], index=dds.obs_names, columns=dds.var_names).T
    normed = normed.round(2).rename_axis("gene_id").reset_index()
    return res, normed


def bundle_yaml(n_genes: int) -> dict:
    f, s, i = {"type": "float"}, {"type": "string"}, {"type": "int"}
    return {
        "id": "airway",
        "title": "Airway smooth muscle cells – dexamethasone vs control (public)",
        "description": (
            "Public RNA-seq of primary human airway smooth muscle cells from 4 donors, untreated or treated with "
            "dexamethasone (Himes et al. 2014, GEO GSE52778; Bioconductor `airway` package). Differential expression "
            f"computed with pydeseq2, design ~ cell + dex, treated vs control; {n_genes} genes with >= "
            f"{MIN_TOTAL_COUNT} reads in total."
        ),
        "organism": "Homo sapiens",
        "genome": "GRCh38",
        "modalities": ["rna-seq"],
        "contrast": {"name": "treated_vs_control", "numerator": "treated", "denominator": "control"},
        "samples": "samples.tsv",
        "tables": {
            "de": {
                "file": "tables/de.parquet",
                "description": "DESeq2 (pydeseq2) results, one row per gene, dexamethasone treated vs control",
                "key": "gene_id",
                "columns": {
                    "gene_id": {**s, "description": "Ensembl gene id"},
                    "gene_name": {**s, "description": "HGNC gene symbol"},
                    "biotype": {**s, "description": "Ensembl gene biotype"},
                    "chrom": {**s, "description": "chromosome (GRCh38)"},
                    "start": {**i, "description": "gene start (GRCh38)"},
                    "end": {**i, "description": "gene end (GRCh38)"},
                    "description": {**s, "description": "gene description"},
                    "baseMean": {**f, "description": "mean of normalised counts over all samples"},
                    "log2FoldChange": {**f, "description": "log2 fold change, treated vs control"},
                    "lfcSE": {**f, "description": "standard error of log2FoldChange"},
                    "stat": {**f, "description": "Wald statistic"},
                    "pvalue": {**f, "description": "Wald test p-value"},
                    "padj": {**f, "description": "BH-adjusted p-value"},
                },
            },
            "counts": {
                "file": "tables/counts.parquet",
                "description": "DESeq2 size-factor normalised counts, genes x samples",
                "key": "gene_id",
                "columns": {"gene_id": {**s, "description": "Ensembl gene id"}},
            },
        },
        "links": [{"from": "counts.gene_id", "to": "de.gene_id"}],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=default_out(), help="bundle folder (default: %(default)s)")
    args = ap.parse_args()
    out: Path = args.out

    counts, meta, genes = load(download(out / "source"))
    res, normed = run_deseq(counts, meta)
    de = res.merge(genes, on="gene_id", how="left")
    de = de[
        [
            "gene_id",
            "gene_name",
            "biotype",
            "chrom",
            "start",
            "end",
            "description",
            "baseMean",
            "log2FoldChange",
            "lfcSE",
            "stat",
            "pvalue",
            "padj",
        ]
    ]
    de["start"] = de["start"].astype("Int64")
    de["end"] = de["end"].astype("Int64")
    assert de["gene_id"].is_unique and normed["gene_id"].is_unique

    (out / "tables").mkdir(parents=True, exist_ok=True)
    de.to_parquet(out / "tables" / "de.parquet", index=False)
    normed.to_parquet(out / "tables" / "counts.parquet", index=False)
    meta.to_csv(out / "samples.tsv", sep="\t", index=False)
    with open(out / "bundle.yaml", "w") as fh:
        yaml.safe_dump(bundle_yaml(len(de)), fh, sort_keys=False, allow_unicode=True)

    sig = int(((de["padj"] < 0.05) & (de["log2FoldChange"].abs() >= 1)).sum())
    print(f"wrote {out}: {len(de)} genes, {sig} with padj < 0.05 and |log2FC| >= 1, {len(meta)} samples")


if __name__ == "__main__":
    main()
