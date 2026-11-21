# Results bundle format (v1)

A results bundle is a folder with the outputs of an analysis, described well enough that
Aibex View (and the LLM, through tools) can use it without dataset-specific code.

```
<bundle-id>/
  bundle.yaml          description (required)
  samples.tsv          sample sheet (optional but recommended)
  tables/
    de.parquet         any number of tables; parquet preferred, tsv/csv accepted
    editing.parquet
    counts.parquet
```

## bundle.yaml

```yaml
id: adar2-editing
title: ADAR2-KO mouse – RNA-seq and RNA editing
description: >
  Differential expression and A-to-I editing in ADAR2 knockout vs wild type mice.
organism: Mus musculus
genome: GRCm38            # mm10; informative only – the app never needs the genome
modalities: [rna-seq, rna-editing]
contrast: {name: KO_vs_WT, numerator: KO, denominator: WT}
samples: samples.tsv
tables:
  de:
    file: tables/de.parquet
    description: DESeq2 results, one row per gene
    key: gene_id
    columns:
      gene_id:        {type: string, description: Ensembl gene id}
      gene_name:      {type: string, description: gene symbol}
      baseMean:       {type: float}
      log2FoldChange: {type: float, description: KO vs WT}
      padj:           {type: float, description: BH-adjusted p-value}
  editing:
    file: tables/editing.parquet
    description: editing levels per site and condition, one row per site
    key: site_id
    columns:
      site_id:   {type: string}
      gene_id:   {type: string}
      chrom:     {type: string}
      position:  {type: int}
      edit_wt:   {type: float, description: mean editing level WT (0-1)}
      edit_ko:   {type: float, description: mean editing level KO (0-1)}
      delta:     {type: float, description: edit_ko - edit_wt}
links:
  - {from: editing.gene_id, to: de.gene_id}     # enables linked selection across modalities
default_view: views/default.json                 # optional starting spec
```

## samples.tsv
Tab-separated, first column `sample` (sample names exactly as the matrix column names), further columns are sample
annotations (e.g. `genotype`, `batch`). Used for PCA colours and heatmap grouping.

## Rules
- Column names in tables must match `bundle.yaml`. Unknown extra columns are allowed and exposed with type inferred.
- Column `type` vocabulary: `string`, `int`, `float`, `bool`, `date`. Inferred types are mapped to the same vocabulary.
- A **matrix table** (e.g. normalised counts) is wide: the key column (e.g. `gene_id`) plus one numeric column per sample,
  named as in `samples.tsv`. Such tables need not declare the sample columns; they are used by `pca` and `heatmap` panels.
- `key` columns must be unique within a table.
- `links` declare joinable keys; the backend creates DuckDB views so the LLM can join modalities.
- Bundle data files are **never** committed (size; unpublished data in future projects). Locally they live under `data/` or `AIBEX_DATA_DIR`;
  on the cluster on the PVC mounted at `/data`.
- A converter script per source format lives in `scripts/` (e.g. `scripts/convert_adar2.py`). Converters precompute
  everything the views need (summaries, per-gene aggregates, filtered site lists); the app only reads result tables.
- `views/` inside the bundle holds `default.json` (optional) and the saved views written by the app (`views/<name>.json`).
