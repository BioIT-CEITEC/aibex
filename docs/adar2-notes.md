# ADAR2 use case – raw data notes and planned bundle

Written in T30 (overnight 2026-11-22) from a read-only inspection of `raw/adar2-editing` (the folder next to
`AIBEX_DATA_DIR`). **For Vojta to confirm in T33** – every assumption is marked *(A#)*, open questions *(Q#)*.
No raw files were copied; numbers below were computed on the fly with polars.

## 1. What is in `raw/adar2-editing`

| Path | Size | Used by the converter? |
|---|---|---|
| `input_files/ADAR_vs_WT_DESeq2.tsv` | 15.5 MB, 33 513 genes | **yes** → `de` + `counts` (byte-identical to `DE_RSEM/ADAR_vs_WT/DESeq2.tsv`) |
| `input_files/DE_experiment_design.tsv` | 356 B, 19 samples | **yes** → `samples.tsv` (identical to `DE_RSEM/DE_experiment_design.tsv`) |
| `input_files/editing_analysis/known_editing_sites/*.known_editing_sites_AF.tsv` | 20 files × 2.4 MB, 108 280 positions each | **yes** → per-site counts of `editing` |
| `val_editing_sites_table.xlsx` | 0.5 MB, 4 451 rows | **yes**, only for the gene annotation of sites (`gene_name`, `exon_number`) – the GTF used by the R code is not here |
| `custom_scripts/mm10.txt` | 300 KB, 8 340 known mouse editing sites (RADAR-style: strand, gene, region, PubMed) | optional → `strand`, `known_db`, `region` for the 1 332 sites it covers |
| `val_editing_sites_table_filtered.xlsx` | 96 KB, 512 rows | cross-check only (sites with > 100 edited reads) |
| `editing_summary.xlsx` | 12 KB, 4 sheets | cross-check only (per-sample / per-condition editing ratio) |
| `input_files/DE_RSEM/<contrast>/…` | 7 contrasts, DESeq2 + edgeR tables, PDFs/PNGs/SVGs, PCA | no (other contrasts out of scope, Q10); `detail_results/DESeq2_experiment_design.tsv` read for colours only |
| `input_files/DE_RSEM/complete_RSEM_table.RData` | 6.2 MB | no – normalised and raw counts are already columns of `DESeq2.tsv` |
| `input_files/Alu.bed` | 207 MB | no – only used by the cluster part of the R code (see 2.3) |
| `input_files/multiqc_star.txt` | 4 KB | no (only in commented-out R code) |
| `input_files/mapped/` | empty | – (BAMs not provided; not needed) |
| `custom_scripts/*.R` | R code | read, see section 2 |
| `~$*.xlsx` | Excel lock files | ignored |

## 2. What the R code does (`custom_scripts/proces_all_samples_editing_new.R`)

`proces_all_samples_editing.R` is an older version of the same script (different paths, an older experiment with
`ADAR2_KO`/`A2G` contrasts). `rna_editing_bam_get_edit_region_new.R` detects editing clusters from BAMs – not usable
without BAMs and not needed.

### 2.1 Known editing sites (the part that produced the xlsx files)
1. Reads every `*.known_editing_sites_AF.tsv` (columns `#CHR POS Count_A Count_C Count_G Count_T Good_depth`).
   Per sample and site: **`edit_count = Count_C + Count_G`** (A→G read as G on + strand genes, as C on − strand genes;
   strand-agnostic), **`cov = Good_depth`**.
2. Overlaps sites with the exons of one canonical transcript per gene (GTF GRCm38.p6-93, chr 1–19, X, Y) → `gene_id`,
   `gene_name`, `exon_number`. A site in two overlapping genes yields two rows.
3. Inner-joins with the DESeq2 normalised counts by `(sample, gene_id)` → only sites in genes of the DE table, and only
   the 19 samples of the design (**`PER01RE` is dropped** – a re-sequenced PER01, not in the design).
4. `edit_ratio = edit_count / cov` (0 when `cov = 0`), `sum_edit_counts` / `sum_cov` = sums over all 19 samples.
5. `val_editing_sites_table.xlsx` = sites with **`sum_edit_counts > 0`** (4 451 rows = 4 372 unique sites; 79 sites
   overlap two genes); `…_filtered.xlsx` = **`sum_edit_counts > 100`** (512 rows).
6. `editing_summary.xlsx`: pooled `sum(edit)/sum(cov)` per sample / condition / tissue group over the `> 100` sites.
   Global editing is **lower in ADAR than in WT**: 0.177 vs 0.238 (both PER and PL groups).

### 2.2 Reproduction check (raw TSVs vs xlsx)
Recomputing step 1 + 4 from the raw TSVs reproduces `sum_cov` and `sum_edit_counts` of the xlsx exactly for every site,
except the sites listed under two (or three) genes: R sums them after the gene join, so their sums are doubled/tripled
(157 rows), plus 2 `Sept2` sites listed once but with doubled sums (probably two overlapping exon records of the
same gene). The converter will compute sums per unique site
(no double counting). Of 55 146 raw positions with any edited read, only 4 372 fall into canonical exons of DE genes.

### 2.3 Not reproducible / not needed
The second half of `run_all()` (editing clusters, Alu overlap, per-gene `cluster_edits_per_10000_reads`) reads
`RNA_editing_analysis/*.editing_clusters.tsv` and `*.mismatch_tab.tsv`, which are not in the folder, and refers to old
contrast names (`ADAR2_KO_vs_WT_pval`, …) that no longer exist – this part would fail as written. Not used.

## 3. Samples and contrast
- 19 samples: **10 WT, 9 ADAR**; two groups by name prefix, `PER` (PER01–PER13, 9 samples: 5 WT, 4 ADAR) and `PL`
  (PL43–PL67, 10 samples: 5 WT, 5 ADAR). The R code calls the prefix `condition2`.
- DE contrast (Q10): DESeq2 `condition ADAR vs WT` (log2FC > 0 = higher in ADAR). 2 870 genes with `padj < 0.05`;
  14 400 genes have `padj = NA` (independent filtering); the `significant_DE` column is TRUE for only 6 genes (it also
  needs a large |log2FC|).
- *(A1)* Editing uses the **same comparison**: numerator = the 9 ADAR samples, denominator = the 10 WT samples, both
  groups (PER + PL) pooled, as in `summary_ADAR_WT`.
- *(Q-a)* What do `ADAR` and `WT` mean biologically? Editing is ~25 % lower in `ADAR` and the docs say "ADAR2-KO", so
  I assume `ADAR` = the ADAR2-deficient genotype. The bundle will use the labels as they are in the data (`ADAR`, `WT`)
  and describe `ADAR` as "ADAR2-deficient (as labelled in the data)" until you confirm. Contrast in `bundle.yaml`:
  `{name: ADAR_vs_WT, numerator: ADAR, denominator: WT}`.
- *(Q-b)* What are `PER` and `PL` (tissue? cohort/batch?)? Planned as a neutral `group` column in `samples.tsv`.

## 4. Planned bundle (`$AIBEX_DATA_DIR/adar2-editing/`, T31)

`scripts/convert_adar2.py` (PEP 723 inline deps: polars, fastexcel for the xlsx annotation, pyyaml; lazy scans for the
TSVs – the inputs are small, ~65 MB in total). Usage: `uv run scripts/convert_adar2.py --raw <raw/adar2-editing>`.

### `samples.tsv`
`sample, genotype (ADAR|WT), group (PER|PL), replicate` – 19 rows, order WT then ADAR. Column named `genotype` so demo
prompt 3 ("grouped by genotype") works literally.

### `de` (key `gene_id`, 33 513 rows)
From `ADAR_vs_WT_DESeq2.tsv`: `gene_id` (= `Ensembl_Id`), `gene_name`, `biotype`, `baseMean`, `log2FoldChange`,
`lfcSE`, `stat`, `pvalue`, `padj`.
- *(A2)* `gene_name` = `Feature_name` with the `__ENSMUSG…` suffix removed (the pipeline appends the id to duplicated
  symbols, e.g. `Zkscan7__ENSMUSG00000063488`; 91 rows); the cleaned name is then not unique (37 symbols on 76 rows)
  – fine, the key is `gene_id`.
- Precomputed editing columns (Q4), over the **filtered sites** of the gene (see `editing`):
  `n_edit_sites` (int, 0 when none), `mean_delta` (mean of site `delta`, null when none), `max_abs_delta`
  (largest |delta|, null when none), `edit_wt`, `edit_adar` (pooled gene-level ratios, sum of edited reads / sum of
  coverage over the gene's sites, null when none).
- Dropped: `significant_DE` (misleading, see 3), the 38 per-sample count columns (→ `counts`).

### `counts` (matrix table, key `gene_id`)
`gene_id` + 19 columns of **DESeq2 normalised counts** (`<sample>_normCounts` renamed to `<sample>`), all 33 513 genes.
PCA/heatmap panels apply `log1p` themselves. *(A3)* normCounts of the ADAR_vs_WT run, not RSEM TPM.

### `editing` (key `site_id`, ≈ 4 000 rows)
Site set *(A4)*: the sites of `val_editing_sites_table.xlsx` (R: any edited read in the 19 samples, in a canonical exon
of a DE gene) **and** pooled coverage ≥ 10 reads in both ADAR and WT → **4 024 sites** (≥ 20: 3 799; ≥ 50: 3 270).
This matches the "~4000 realistically edited sites" (Q7). The R `> 100 edited reads` set (≈ 500 sites) is kept as a
boolean column instead of a second filter.

| column | type | definition |
|---|---|---|
| `site_id` | string | `chr:pos`, e.g. `1:13625015` |
| `gene_id` | string | Ensembl id via `gene_name` → DE table; *(A5)* a site in several genes is assigned to the gene with the highest `baseMean`, all names kept in `gene_names` |
| `gene_name`, `gene_names` | string | symbol(s) from the xlsx |
| `chrom`, `position` | string, int | GRCm38, 1-based (matches `mm10.txt` coordinates) |
| `exon_number` | int | canonical-transcript exon from the xlsx |
| `strand`, `region`, `known_db` | string, string, bool | from `mm10.txt` where the site is listed (1 332 of 4 372 sites), else null / false |
| `cov_wt`, `cov_adar`, `edited_wt`, `edited_adar` | int | summed reads per condition |
| `edit_wt`, `edit_adar` | float | pooled editing level 0–1 = `edited / cov` per condition *(A6: pooled, like the R summaries, not the mean of per-sample ratios)* |
| `delta` | float | `edit_adar − edit_wt` (ADAR vs WT, same direction as log2FC) |
| `high_confidence` | bool | R filter `sum_edit_counts > 100` over all 19 samples |
| `n_samples_covered` | int | samples with coverage > 0 (of 19) |

Distribution on the 4 372 sites (before the coverage filter): median `edit_wt` 0.056, median `edit_adar` 0.024,
median `delta` −0.006 (IQR −0.062 … 0.008); 720 of the 4 024 filtered sites have |delta| > 0.1.

Optional (decide in T31/T42): `editing_levels` matrix table (key `site_id`, one column per sample = per-sample
`edit_count / cov`, null when `cov = 0`) for a heatmap of sites × samples and for the Level-2 "sites along the
transcript" widget (demo prompt 5). Small (4 024 × 19).

### `bundle.yaml`
`id: adar2-editing`, `organism: Mus musculus`, `genome: GRCm38`, `modalities: [rna-seq, rna-editing]`,
`contrast: {name: ADAR_vs_WT, numerator: ADAR, denominator: WT}`, `links: [{from: editing.gene_id, to: de.gene_id},
{from: counts.gene_id, to: de.gene_id}]`, descriptions for every table and column.

## 5. Example rows (raw, a few lines only)

`known_editing_sites/PER01.known_editing_sites_AF.tsv`
```
#CHR  POS      Count_A  Count_C  Count_G  Count_T  Good_depth
1     3253303  0        0        0        0        0
```
`val_editing_sites_table_filtered.xlsx` (cells are `percent (edited/coverage)`)
```
chr  pos       gene_name  exon_number  sum_cov  sum_edit_counts  PER ADAR rep01  …  PER WT rep01  …
1    13625741  Lactb2     7            381      176              16.7 (4/24)     …  76.9 (20/26)  …
```
`ADAR_vs_WT_DESeq2.tsv` (first columns)
```
Ensembl_Id          baseMean  log2FoldChange  lfcSE  pvalue    padj      significant_DE  Feature_name  biotype
ENSMUSG00000085666  237.4     4.35            0.110  8.4e-204  1.6e-199  TRUE            Gm9855        processed_pseudogene
```

## 6. Converter result (T31)
`scripts/convert_adar2.py` implements section 4 as planned (defaults derive `--raw`/`--out` from
`$AIBEX_DATA_DIR`; the script does not read `.env`, so pass the paths or export the variable). Result: 33 513 genes,
1 184 of them with editing sites; **4 024 sites** (485 `high_confidence`, 719 with |delta| > 0.1); 1 225 sites listed
in `mm10.txt`; pooled editing over the 4 024 sites WT 0.109, ADAR 0.079. All xlsx symbols map to a DE gene. Sanity
check: the Gria2 Q/R site (`3:80706912`) has `edit_wt` 0.99 and `edit_adar` 0.15, which supports Q-a (ADAR =
ADAR2-deficient). Details beyond the plan:
- `editing_levels` (matrix table, site × sample, null when a sample has no coverage) is included, linked
  `editing_levels.site_id → editing.site_id`.
- A symbol that is on several DE rows maps to the row with the highest `baseMean` (same rule as A5).
- `region` = `seqReg` of `mm10.txt` with `E`/`I` written as `exon`/`intron`; other codes (e.g. `O`) are kept as they
  are.
- `samples.tsv` order: WT then ADAR, each by group and sample. Column order of `counts`/`editing_levels` follows it.

## 6b. Default view (T32)
The converter also writes `views/default.json` (named by `default_view` in `bundle.yaml`; the backend uses it only if
it validates, else it serves the generated view). Dataset column names stay in the converter, not in the app.
Panels: `volcano` (de, first plot, empty `label` for demo prompts 1/4), `editing-vs-expression` (per site: gene
log2FC vs editing Δ, coloured by gene DE), `editing-levels` (per site: editing WT vs ADAR with a diagonal, coloured by
`high_confidence`), `pca` (counts, by genotype), `edited-genes` (de sorted by `n_edit_sites` = sites per gene),
`editing-sites` (sorted by `delta`, strongest loss first). No heatmap on purpose (demo prompt 3 adds one).
`selection: gene_id, linked` – the editing plots return `gene_id` too (docs/api.md, panel data), so selecting a gene in
any panel highlights its sites. To draw per-site plots without a join, `editing` carries `gene_log2fc` and `gene_padj`
(copied from `de`).
Visual check on the real data (opt-in e2e, data stay outside the repo):
`make e2e E2E_REAL_DATA=<AIBEX_DATA_DIR>` runs only `frontend/e2e/real-*.spec.ts` and writes
`logs/screens/T32-adar2-*.png`.

## 7. Questions for Vojta (T33) – answered 2026-11-22
Source for Q-a/Q-b: the submitted manuscript Lacovich et al. (in the raw folder, not in git).
- **Q-a – answered:** `ADAR` = *Adarb1* (ADAR2) knockout/mutant mice; `WT` = wild-type littermates (C57BL/6N). Samples
  are P14 pup brains (one hemisphere; RNA-seq on the same animals as the proteomics). UI wording: **"ADAR2-KO vs WT"**;
  keep the data value `ADAR` in the tables, describe it as "ADAR2 knockout (Adarb1 mutant)".
- **Q-b – answered:** the prefix is the **treatment** of the dams/pups (pre- and postnatal, oral): `PER` = perampanel
  (AMPA receptor antagonist), `PL` = placebo/vehicle (70 % sorbitol; "PLAC" in the paper). The design is genotype ×
  treatment (PER: 5 WT + 4 ADAR, PL: 5 WT + 5 ADAR). The ADAR vs WT contrast stays pooled over both treatments, as in
  the R code. Rename `samples.tsv` column `group` → `treatment` with values `perampanel` / `placebo` (keep the
  `PER`/`PL` prefix in sample names), and offer treatment as a colour/facet option (e.g. PCA, editing levels) – T35.
- **Q-c – confirmed:** keep the 4 024 sites as the main `editing` table; `high_confidence` stays a filterable column.
- **Q-d – confirmed:** `delta` = pooled ratio difference.
- **Q-e – confirmed:** a site in overlapping genes goes to the gene with the higher `baseMean`.
