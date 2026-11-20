"""The payroll workbook package: every part defines what the entry binds to the shared state."""
import ast
import inspect

from backend.app.services.workbook import payroll
from backend.app.services.workbook.payroll import build, controls, report


def test_parts_define_their_functions():
    for module, names in ((controls, ["write_control_lead", "lead_to_g1", "write_control_table", "clear_from",
                                      "tab_opening", "other_entries"]),
                          (report, ["payroll_report_lines", "write_payroll_report", "directors_per_file",
                                    "write_directors"]),
                          (build, ["build_payroll"])):
        for name in names:
            assert callable(getattr(module, name, None)), f"{module.__name__}.{name} missing"


def test_entry_binds_only_existing_parts():
    tree = ast.parse(inspect.getsource(payroll))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and \
                node.value.id in ("build", "controls", "report"):
            assert hasattr({"build": build, "controls": controls, "report": report}[node.value.id], node.attr)
