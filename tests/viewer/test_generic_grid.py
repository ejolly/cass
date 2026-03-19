"""TDD tests for generic_grid — column defs for generic DB viewer."""

from __future__ import annotations

__docformat__ = "google"


class TestBuildGenericColumnDefs:
    def test_returns_list_of_dicts(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("name", "string"), ("score", "float64")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        assert isinstance(defs, list)
        assert all(isinstance(d, dict) for d in defs)

    def test_pk_columns_not_editable(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("name", "string")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        id_def = next(d for d in defs if d["field"] == "id")
        assert id_def.get("editable") is not True

    def test_non_pk_columns_editable_by_default(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("name", "string")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        name_def = next(d for d in defs if d["field"] == "name")
        assert name_def.get("editable") is True

    def test_editable_false_disables_all(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("name", "string")]
        defs = build_generic_column_defs(schema, pk_cols=["id"], editable=False)
        for d in defs:
            assert d.get("editable") is not True

    def test_numeric_type_gets_number_editor(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("val", "float64")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        val_def = next(d for d in defs if d["field"] == "val")
        assert val_def.get("cellEditor") == "agNumberCellEditor"

    def test_bool_type_gets_checkbox(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("active", "boolean")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        bool_def = next(d for d in defs if d["field"] == "active")
        assert bool_def.get("cellRenderer") == "agCheckboxCellRenderer"

    def test_all_columns_sortable(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("a", "string"), ("b", "int64")]
        defs = build_generic_column_defs(schema, pk_cols=[])
        assert all(d.get("sortable") for d in defs)

    def test_hidden_rowid_when_no_pk(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("a", "string"), ("b", "int64")]
        defs = build_generic_column_defs(schema, pk_cols=[], use_rowid=True)
        rowid_def = next((d for d in defs if d["field"] == "rowid"), None)
        assert rowid_def is not None
        assert rowid_def.get("hide") is True

    def test_categorical_column_gets_select_editor(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("color", "string")]
        categoricals = {"color": ["blue", "green", "red"]}
        defs = build_generic_column_defs(
            schema, pk_cols=["id"], categoricals=categoricals
        )
        color_def = next(d for d in defs if d["field"] == "color")
        assert color_def["cellEditor"] == "agSelectCellEditor"
        assert color_def["cellEditorParams"]["values"] == ["blue", "green", "red"]

    def test_categorical_pk_not_editable(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("status", "string"), ("val", "int64")]
        categoricals = {"status": ["active", "inactive"]}
        defs = build_generic_column_defs(
            schema, pk_cols=["status"], categoricals=categoricals
        )
        status_def = next(d for d in defs if d["field"] == "status")
        assert status_def.get("editable") is not True
        assert "cellEditor" not in status_def

    def test_numeric_int_gets_stepper_and_precision(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("count", "int32")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        count_def = next(d for d in defs if d["field"] == "count")
        assert count_def["cellEditor"] == "agNumberCellEditor"
        params = count_def["cellEditorParams"]
        assert params["showStepperButtons"] is True
        assert params["precision"] == 0
        assert params["step"] == 1

    def test_numeric_float_gets_stepper_no_precision(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("score", "float64")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        score_def = next(d for d in defs if d["field"] == "score")
        params = score_def["cellEditorParams"]
        assert params["showStepperButtons"] is True
        assert "precision" not in params

    def test_timestamp_gets_date_editor_with_time(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("created", "timestamp")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        ts_def = next(d for d in defs if d["field"] == "created")
        assert ts_def["cellEditor"] == "agDateStringCellEditor"
        assert ts_def["cellEditorParams"]["includeTime"] is True

    def test_date_gets_date_editor_without_time(self) -> None:
        from cass.viewer.generic_grid import build_generic_column_defs

        schema = [("id", "int64"), ("birthday", "date")]
        defs = build_generic_column_defs(schema, pk_cols=["id"])
        date_def = next(d for d in defs if d["field"] == "birthday")
        assert date_def["cellEditor"] == "agDateStringCellEditor"
        assert "cellEditorParams" not in date_def
