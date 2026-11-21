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
genome: GRCm39            # (?) fill in the real build
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

## Rules
- Column names in tables must match `bundle.yaml`. Unknown extra columns are allowed and exposed with type inferred.
- `key` columns must be unique within a table.
- `links` declare joinable keys; the backend creates DuckDB views so the LLM can join modalities.
- Bundles with real/unpublished data are **never** committed. Locally they live under `data/` or `AIBEX_DATA_DIR`;
  on the cluster on the PVC mounted at `/data`.
- A converter script per source format lives in `scripts/` (e.g. `scripts/convert_adar2.py`).
