# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "polars>=1.0",
#   "fastexcel>=0.11",
#   "pyyaml>=6",
# ]
# ///
"""Convert the published ADAR2 results (RNA-seq DE + RNA editing) into the `adar2-editing` bundle.

Input: the raw folder described in docs/adar2-notes.md (default `$AIBEX_DATA_DIR/../raw/adar2-editing`):
    input_files/ADAR_vs_WT_DESeq2.tsv                         DESeq2 ADAR vs WT (+ normalised counts per sample)
    input_files/DE_experiment_design.tsv                      19 samples (condition ADAR / WT)
    input_files/editing_analysis/known_editing_sites/*.tsv    per-sample read counts at known editing sites
    val_editing_sites_table.xlsx                              site → gene annotation (the GTF is not provided)
    custom_scripts/mm10.txt                                   RADAR-style list of known mouse sites (optional)

Follows the known-sites part of `custom_scripts/proces_all_samples_editing_new.R`: per sample and site
`edited = Count_C + Count_G`, `cov = Good_depth`; only the 19 design samples (PER01RE is dropped); only sites of
the xlsx (any edited read, canonical exon of a DE gene). Additional filter (docs/adar2-notes.md, A4): pooled coverage
>= --min-cov reads in both ADAR and WT. Sums are computed per unique site (no double counting of sites that lie in
two overlapping genes). The editing contrast is the same as the DE contrast: ADAR (numerator) vs WT.

Usage:
    uv run scripts/convert_adar2.py                     # raw + out derived from $AIBEX_DATA_DIR (or ./data)
    uv run scripts/convert_adar2.py --raw RAW --out OUT [--min-cov 10]

Output (docs/bundle-format.md): bundle.yaml, samples.tsv, tables/{de,counts,editing,editing_levels}.parquet
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import polars as pl
import yaml

NUM, DEN = "ADAR", "WT"  # contrast (Q10): ADAR vs WT in both modalities
HIGH_CONFIDENCE_MIN_EDITED = 100  # R: val_editing_sites_table_filtered.xlsx = sum_edit_counts > 100
REGION = {"E": "exon", "I": "intron"}


def default_data_dir() -> Path:
    return Path(os.getenv("AIBEX_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------- samples
def read_samples(raw: Path) -> pl.DataFrame:
    """samples.tsv: sample, genotype, group, replicate – WT first, then ADAR (each by group, sample)."""
    d = pl.read_csv(raw / "input_files" / "DE_experiment_design.tsv", separator="\t", infer_schema_length=0)
    s = d.select(
        pl.col("sample_name").alias("sample"),
        pl.col("condition").alias("genotype"),
        pl.col("sample_name").str.extract(r"^([A-Za-z]+)", 1).alias("group"),
        pl.col("replicate"),
    )
    bad = set(s["genotype"]) - {NUM, DEN}
    if bad:
        raise SystemExit(f"unexpected conditions in the design: {sorted(bad)}")
    order = pl.when(pl.col("genotype") == DEN).then(0).otherwise(1)
    return s.sort(order, "group", "sample")


# --------------------------------------------------------------------------------------------------------- de/counts
def read_de(raw: Path, samples: list[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    path = raw / "input_files" / "ADAR_vs_WT_DESeq2.tsv"
    t = pl.read_csv(path, separator="\t", null_values=["NA", ""], infer_schema_length=100_000)
    de = t.select(
        pl.col("Ensembl_Id").alias("gene_id"),
        # the pipeline appends the Ensembl id to duplicated symbols (Zkscan7__ENSMUSG00000063488) – A2
        pl.col("Feature_name").str.replace(r"__ENSMUSG\d+(\.\d+)?$", "").alias("gene_name"),
        pl.col("biotype"),
        *(pl.col(c).cast(pl.Float64) for c in ("baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj")),
    )
    missing = [s for s in samples if f"{s}_normCounts" not in t.columns]
    if missing:
        raise SystemExit(f"normalised counts missing for samples {missing}")
    counts = t.select(
        pl.col("Ensembl_Id").alias("gene_id"),
        *(pl.col(f"{s}_normCounts").cast(pl.Float64).round(2).alias(s) for s in samples),
    )
    if de["gene_id"].n_unique() != de.height:
        raise SystemExit("gene ids in the DE table are not unique")
    return de, counts


# ------------------------------------------------------------------------------------------------------------ sites
def read_site_annotation(raw: Path, de: pl.DataFrame) -> pl.DataFrame:
    """One row per unique site with gene annotation from the xlsx; gene_id via gene_name → DE table.

    A symbol on several DE rows maps to the row with the highest baseMean; a site in several genes is assigned to the
    gene with the highest baseMean (A5), all symbols are kept in `gene_names`.
    """
    x = pl.read_excel(raw / "val_editing_sites_table.xlsx").select(
        pl.col("chr").cast(pl.String).alias("chrom"),
        pl.col("pos").cast(pl.Int64).alias("position"),
        pl.col("gene_name").cast(pl.String),
        pl.col("exon_number").cast(pl.Int64, strict=False),
    ).unique()
    names = (
        de.filter(pl.col("gene_name").is_not_null())
        .sort("baseMean", descending=True, nulls_last=True)
        .unique("gene_name", keep="first")
        .select("gene_name", "gene_id", pl.col("baseMean").alias("_bm"))
    )
    x = x.join(names, on="gene_name", how="left")
    unmapped = x.filter(pl.col("gene_id").is_null())
    if unmapped.height:
        log(f"  {unmapped.height} site/gene rows have a symbol that is not in the DE table – dropped")
    x = x.filter(pl.col("gene_id").is_not_null())
    all_names = x.group_by("chrom", "position").agg(
        pl.col("gene_name").unique().sort().str.join(",").alias("gene_names")
    )
    best = (
        x.sort("_bm", descending=True, nulls_last=True)
        .unique(["chrom", "position"], keep="first")
        .drop("_bm")
    )
    return best.join(all_names, on=["chrom", "position"])


def read_known_db(raw: Path) -> pl.DataFrame | None:
    path = raw / "custom_scripts" / "mm10.txt"
    if not path.exists():
        log("  custom_scripts/mm10.txt not found – strand/region/known_db left empty")
        return None
    m = pl.read_csv(path, separator="\t", infer_schema_length=0, quote_char=None)
    return (
        m.select(
            pl.col("chrom").str.replace(r"^chr", "").alias("chrom"),
            pl.col("coordinate").cast(pl.Int64).alias("position"),
            pl.col("strand"),
            pl.col("seqReg").replace_strict(REGION, default=pl.col("seqReg")).alias("region"),
        )
        .unique(["chrom", "position"], keep="first")
        .with_columns(pl.lit(True).alias("known_db"))
    )


def read_site_counts(raw: Path, samples: pl.DataFrame, sites: pl.DataFrame) -> pl.DataFrame:
    """Long table sample × site: edited (Count_C + Count_G), cov (Good_depth), restricted to the annotated sites."""
    folder = raw / "input_files" / "editing_analysis" / "known_editing_sites"
    keys = sites.select("chrom", "position").lazy()
    frames = []
    for s in samples["sample"]:
        path = folder / f"{s}.known_editing_sites_AF.tsv"
        if not path.exists():
            raise SystemExit(f"editing counts missing for sample {s}: {path}")
        lf = (
            pl.scan_csv(path, separator="\t", schema_overrides={"#CHR": pl.String})
            .select(
                pl.col("#CHR").str.replace(r"^chr", "").alias("chrom"),
                pl.col("POS").cast(pl.Int64).alias("position"),
                (pl.col("Count_C") + pl.col("Count_G")).cast(pl.Int64).alias("edited"),
                pl.col("Good_depth").cast(pl.Int64).alias("cov"),
            )
            .join(keys, on=["chrom", "position"], how="semi")
            # a position listed twice in a file would be summed twice by a join; keep one row per site
            .unique(["chrom", "position"], keep="first")
            .with_columns(pl.lit(s).alias("sample"))
        )
        frames.append(lf)
    long = pl.concat(frames).collect()
    return long.join(samples.select("sample", "genotype"), on="sample")


def summarise_sites(
    sites: pl.DataFrame, long: pl.DataFrame, known: pl.DataFrame | None, min_cov: int
) -> tuple[pl.DataFrame, pl.DataFrame]:
    def pooled(geno: str, col: str) -> pl.Expr:
        return pl.col(col).filter(pl.col("genotype") == geno).sum()

    agg = long.group_by("chrom", "position").agg(
        pooled(DEN, "cov").alias("cov_wt"),
        pooled(NUM, "cov").alias("cov_adar"),
        pooled(DEN, "edited").alias("edited_wt"),
        pooled(NUM, "edited").alias("edited_adar"),
        pl.col("edited").sum().alias("_edited_all"),
        (pl.col("cov") > 0).sum().cast(pl.Int64).alias("n_samples_covered"),
    )
    ed = sites.join(agg, on=["chrom", "position"], how="inner")
    if known is not None:
        ed = ed.join(known, on=["chrom", "position"], how="left")
    else:
        ed = ed.with_columns(
            pl.lit(None, pl.String).alias("strand"), pl.lit(None, pl.String).alias("region"), pl.lit(False).alias("known_db")
        )
    n_all = ed.height
    ed = (
        ed.filter((pl.col("cov_wt") >= min_cov) & (pl.col("cov_adar") >= min_cov))
        .with_columns(
            (pl.col("edited_wt") / pl.col("cov_wt")).alias("edit_wt"),
            (pl.col("edited_adar") / pl.col("cov_adar")).alias("edit_adar"),
            (pl.col("_edited_all") > HIGH_CONFIDENCE_MIN_EDITED).alias("high_confidence"),
            pl.col("known_db").fill_null(False),
        )
        .with_columns((pl.col("edit_adar") - pl.col("edit_wt")).alias("delta"))
        .with_columns(
            (pl.col("chrom") + ":" + pl.col("position").cast(pl.String)).alias("site_id"),
            *(pl.col(c).round(5) for c in ("edit_wt", "edit_adar", "delta")),
        )
        .sort(chrom_order(), "position")
        .select(
            "site_id", "gene_id", "gene_name", "gene_names", "chrom", "position", "exon_number",
            "strand", "region", "known_db", "cov_wt", "cov_adar", "edited_wt", "edited_adar",
            "edit_wt", "edit_adar", "delta", "high_confidence", "n_samples_covered",
        )
    )
    log(f"  {n_all} annotated sites with counts, {ed.height} with pooled coverage >= {min_cov} in both conditions")
    levels = (
        long.join(ed.select("chrom", "position", "site_id"), on=["chrom", "position"])
        .with_columns(
            pl.when(pl.col("cov") > 0).then((pl.col("edited") / pl.col("cov")).round(5)).alias("level")
        )
        .pivot(on="sample", index="site_id", values="level")
    )
    return ed, levels


def chrom_order() -> pl.Expr:
    """1..19, X, Y, MT, others – numeric chromosomes in numeric order."""
    c = pl.col("chrom")
    return (
        pl.when(c.str.contains(r"^\d+$")).then(c.cast(pl.Int64, strict=False))
        .when(c == "X").then(100).when(c == "Y").then(101).when(c.is_in(["MT", "M"])).then(102)
        .otherwise(200)
    )


def gene_editing(editing: pl.DataFrame) -> pl.DataFrame:
    """Per-gene editing columns for `de` (Q4: precomputed), over the filtered sites."""
    return editing.group_by("gene_id").agg(
        pl.len().cast(pl.Int64).alias("n_edit_sites"),
        pl.col("delta").mean().round(5).alias("mean_delta"),
        pl.col("delta").abs().max().round(5).alias("max_abs_delta"),
        (pl.col("edited_wt").sum() / pl.col("cov_wt").sum()).round(5).alias("edit_wt"),
        (pl.col("edited_adar").sum() / pl.col("cov_adar").sum()).round(5).alias("edit_adar"),
    )


# ------------------------------------------------------------------------------------------------------ bundle.yaml
def bundle_yaml(n_genes: int, n_sites: int, n_samples: int, min_cov: int) -> dict:
    f, s, i, b = {"type": "float"}, {"type": "string"}, {"type": "int"}, {"type": "bool"}
    adar = "ADAR (ADAR2-deficient, as labelled in the data)"
    return {
        "id": "adar2-editing",
        "title": "ADAR2 mouse – RNA-seq and RNA editing (ADAR vs WT)",
        "description": (
            "Published mouse RNA-seq data: differential expression (DESeq2) and A-to-I RNA editing at known editing "
            f"sites, {n_samples} samples, {adar} vs WT. Editing levels are pooled over the samples of each "
            f"condition; {n_sites} sites in canonical exons of DE genes with >= {min_cov} reads in both conditions. "
            "Converted by scripts/convert_adar2.py (see docs/adar2-notes.md for the assumptions)."
        ),
        "organism": "Mus musculus",
        "genome": "GRCm38",
        "modalities": ["rna-seq", "rna-editing"],
        "contrast": {"name": "ADAR_vs_WT", "numerator": NUM, "denominator": DEN},
        "samples": "samples.tsv",
        "tables": {
            "de": {
                "file": "tables/de.parquet",
                "description": (
                    f"DESeq2 results ADAR vs WT, one row per gene ({n_genes} genes), with per-gene editing summaries "
                    "over the gene's editing sites"
                ),
                "key": "gene_id",
                "columns": {
                    "gene_id": {**s, "description": "Ensembl gene id"},
                    "gene_name": {**s, "description": "gene symbol (not unique for a few symbols)"},
                    "biotype": {**s, "description": "Ensembl gene biotype"},
                    "baseMean": {**f, "description": "mean of normalised counts over all samples"},
                    "log2FoldChange": {**f, "description": "log2 fold change, ADAR vs WT (> 0 = higher in ADAR)"},
                    "lfcSE": {**f, "description": "standard error of log2FoldChange"},
                    "stat": {**f, "description": "Wald statistic"},
                    "pvalue": {**f, "description": "Wald test p-value"},
                    "padj": {**f, "description": "BH-adjusted p-value (null = filtered out by DESeq2)"},
                    "n_edit_sites": {**i, "description": "number of editing sites of the gene in table editing (0 = none)"},
                    "mean_delta": {**f, "description": "mean editing change (edit_adar - edit_wt) over the gene's sites"},
                    "max_abs_delta": {**f, "description": "largest absolute editing change over the gene's sites"},
                    "edit_wt": {**f, "description": "gene-level editing level WT (0-1): edited reads / coverage over its sites"},
                    "edit_adar": {**f, "description": "gene-level editing level ADAR (0-1): edited reads / coverage over its sites"},
                },
            },
            "counts": {
                "file": "tables/counts.parquet",
                "description": "DESeq2 normalised counts, genes x samples (matrix table)",
                "key": "gene_id",
                "columns": {"gene_id": {**s, "description": "Ensembl gene id"}},
            },
            "editing": {
                "file": "tables/editing.parquet",
                "description": (
                    f"A-to-I editing per site, one row per site ({n_sites} sites), pooled reads per condition, "
                    "ADAR vs WT"
                ),
                "key": "site_id",
                "columns": {
                    "site_id": {**s, "description": "chrom:position (GRCm38)"},
                    "gene_id": {**s, "description": "Ensembl gene id of the gene the site lies in (links to de)"},
                    "gene_name": {**s, "description": "gene symbol"},
                    "gene_names": {**s, "description": "all gene symbols at this site (overlapping genes)"},
                    "chrom": {**s, "description": "chromosome (GRCm38)"},
                    "position": {**i, "description": "1-based position (GRCm38)"},
                    "exon_number": {**i, "description": "exon number in the gene's canonical transcript"},
                    "strand": {**s, "description": "strand from the known-sites database (null if not listed)"},
                    "region": {**s, "description": (
                        "sequence region from the known-sites database: exon, intron or the database's own code "
                        "(e.g. O); null if not listed"
                    )},
                    "known_db": {**b, "description": "site is listed in the known mouse editing sites database (mm10.txt)"},
                    "cov_wt": {**i, "description": "reads covering the site, summed over WT samples"},
                    "cov_adar": {**i, "description": "reads covering the site, summed over ADAR samples"},
                    "edited_wt": {**i, "description": "edited (G) reads, summed over WT samples"},
                    "edited_adar": {**i, "description": "edited (G) reads, summed over ADAR samples"},
                    "edit_wt": {**f, "description": "editing level WT (0-1) = edited_wt / cov_wt"},
                    "edit_adar": {**f, "description": "editing level ADAR (0-1) = edited_adar / cov_adar"},
                    "delta": {**f, "description": "editing change edit_adar - edit_wt (ADAR vs WT)"},
                    "high_confidence": {**b, "description": f"more than {HIGH_CONFIDENCE_MIN_EDITED} edited reads over all samples"},
                    "n_samples_covered": {**i, "description": f"samples with coverage > 0 (of {n_samples})"},
                },
            },
            "editing_levels": {
                "file": "tables/editing_levels.parquet",
                "description": "editing level (0-1) per site and sample, null when the sample has no coverage (matrix table)",
                "key": "site_id",
                "columns": {"site_id": {**s, "description": "chrom:position (GRCm38), links to editing"}},
            },
        },
        "links": [
            {"from": "editing.gene_id", "to": "de.gene_id"},
            {"from": "counts.gene_id", "to": "de.gene_id"},
            {"from": "editing_levels.site_id", "to": "editing.site_id"},
        ],
    }


# ------------------------------------------------------------------------------------------------------------- main
def main() -> None:
    data = default_data_dir()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", type=Path, default=data.parent / "raw" / "adar2-editing", help="raw folder (default: %(default)s)")
    ap.add_argument("--out", type=Path, default=data / "adar2-editing", help="bundle folder (default: %(default)s)")
    ap.add_argument("--min-cov", type=int, default=10, help="pooled coverage needed in each condition (default: 10)")
    args = ap.parse_args()
    raw, out = args.raw, args.out
    if not (raw / "input_files").is_dir():
        raise SystemExit(f"raw folder not found: {raw}")

    log(f"reading {raw}")
    samples = read_samples(raw)
    names = list(samples["sample"])
    de, counts = read_de(raw, names)
    sites = read_site_annotation(raw, de)
    long = read_site_counts(raw, samples, sites)
    editing, levels = summarise_sites(sites, long, read_known_db(raw), args.min_cov)
    levels = levels.select("site_id", *[s for s in names if s in levels.columns])

    de = de.join(gene_editing(editing), on="gene_id", how="left").with_columns(pl.col("n_edit_sites").fill_null(0))
    assert de["gene_id"].is_unique().all() and editing["site_id"].is_unique().all()
    assert editing["gene_id"].is_in(de["gene_id"].implode()).all(), "every site must link to a DE gene"

    (out / "tables").mkdir(parents=True, exist_ok=True)
    de.write_parquet(out / "tables" / "de.parquet")
    counts.write_parquet(out / "tables" / "counts.parquet")
    editing.write_parquet(out / "tables" / "editing.parquet")
    levels.write_parquet(out / "tables" / "editing_levels.parquet")
    samples.write_csv(out / "samples.tsv", separator="\t")
    with open(out / "bundle.yaml", "w") as fh:
        yaml.safe_dump(bundle_yaml(de.height, editing.height, len(names), args.min_cov), fh, sort_keys=False, allow_unicode=True)

    n_genes_ed = int((de["n_edit_sites"] > 0).sum())
    print(
        f"wrote {out}: {de.height} genes ({n_genes_ed} with editing sites), {editing.height} sites "
        f"({int(editing['high_confidence'].sum())} high-confidence, {int((editing['delta'].abs() > 0.1).sum())} "
        f"with |delta| > 0.1), {len(names)} samples; pooled editing WT "
        f"{editing['edited_wt'].sum() / editing['cov_wt'].sum():.3f}, ADAR "
        f"{editing['edited_adar'].sum() / editing['cov_adar'].sum():.3f}"
    )


if __name__ == "__main__":
    main()
