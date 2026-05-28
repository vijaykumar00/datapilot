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

TEMPLATES_DIR = Path(__file__).parent.parent / "uploads"
TEMPLATES_DIR.mkdir(exist_ok=True)
TEMPLATES_FILE = TEMPLATES_DIR / "templates.json"

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


class TemplateStore:
    def __init__(self):
        self._custom_templates: Dict[str, Dict[str, Any]] = {}
        self._load_custom_templates()

    def _load_custom_templates(self):
        """Load persistent templates from JSON file on disk."""
        if not TEMPLATES_FILE.exists():
            self._custom_templates = {}
            return
        try:
            with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._custom_templates = {t["template_id"]: t for t in data}
                else:
                    self._custom_templates = data
            logger.info("Loaded %d custom templates from disk", len(self._custom_templates))
        except Exception as e:
            logger.error("Failed to load custom templates from %s: %s", TEMPLATES_FILE, e)
            self._custom_templates = {}

    def _save_custom_templates(self):
        """Persist custom templates to JSON file on disk."""
        try:
            with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
                json.dump(self._custom_templates, f, indent=2, ensure_ascii=False)
            logger.info("Persisted %d custom templates to disk", len(self._custom_templates))
        except Exception as e:
            logger.error("Failed to persist custom templates: %s", e)

    def list_templates(self) -> List[Dict[str, Any]]:
        """Return full list of built-in and custom templates."""
        custom_list = list(self._custom_templates.values())
        return BUILT_IN_TEMPLATES + custom_list

    def get_template(self, template_id: str) -> Dict[str, Any] | None:
        """Fetch template by ID."""
        for t in BUILT_IN_TEMPLATES:
            if t["template_id"] == template_id:
                return t
        return self._custom_templates.get(template_id)

    def create_template(self, name: str, description: str, category: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Save a new custom template and persist to disk."""
        template_id = f"custom_{uuid.uuid4().hex[:8]}"
        template = {
            "template_id": template_id,
            "name": name.strip(),
            "description": description.strip(),
            "category": category.strip(),
            "steps": steps,
            "is_builtin": False
        }
        self._custom_templates[template_id] = template
        self._save_custom_templates()
        return template

    def duplicate_template(self, template_id: str) -> Dict[str, Any] | None:
        """Duplicate an existing template, append (Copy) to name, and save to disk."""
        source = self.get_template(template_id)
        if not source:
            return None
            
        import copy
        new_steps = copy.deepcopy(source["steps"])
        
        new_template_id = f"custom_{uuid.uuid4().hex[:8]}"
        duplicated = {
            "template_id": new_template_id,
            "name": f"{source['name']} (Copy)",
            "description": source["description"],
            "category": source["category"],
            "steps": new_steps,
            "is_builtin": False
        }
        self._custom_templates[new_template_id] = duplicated
        self._save_custom_templates()
        return duplicated

    def delete_template(self, template_id: str) -> bool:
        """Delete custom template from store and disk."""
        if template_id in self._custom_templates:
            del self._custom_templates[template_id]
            self._save_custom_templates()
            return True
        return False


_store: TemplateStore | None = None


def get_template_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store
