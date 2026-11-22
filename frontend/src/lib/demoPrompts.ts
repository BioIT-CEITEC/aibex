/**
 * The six demo prompts from docs/roadmap.md, in demo order (T52). They are prompt texts for the live demo on the ADAR2
 * bundle (prompts 4 and 5 need its editing modality), not column names the UI reads data with.
 */
export const DEMO_PROMPTS: readonly string[] = [
  'Label the 10 most significant genes in the volcano plot.',
  'Only show genes with padj < 0.01 and |log2FC| > 1 everywhere.',
  'Add a heatmap of the top 30 genes, samples grouped by genotype.',
  'Colour genes in the volcano by their editing change.',
  'For the selected gene, show its editing sites along the transcript.',
  'Undo the last two changes.',
];
