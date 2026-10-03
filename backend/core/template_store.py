"""
template_store.py — Persistent template and business workflow store.
Manages built-in template catalogs and custom user-saved pipelines.
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("datapilot.template_store")



# Default pre-packaged high-value corporate templates aligned with transform_engine.py
BUILT_IN_TEMPLATES = [
    # --- Sales Templates ---
    {
        "template_id": "sales_rev_std",
        "name": "Revenue Aggregator & Standardizer",
        "description": "Standardizes product names to uppercase, imputes missing units, and cleans sales/revenue parameters.",
        "category": "Sales",
        "steps": [
            {"action": "normalize_text", "column": "product", "strategy": "upper", "description": "Convert product values to uppercase"},
            {"action": "fill_nulls", "column": "sales", "strategy": "median", "description": "Impute missing sales volume using median"},
            {"action": "fill_nulls", "column": "revenue", "strategy": "median", "description": "Impute missing revenue using median"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "sales_product_calc",
        "name": "Product Performance Calculator",
        "description": "Standardizes product naming and aggregates revenue streams by specific product segments.",
        "category": "Sales",
        "steps": [
            {"action": "normalize_text", "column": "product", "strategy": "upper", "description": "Convert product values to uppercase"},
            {"action": "group_aggregate", "group_by": ["product"], "aggregations": [{"column": "revenue", "func": "sum"}], "description": "Group by product and sum revenue"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "sales_cust_profiler",
        "name": "Customer Trend Profiler",
        "description": "Imputes customer region settings and standardizes geographical codes.",
        "category": "Sales",
        "steps": [
            {"action": "fill_nulls", "column": "region", "strategy": "constant", "fill_value": "GLOBAL", "description": "Impute missing region fields with constant GLOBAL"},
            {"action": "normalize_text", "column": "region", "strategy": "upper", "description": "Convert region tags to uppercase"}
        ],
        "is_builtin": True
    },
    # --- Finance Templates ---
    {
        "template_id": "fin_recon_format",
        "name": "Reconciliation Formatter",
        "description": "Imputes missing invoice codes, normalizes values, and prepares spreadsheets for reconciliation audits.",
        "category": "Finance",
        "steps": [
            {"action": "fill_nulls", "column": "invoice", "strategy": "constant", "fill_value": "UNASSIGNED", "description": "Impute missing invoice codes with constant UNASSIGNED"},
            {"action": "normalize_text", "column": "invoice", "strategy": "upper", "description": "Convert invoices to uppercase"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "fin_gst_std",
        "name": "GST Analysis Standardizer",
        "description": "Renames tax columns, normalizes billing numbers, and filters out zero-revenue invoice lines.",
        "category": "Finance",
        "steps": [
            {"action": "rename_column", "column": "tax", "new_name": "GST_tax", "description": "Rename tax column to GST_tax"},
            {"action": "filter_rows", "column": "revenue", "operator": ">", "value": 0, "description": "Filter invoice lines with positive revenue"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "fin_expense_tracker",
        "name": "Expense Tracker Cleanup",
        "description": "Trims whitespace, capitalizes expense categories, and structures standard expense logs.",
        "category": "Finance",
        "steps": [
            {"action": "normalize_text", "column": "category", "strategy": "title", "description": "Format expense categories in Title Case"},
            {"action": "fill_nulls", "column": "amount", "strategy": "median", "description": "Impute missing amounts with median"}
        ],
        "is_builtin": True
    },
    # --- Inventory Templates ---
    {
        "template_id": "inv_stock_forecast",
        "name": "Stock Forecasting Profiler",
        "description": "Fills missing stock quantifiers, converts serial numbers, and shapes serial catalog fields.",
        "category": "Inventory",
        "steps": [
            {"action": "fill_nulls", "column": "quantity", "strategy": "mean", "description": "Impute missing stock quantities using mean"},
            {"action": "normalize_text", "column": "serial", "strategy": "upper", "description": "Convert serial parameters to uppercase"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "inv_reorder_analyzer",
        "name": "Reorder Analyzer",
        "description": "Aggregates available units by product name to quickly identify inventory reorder requirements.",
        "category": "Inventory",
        "steps": [
            {"action": "group_aggregate", "group_by": ["product"], "aggregations": [{"column": "quantity", "func": "sum"}], "description": "Sum quantities by product category"}
        ],
        "is_builtin": True
    },
    # --- HR Templates ---
    {
        "template_id": "hr_payroll_clean",
        "name": "Payroll Clean & Standardize",
        "description": "Imputes payroll blank fields, converts salary parameters, and structures payroll audits.",
        "category": "HR",
        "steps": [
            {"action": "fill_nulls", "column": "salary", "strategy": "median", "description": "Impute missing salaries using median"},
            {"action": "convert_type", "column": "salary", "target_type": "float", "description": "Convert salary parameters to float"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "hr_attendance_audit",
        "name": "Attendance Audit Cleaner",
        "description": "Imputes missing attendance scores and formats employee records.",
        "category": "HR",
        "steps": [
            {"action": "fill_nulls", "column": "attendance", "strategy": "constant", "fill_value": 1.0, "description": "Impute missing attendance with 1.0"}
        ],
        "is_builtin": True
    },
    {
        "template_id": "hr_overtime_tracker",
        "name": "Overtime Performance Tracker",
        "description": "Formats HR employee overtime rates and validates hours worked parameters.",
        "category": "HR",
        "steps": [
            {"action": "convert_type", "column": "rate", "target_type": "float", "description": "Convert rate fields to float"},
            {"action": "convert_type", "column": "hours", "target_type": "float", "description": "Convert hours fields to float"}
        ],
        "is_builtin": True
    }
]


from datetime import datetime
from core.db import get_connection

class TemplateStore:
    """Templates are read from the database on every call (no per-process cache),
    so every API worker sees the same data immediately."""

    def __init__(self):
        pass

    @staticmethod
    def _fetch(where: str, params: tuple) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT template_id, name, description, category, steps, is_builtin, user_id, workspace_id, "
                f"created_at, updated_at FROM templates WHERE {where};",
                params,
            )
            out = []
            for row in cursor.fetchall():
                d = dict(row)
                d["steps"] = json.loads(d["steps"])
                d["is_builtin"] = bool(d["is_builtin"])
                out.append(d)
            return out
        finally:
            conn.close()

    @property
    def _custom_templates(self) -> Dict[str, Dict[str, Any]]:  # backwards compatibility for tests/tools
        return {t["template_id"]: t for t in self._fetch("1 = 1", ())}

    def list_templates(self, user_id: str = "default_user", workspace_id: str = "default_workspace") -> List[Dict[str, Any]]:
        return BUILT_IN_TEMPLATES + self._fetch("user_id = ? AND workspace_id = ?", (user_id, workspace_id))

    def get_template(
        self,
        template_id: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Dict[str, Any] | None:
        for t in BUILT_IN_TEMPLATES:
            if t["template_id"] == template_id:
                return t
        rows = self._fetch("template_id = ?", (template_id,))
        if not rows:
            return None
        template = rows[0]
        if user_id is not None and workspace_id is not None:
            if template.get("user_id") != user_id or template.get("workspace_id") != workspace_id:
                return None
        return template

    def create_template(self, name: str, description: str, category: str, steps: List[Dict[str, Any]], user_id: str = "default_user", workspace_id: str = "default_workspace") -> Dict[str, Any]:
        """Save a new custom template to SQLite and local cache."""
        template_id = f"custom_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        template = {
            "template_id": template_id,
            "name": name.strip(),
            "description": description.strip(),
            "category": category.strip(),
            "steps": steps,
            "is_builtin": False,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "created_at": now,
            "updated_at": now
        }
        
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO templates (template_id, name, description, category, steps, is_builtin, user_id, workspace_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?);
                """,
                (
                    template_id,
                    template["name"],
                    template["description"],
                    template["category"],
                    json.dumps(steps),
                    user_id,
                    workspace_id,
                    now,
                    now
                )
            )
            conn.commit()
            logger.info(f"Created template {template_id} in SQLite")
        except Exception as e:
            logger.error(f"Failed to create template: {e}")
        finally:
            conn.close()
        return template

    def duplicate_template(self, template_id: str, user_id: str = "default_user", workspace_id: str = "default_workspace") -> Dict[str, Any] | None:
        """Duplicate an existing template, append (Copy) to name, and save to SQLite."""
        source = self.get_template(template_id, user_id=user_id, workspace_id=workspace_id)
        if not source:
            return None
            
        import copy
        new_steps = copy.deepcopy(source["steps"])
        
        new_template_id = f"custom_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        duplicated = {
            "template_id": new_template_id,
            "name": f"{source['name']} (Copy)",
            "description": source["description"],
            "category": source["category"],
            "steps": new_steps,
            "is_builtin": False,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "created_at": now,
            "updated_at": now
        }
        
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO templates (template_id, name, description, category, steps, is_builtin, user_id, workspace_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?);
                """,
                (
                    new_template_id,
                    duplicated["name"],
                    duplicated["description"],
                    duplicated["category"],
                    json.dumps(new_steps),
                    user_id,
                    workspace_id,
                    now,
                    now
                )
            )
            conn.commit()
            logger.info(f"Duplicated template {template_id} to {new_template_id}")
        except Exception as e:
            logger.error(f"Failed to duplicate template: {e}")
            return None
        finally:
            conn.close()
        return duplicated

    def delete_template(
        self,
        template_id: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> bool:
        """Delete a custom template (scoped to its owner when user/workspace are given)."""
        conn = get_connection()
        try:
            params = [template_id]
            scope_sql = ""
            if user_id is not None and workspace_id is not None:
                scope_sql = " AND user_id = ? AND workspace_id = ?"
                params.extend([user_id, workspace_id])
            cursor = conn.execute(f"DELETE FROM templates WHERE template_id = ? AND is_builtin = 0{scope_sql};", tuple(params))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete template: {e}")
            return False
        finally:
            conn.close()


_store: TemplateStore | None = None


def get_template_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store
