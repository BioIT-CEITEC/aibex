# AIBEX – vision

**AIBEX – Assistant for Integrated Bioinformatics EXecution.** *You are the expert. Aibex is your assistant.*

Generic AI chat tools can write code and explain results, but bioinformatics work also needs access to
data and compute, the ability to work with sensitive data, and the experience of people who have done
the analysis before. AIBEX aims to bring these together in one assistant for bioinformaticians, and
through them for molecular and clinical biologists.

## Stages (users move back and forth between them)
1. **Intake** – what analysis do you want, what data do you have?
2. **Resources** – find and connect public and private data and their metadata; suggest where data and results should live.
3. **Compute** – suggest where to run (e.g. Kubernetes / national e-infrastructure), launch workflows (Snakemake, Nextflow), monitor and check runs.
4. **Analysis and meta-analysis** – primary analysis, statistics, combining results across modalities and studies.
5. **View** – an interactive dashboard of the results that biologists can change by prompting (**Aibex View**).

## Principles
- **Assistant, not oracle.** Human in the loop at every stage; expert knowledge steers the analysis.
- **Your infrastructure, your models.** Works with self-hosted open-weight models (slower, fine for long-running and sensitive work) and commercial models (fast, for interactive work).
- **Sensitive data stay put.** Only partial / aggregate results leave the secure environment (TRE, federated analysis).
- **Guardrails, not freestyle.** Preset formats (view spec, results bundles), validated changes, undo, and audit trail.
- **Framework.** A new viewer for a new analysis should be generated quickly from the same building blocks.

## Now
The first working piece is **Aibex View**. The other stages will be shown as a clickable mock first.
