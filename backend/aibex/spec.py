"""Pydantic models of the view spec (docs/spec-format.md) + structural validation.

Structural checks only (T13a): field types, allowed enum values, `field` xor `expr`, kebab-case unique ids,
layout <-> panels, plain-JSON `plotly` overrides. Checks against the bundle schema, the `expr` grammar and widget
code/SQL are semantic and live in aibex/validate.py (`validate_spec` runs both).

Models forbid unknown fields so a typo in an LLM patch ("colour", "lable") becomes a validation error the LLM can
repair, instead of being silently ignored.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
GRID_COLUMNS = 12

PlotKind = Literal["scatter", "bar", "box", "violin", "histogram", "heatmap", "line", "pca"]
FilterOp = Literal["<=", ">=", "<", ">", "==", "!=", "in", "between", "contains"]
MATRIX_KINDS = ("pca", "heatmap")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_kebab(value: str, what: str) -> str:
    if not KEBAB_RE.match(value):
        raise ValueError(f"{what} {value!r} must be kebab-case (lowercase letters, digits and single dashes)")
    return value


def _field_xor_expr(obj: Any, what: str) -> None:
    if (obj.field is None) == (obj.expr is None):
        raise ValueError(f"{what} needs exactly one of 'field' or 'expr'")


def check_plain_json(value: Any, path: str = "plotly") -> None:
    """Raise ValueError unless `value` is plain JSON (dict/list/str/finite number/bool/None)."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: numbers must be finite")
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            check_plain_json(v, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"{path}: object keys must be strings")  # noqa: TRY004 (pydantic needs ValueError)
            check_plain_json(v, f"{path}.{k}")
        return
    raise ValueError(f"{path}: {type(value).__name__} is not plain JSON")


# ---------------------------------------------------------------- encodings


class Axis(_Model):
    field: str | None = None
    expr: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Axis:
        _field_xor_expr(self, "axis")
        return self


class Color(_Model):
    field: str | None = None
    expr: str | None = None
    label: str | None = None
    palette: dict[str, str] | None = None
    colorscale: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Color:
        _field_xor_expr(self, "color")
        if self.palette is not None and self.colorscale is not None:
            raise ValueError("color takes either 'palette' (categorical) or 'colorscale' (continuous), not both")
        return self


class Size(_Model):
    field: str | None = None
    expr: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Size:
        _field_xor_expr(self, "size")
        return self


class Label(_Model):
    field: str
    values: list[str] = Field(default_factory=list)
    top_n: int | None = Field(default=None, ge=0, le=200)
    by: str | None = None

    @model_validator(mode="after")
    def _top_n_needs_by(self) -> Label:
        if self.top_n and not self.by:
            raise ValueError("label.top_n needs 'by' (the column to rank by)")
        return self


class HeatmapRows(_Model):
    top_n: int | None = Field(default=None, ge=1, le=500)
    by: str | None = None
    values: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> HeatmapRows:
        if self.top_n is not None and not self.by:
            raise ValueError("rows.top_n needs 'by' (<table>.<column>)")
        if self.by is not None and self.by.count(".") != 1:
            raise ValueError("rows.by must be '<table>.<column>'")
        if self.top_n is None and not self.values:
            raise ValueError("rows needs explicit 'values' or 'top_n' + 'by'")
        return self


# ---------------------------------------------------------------- panels


class _PanelBase(_Model):
    id: str
    title: str = ""
    description: str | None = None

    @field_validator("id")
    @classmethod
    def _kebab(cls, v: str) -> str:
        return _check_kebab(v, "panel id")


class PlotPanel(_PanelBase):
    type: Literal["plot"]
    table: str
    kind: PlotKind
    x: Axis | None = None
    y: Axis | None = None
    color: Color | None = None
    size: Size | None = None
    label: Label | None = None
    facet: str | None = None
    plotly: dict[str, Any] = Field(default_factory=dict)
    # pca / heatmap
    top_n: int | None = Field(default=None, ge=2, le=50000)
    scale: Literal["none", "log1p", "row-z"] | None = None
    rows: HeatmapRows | None = None
    group_by: str | None = None

    @field_validator("plotly")
    @classmethod
    def _plain_json(cls, v: dict[str, Any]) -> dict[str, Any]:
        check_plain_json(v)
        return v

    @model_validator(mode="after")
    def _per_kind(self) -> PlotPanel:
        if self.kind == "pca":
            if self.scale == "row-z":
                raise ValueError("pca scale must be 'none' or 'log1p'")
            if self.color is not None and self.color.field is None:
                raise ValueError("pca color must be {'field': <samples.tsv column>}")
            extra = [n for n in ("x", "y", "size", "label", "rows", "group_by") if getattr(self, n) is not None]
            if extra:
                raise ValueError(f"pca panels do not use {', '.join(extra)}")
        elif self.kind == "heatmap":
            if self.rows is None:
                raise ValueError("heatmap panels need 'rows'")
            extra = [n for n in ("x", "y", "size", "label", "top_n") if getattr(self, n) is not None]
            if extra:
                raise ValueError(f"heatmap panels do not use {', '.join(extra)}")
        else:
            if self.x is None and self.y is None:
                raise ValueError(f"{self.kind} plots need 'x' and/or 'y'")
            extra = [n for n in ("top_n", "scale", "rows", "group_by") if getattr(self, n) is not None]
            if extra:
                raise ValueError(f"{', '.join(extra)} only apply to pca/heatmap plots")
        return self


class SortKey(_Model):
    field: str
    dir: Literal["asc", "desc"] = "asc"


