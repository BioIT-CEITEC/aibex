"""Unit tests for the restricted `expr` grammar (T13b, docs/api.md "Spec validation rules", Q1)."""

from __future__ import annotations

import duckdb
import pytest

from aibex.expr import ExprError, compile_expr, tokenize

COLS = ["gene_name", "log2FoldChange", "padj", "baseMean", "KO 1"]


@pytest.mark.parametrize(
    ("expr", "used"),
    [
        ("-log10(padj)", ["padj"]),
        ("abs(log2FoldChange) > 1", ["log2FoldChange"]),
        ("abs(log2FoldChange) > 1 OR NOT padj >= 0.01", ["log2FoldChange", "padj"]),
        ("CASE WHEN padj < 0.05 AND abs(log2FoldChange) > 1 THEN 'sig' ELSE 'ns' END", ["padj", "log2FoldChange"]),
        ("case when padj < 0.05 then 'up' when padj < 0.1 then 'maybe' end", ["padj"]),
        ("padj IS NULL", ["padj"]),
        ("padj is not null and gene_name <> 'Gria2'", ["padj", "gene_name"]),
        ("gene_name = 'it''s'", ["gene_name"]),
        ("log2(baseMean + 1) * 2 - 1 / 3", ["baseMean"]),
        ("round(least(padj, 1), 3) != greatest(0, coalesce(padj, 1))", ["padj"]),
        ('"KO 1" / 2', ["KO 1"]),
        ("ln(sqrt(baseMean)) <= log(baseMean)", ["baseMean"]),
        ("TRUE", []),
        ("1.5e-3 < padj", ["padj"]),
        ("-(-padj)", ["padj"]),
    ],
)
def test_accepts_grammar(expr, used):
    c = compile_expr(expr, COLS)
    assert c.columns == used


@pytest.mark.parametrize(
    "expr",
    [
        "(SELECT 1)",
        "padj < (SELECT max(padj) FROM de)",
        "read_csv('x')",
        "CASE WHEN read_csv('x') THEN 1 END",
        "padj; DROP TABLE de",
        "padj::int",
        "CAST(padj AS int)",
        "padj -- comment",
        "padj /* c */",
        "upper(gene_name)",
        "gene_name LIKE 'G%'",
        "padj IN (1, 2)",
        "padj BETWEEN 0 AND 1",
        "padj == 1",
        "padj <",
        "(padj",
        "abs()",
        "CASE padj WHEN 1 THEN 2 END",
        "CASE WHEN padj < 1 THEN 2",
        "",
        "   ",
        "padj padj",
        "de.padj",
        "$1",
        "getenv('HOME')",
        "x" * 3000,
        "(" * 100 + "padj" + ")" * 100,
    ],
)
def test_rejects_outside_grammar(expr):
    with pytest.raises(ExprError):
        compile_expr(expr, COLS)


def test_unknown_column_named_in_error():
    with pytest.raises(ExprError, match="secret_col"):
        compile_expr("-log10(secret_col)", COLS)


def test_columns_matched_case_insensitively_and_canonicalised():
    c = compile_expr("abs(LOG2FOLDCHANGE) > 1", COLS)
    assert c.columns == ["log2FoldChange"]
    assert '"log2FoldChange"' in c.sql


def test_no_column_list_accepts_any_column():
    assert compile_expr("foo + bar").columns == ["foo", "bar"]


def test_compiled_sql_is_normalised_and_runs_in_duckdb():
    con = duckdb.connect()
    con.execute("CREATE TABLE de AS SELECT 'it''s' AS gene_name, 2.0 AS log2FoldChange, 0.01 AS padj, "
                "10.0 AS baseMean, 3 AS \"KO 1\"")
    for expr in [
        "CASE WHEN padj < 0.05 AND abs(log2FoldChange) > 1 THEN 'sig' ELSE 'ns' END",
        "-log10(padj)",
        "gene_name = 'it''s'",
        '"KO 1" / 2',
    ]:
        sql = compile_expr(expr, COLS).sql
        con.execute(f"SELECT {sql} FROM de").fetchall()
    assert con.execute(f"SELECT {compile_expr('-log10(padj)', COLS).sql} FROM de").fetchone()[0] == pytest.approx(2)
    assert con.execute(f"SELECT {compile_expr(chr(39) + 'a' + chr(39), COLS).sql}").fetchone()[0] == "a"


def test_tokenize_keywords_upper():
    kinds = [(t.kind, t.text) for t in tokenize("not padj is null")]
    assert kinds[0] == ("kw", "NOT") and kinds[2] == ("kw", "IS")
