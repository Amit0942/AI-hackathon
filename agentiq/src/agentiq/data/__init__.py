"""Data access, profiling and integration layer (Phase 1).

Public surface used by the notebooks and by every later phase::

    from agentiq.data import DataLake, CATALOG
    lake = DataLake()
    lake.inventory()                      # Step 1.1
    build_data_dictionary(lake)           # Step 1.2
    check_all_joins(lake)                 # Step 1.3
    load_briefs()                         # campaign brief integration
"""

from .briefs import (
    CampaignBriefDocument,
    DerivedBriefFields,
    briefs_frame,
    coverage_frame,
    derive_fields,
    load_briefs,
    requirements_frame,
)
from .catalog import CATALOG, LAYERS, TABLE_NAMES, ForeignKey, TableSpec, tables_by_layer
from .join_graph import (
    KEY_PATHS,
    JoinCheck,
    check_all_joins,
    check_join,
    joins_frame,
    mermaid_er,
    paths_frame,
    render_join_section,
    trace_all_paths,
)
from .inventory import (
    AsOfDate,
    CapacityModel,
    InventoryShape,
    SellableUnits,
    availability_by_block,
    block_demand,
    candidate_space,
    cold_start_census,
    concentration,
    deployment_split,
    facet_counts,
    infer_as_of_date,
    measure_capacity,
    profile_inventory,
    rotation_economics,
    sellable_units,
    solver_scenarios,
)
from .inventory_report import render_inventory_report
from .loaders import DataLake, LoadReport, read_table
from .paths import ProjectPaths, find_project_root
from .profiling import (
    build_data_dictionary,
    columns_frame,
    profile_lake,
    profile_table,
    render_data_dictionary,
    tables_frame,
)

__all__ = [
    "CATALOG",
    "KEY_PATHS",
    "LAYERS",
    "TABLE_NAMES",
    "AsOfDate",
    "CampaignBriefDocument",
    "CapacityModel",
    "DataLake",
    "DerivedBriefFields",
    "ForeignKey",
    "InventoryShape",
    "JoinCheck",
    "LoadReport",
    "ProjectPaths",
    "SellableUnits",
    "TableSpec",
    "availability_by_block",
    "block_demand",
    "briefs_frame",
    "build_data_dictionary",
    "candidate_space",
    "check_all_joins",
    "check_join",
    "cold_start_census",
    "columns_frame",
    "concentration",
    "coverage_frame",
    "deployment_split",
    "derive_fields",
    "facet_counts",
    "find_project_root",
    "infer_as_of_date",
    "joins_frame",
    "load_briefs",
    "measure_capacity",
    "mermaid_er",
    "paths_frame",
    "profile_inventory",
    "profile_lake",
    "profile_table",
    "read_table",
    "render_data_dictionary",
    "render_inventory_report",
    "render_join_section",
    "requirements_frame",
    "rotation_economics",
    "sellable_units",
    "solver_scenarios",
    "tables_by_layer",
    "tables_frame",
    "trace_all_paths",
]
