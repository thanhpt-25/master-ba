"""Deterministic pipelines connecting agents, team runtime, trace store and renderer."""

from masterba.pipeline.basic import (
    DESIGN_DOC_ID,
    IT_DOC_ID,
    ST_DOC_ID,
    BasicArtifacts,
    assign_basic_ids,
    run_basic_design,
)
from masterba.pipeline.brd import (
    BRD_DOC_ID,
    BrdArtifacts,
    assign_ids,
    next_requirement_number,
    run_brd,
)
from masterba.pipeline.detail import (
    DETAIL_DOC_ID,
    UT_DOC_ID,
    DetailArtifacts,
    assign_detail_ids,
    run_detail_design,
)
from masterba.pipeline.srs import SRS_DOC_ID, SrsArtifacts, assign_srs_ids, run_srs
from masterba.pipeline.stage import Resume, StageResult, stage_summary

__all__ = [
    "DETAIL_DOC_ID",
    "UT_DOC_ID",
    "DetailArtifacts",
    "assign_detail_ids",
    "run_detail_design",
    "DESIGN_DOC_ID",
    "IT_DOC_ID",
    "ST_DOC_ID",
    "BasicArtifacts",
    "assign_basic_ids",
    "run_basic_design",
    "BRD_DOC_ID",
    "SRS_DOC_ID",
    "BrdArtifacts",
    "SrsArtifacts",
    "Resume",
    "StageResult",
    "assign_ids",
    "assign_srs_ids",
    "next_requirement_number",
    "run_brd",
    "run_srs",
    "stage_summary",
]