class TablePanel(_PanelBase):
    type: Literal["table"]
    table: str
    columns: list[str] | None = None  # None = all columns
    sort: list[SortKey] = Field(default_factory=list)
    page_size: int = Field(default=25, ge=1, le=500)

    @field_validator("columns")
    @classmethod
    def _unique_columns(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            if not v:
                raise ValueError("columns must not be empty (omit it to show all columns)")
            if len(set(v)) != len(v):
                raise ValueError("columns must be unique")
        return v


class TextPanel(_PanelBase):
    type: Literal["text"]
    markdown: str = ""


class WidgetInput(_Model):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    sql: str


class WidgetPanel(_PanelBase):
    type: Literal["widget"]
    inputs: list[WidgetInput] = Field(default_factory=list)
    code: str
    language: Literal["tsx", "jsx"] = "tsx"

    @field_validator("inputs")
    @classmethod
    def _unique_inputs(cls, v: list[WidgetInput]) -> list[WidgetInput]:
        names = [i.name for i in v]
        if len(set(names)) != len(names):
            raise ValueError("widget input names must be unique")
        return v


Panel = Annotated[PlotPanel | TablePanel | TextPanel | WidgetPanel, Field(discriminator="type")]


# ---------------------------------------------------------------- filters, layout, top level


class Filter(_Model):
    id: str
    table: str
    field: str | None = None
    op: FilterOp | None = None
    value: Any = None
    expr: str | None = None
    label: str | None = None
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def _kebab(cls, v: str) -> str:
        return _check_kebab(v, "filter id")

    @model_validator(mode="after")
    def _shape(self) -> Filter:
        if self.expr is not None:
            if self.field is not None or self.op is not None or self.value is not None:
                raise ValueError("a filter has either 'expr' or 'field'/'op'/'value', not both")
            return self
        if self.field is None or self.op is None:
            raise ValueError("a filter needs 'field' and 'op' (or a boolean 'expr')")
        v = self.value
        if self.op == "between":
            if not (isinstance(v, list) and len(v) == 2 and all(_is_scalar(x) for x in v)):
                raise ValueError("'between' needs value = [min, max]")
        elif self.op == "in":
            if not (isinstance(v, list) and v and all(_is_scalar(x) for x in v)):
                raise ValueError("'in' needs a non-empty list of values")
        elif self.op == "contains":
            if not isinstance(v, str):
                raise ValueError("'contains' needs a string value")
        elif not _is_scalar(v) or v is None:
            raise ValueError(f"'{self.op}' needs a single number, string or boolean value")
        return self


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, bool, int)) or (isinstance(v, float) and math.isfinite(v))


class LayoutItem(BaseModel):
    # react-grid-layout may write back a few extra flags; anything else is rejected
    model_config = ConfigDict(extra="forbid")

    i: str
    x: int = Field(ge=0, lt=GRID_COLUMNS)
    y: int = Field(ge=0)
    w: int = Field(ge=1, le=GRID_COLUMNS)
    h: int = Field(ge=1, le=100)
    minW: int | None = None
    maxW: int | None = None
    minH: int | None = None
    maxH: int | None = None
    static: bool | None = None
    moved: bool | None = None

    @model_validator(mode="after")
    def _fits(self) -> LayoutItem:
        if self.x + self.w > GRID_COLUMNS:
            raise ValueError(f"layout item {self.i!r}: x + w must be <= {GRID_COLUMNS}")
        return self


class Theme(_Model):
    palette: str = "default"
    dark: bool = False


class Selection(_Model):
    key: str
    linked: bool = True


class Spec(_Model):
    version: Literal[1] = 1
    title: str = ""
    bundle: str
    theme: Theme | None = None
    filters: list[Filter] = Field(default_factory=list)
    panels: list[Panel] = Field(default_factory=list)
    layout: list[LayoutItem] = Field(default_factory=list)
    selection: Selection | None = None

    @model_validator(mode="after")
    def _ids_and_layout(self) -> Spec:
        errors: list[str] = []
        panel_ids = [p.id for p in self.panels]
        dup = sorted({i for i in panel_ids if panel_ids.count(i) > 1})
        if dup:
            errors.append(f"duplicate panel ids: {', '.join(dup)}")
        filter_ids = [f.id for f in self.filters]
        dup_f = sorted({i for i in filter_ids if filter_ids.count(i) > 1})
        if dup_f:
            errors.append(f"duplicate filter ids: {', '.join(dup_f)}")
        layout_ids = [item.i for item in self.layout]
        dup_l = sorted({i for i in layout_ids if layout_ids.count(i) > 1})
        if dup_l:
            errors.append(f"panels with more than one layout item: {', '.join(dup_l)}")
        missing = [i for i in dict.fromkeys(panel_ids) if i not in layout_ids]
        if missing:
            errors.append(f"panels without a layout item: {', '.join(missing)}")
        orphan = [i for i in dict.fromkeys(layout_ids) if i not in panel_ids]
        if orphan:
            errors.append(f"layout items without a panel: {', '.join(orphan)}")
        if errors:
            raise ValueError("; ".join(errors))
        return self


# ---------------------------------------------------------------- entry point


def _format_error(err: dict[str, Any]) -> str:
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = err.get("msg", "invalid")
    msg = msg.removeprefix("Value error, ")
    return f"{loc}: {msg}" if loc else msg


def parse_spec(data: Any) -> tuple[Spec | None, list[str]]:
    """Structurally validate a spec. Returns (spec, []) or (None, [human-readable errors]); never raises."""
    if not isinstance(data, dict):
        return None, ["spec must be a JSON object"]
    try:
        return Spec.model_validate(data), []
    except ValidationError as exc:
        return None, [_format_error(e) for e in exc.errors(include_url=False)]


def dump_spec(spec: Spec) -> dict[str, Any]:
    """Spec as plain JSON (what the frontend and the LLM see); unset optional fields are dropped."""
    return spec.model_dump(mode="json", exclude_none=True)
