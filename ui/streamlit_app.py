"""
streamlit_app.py — Multi-Source Candidate Data Transformer UI

Modes:
  • Single Candidate — original one-at-a-time flow (unchanged)
  • Batch Mode       — upload multiple ATS JSONs / PDFs / GitHub URLs in one run

Run with:
    streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv(override=True)

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.candidate import CanonicalCandidate
from app.services.batch_service import CandidateSlot, run_batch
from app.services.transformer_service import TransformerService
from app.utils.helpers import write_json_file
from config.settings import MERGE_LOG_PATH, OUTPUT_DIR

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Candidate Profile Transformer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.main {
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #16213e 100%);
}
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #0f0f1a 100%);
    border-right: 1px solid rgba(255,255,255,0.08);
}
.card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
    backdrop-filter: blur(10px);
    transition: border-color 0.2s ease;
}
.card:hover { border-color: rgba(100,149,237,0.4); }
.metric-card {
    background: linear-gradient(135deg, rgba(100,149,237,0.15) 0%, rgba(147,112,219,0.15) 100%);
    border: 1px solid rgba(100,149,237,0.3);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
}
.gradient-text {
    background: linear-gradient(135deg, #6495ED 0%, #9370DB 50%, #48D1CC 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-weight: 700;
}
.conf-bar {
    height: 8px; border-radius: 4px;
    background: linear-gradient(90deg, #6495ED, #9370DB);
    transition: width 0.5s ease;
}
.conf-bg {
    height: 8px; border-radius: 4px;
    background: rgba(255,255,255,0.08);
    margin-bottom: 6px;
}
.skill-badge {
    display: inline-block;
    background: linear-gradient(135deg, rgba(100,149,237,0.2), rgba(147,112,219,0.2));
    border: 1px solid rgba(100,149,237,0.4);
    border-radius: 20px;
    padding: 4px 12px; margin: 4px;
    font-size: 0.85em; font-weight: 500; color: #A8C4FF;
    transition: all 0.2s;
}
.source-ats    { background:rgba(72,209,204,0.15); border-color:rgba(72,209,204,0.5); color:#48D1CC; }
.source-resume { background:rgba(147,112,219,0.15); border-color:rgba(147,112,219,0.5); color:#9370DB; }
.source-github { background:rgba(100,149,237,0.15); border-color:rgba(100,149,237,0.5); color:#6495ED; }
.status-high   { color:#4CAF50; }
.status-medium { color:#FFC107; }
.status-low    { color:#F44336; }
.section-header {
    font-size:1.1em; font-weight:600; color:rgba(255,255,255,0.9);
    margin-bottom:12px; padding-bottom:8px;
    border-bottom:1px solid rgba(255,255,255,0.08);
}
.stTabs [data-baseweb="tab-list"] {
    background:rgba(255,255,255,0.03); border-radius:12px;
    padding:6px; gap:8px; margin-bottom:24px;
}
.stTabs [data-baseweb="tab"] {
    border-radius:8px; font-weight:500; transition:all 0.2s; padding:10px 24px !important;
}
.stFileUploader {
    border:2px dashed rgba(100,149,237,0.3) !important;
    border-radius:12px !important;
    background:rgba(100,149,237,0.04) !important;
    transition:border-color 0.2s;
}
.stFileUploader:hover { border-color:rgba(100,149,237,0.6) !important; }
.stButton > button {
    background:linear-gradient(135deg, #6495ED 0%, #9370DB 100%);
    color:white; border:none; border-radius:10px;
    padding:8px 16px; font-weight:600; font-size:0.9em;
    width:100%; transition:all 0.2s;
    box-shadow:0 4px 20px rgba(100,149,237,0.3);
}
.stButton > button:hover {
    transform:translateY(-2px);
    box-shadow:0 8px 30px rgba(100,149,237,0.4);
}
.json-viewer {
    background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.08);
    border-radius:12px; padding:16px;
    font-family:'Courier New',monospace; font-size:0.85em;
    max-height:600px; overflow-y:auto;
}
.alert-error {
    background:rgba(244,67,54,0.12); border:1px solid rgba(244,67,54,0.4);
    border-radius:10px; padding:12px 16px; color:#EF9A9A; margin-bottom:12px;
}
.alert-warning {
    background:rgba(255,193,7,0.12); border:1px solid rgba(255,193,7,0.4);
    border-radius:10px; padding:12px 16px; color:#FFE082; margin-bottom:12px;
}
.alert-success {
    background:rgba(76,175,80,0.12); border:1px solid rgba(76,175,80,0.4);
    border-radius:10px; padding:12px 16px; color:#A5D6A7;
}

/* Batch table rows */
.batch-row {
    display:flex; align-items:center; gap:12px;
    padding:12px 16px; border-radius:10px;
    background:rgba(255,255,255,0.03);
    border:1px solid rgba(255,255,255,0.06);
    margin-bottom:8px; transition:all 0.2s; cursor:pointer;
}
.batch-row:hover { border-color:rgba(100,149,237,0.4); background:rgba(100,149,237,0.06); }
.batch-row.selected { border-color:rgba(100,149,237,0.7); background:rgba(100,149,237,0.1); }
.batch-status-ok    { color:#4CAF50; font-weight:600; }
.batch-status-error { color:#F44336; font-weight:600; }
.batch-status-skip  { color:#9E9E9E; font-weight:600; }

/* Mode toggle pill */
.mode-pill {
    display:inline-block; padding:4px 14px; border-radius:20px; font-size:0.82em;
    font-weight:600; margin:2px;
}
.mode-single { background:rgba(100,149,237,0.2); color:#6495ED; border:1px solid rgba(100,149,237,0.4); }
.mode-batch  { background:rgba(147,112,219,0.2); color:#9370DB; border:1px solid rgba(147,112,219,0.4); }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Small HTML helpers
# ---------------------------------------------------------------------------

def render_confidence_badge(score: float) -> str:
    if score >= 0.9:
        cls = "status-high"
    elif score >= 0.7:
        cls = "status-medium"
    else:
        cls = "status-low"
    return f'<span class="{cls}">●</span> {score:.0%}'


def render_source_badge(source: str) -> str:
    css = {"ATS": "source-ats", "Resume": "source-resume", "GitHub": "source-github"}.get(source, "")
    return f'<span class="skill-badge {css}">{source}</span>'


def render_skill_badge(skill_name: str, confidence: float, show_confidence: bool = True) -> str:
    if show_confidence:
        return f'<span class="skill-badge" title="Confidence: {confidence:.0%}">{skill_name}</span>'
    return f'<span class="skill-badge">{skill_name}</span>'


def render_confidence_bar(label: str, score: float) -> str:
    pct = int(score * 100)
    color = (
        "linear-gradient(90deg, #4CAF50, #66BB6A)" if score >= 0.9
        else "linear-gradient(90deg, #FFC107, #FFB300)" if score >= 0.7
        else "linear-gradient(90deg, #F44336, #EF5350)"
    )
    return f"""
    <div style="margin-bottom:12px;">
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span style="font-weight:500; font-size:0.9em;">{label}</span>
        <span style="font-size:0.9em; color:rgba(255,255,255,0.6);">{pct}%</span>
      </div>
      <div class="conf-bg">
        <div class="conf-bar" style="width:{pct}%; background:{color};"></div>
      </div>
    </div>
    """


# ---------------------------------------------------------------------------
# Sidebar — Single-candidate mode
# ---------------------------------------------------------------------------

def _render_single_sidebar() -> tuple[
    Optional[dict], Optional[bytes], Optional[str], bool, bool, dict[str, bool], bool
]:
    """Render single-candidate inputs. Returns (ats_data, resume_bytes, github_url,
    show_provenance, show_confidence, selected_fields, generate)."""

    st.sidebar.markdown("#### 📋 ATS Data")
    ats_file = st.sidebar.file_uploader(
        "Upload ATS JSON", type=["json"], key="ats_upload",
        help="Structured ATS export in JSON format",
    )
    ats_data: Optional[dict] = None
    if ats_file:
        try:
            ats_file.seek(0)
            ats_data = json.loads(ats_file.read().decode("utf-8"))
            st.sidebar.markdown('<div class="alert-success">✓ ATS JSON loaded</div>', unsafe_allow_html=True)
        except json.JSONDecodeError as exc:
            st.sidebar.markdown(f'<div class="alert-error">✗ Invalid JSON: {exc}</div>', unsafe_allow_html=True)

    st.sidebar.markdown("#### 📄 Resume PDF")
    resume_file = st.sidebar.file_uploader(
        "Upload Resume PDF", type=["pdf"], key="resume_upload",
        help="Scanned or image-based PDF resume",
    )
    resume_bytes: Optional[bytes] = None
    if resume_file:
        resume_file.seek(0)
        resume_bytes = resume_file.read()
        st.sidebar.markdown('<div class="alert-success">✓ PDF loaded</div>', unsafe_allow_html=True)

    st.sidebar.markdown("#### 🐙 GitHub Profile")
    github_url = st.sidebar.text_input(
        "GitHub URL", placeholder="https://github.com/username", key="github_url",
    )
    if github_url and not github_url.startswith("https://github.com/"):
        st.sidebar.markdown('<div class="alert-warning">⚠ Check URL format</div>', unsafe_allow_html=True)

    show_provenance, show_confidence, selected_fields = _render_common_config("single")

    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    generate = st.sidebar.button("🚀 Generate Profile", use_container_width=True, key="btn_generate_single")

    return ats_data, resume_bytes, github_url or None, show_provenance, show_confidence, selected_fields, generate


# ---------------------------------------------------------------------------
# Sidebar — Batch mode
# ---------------------------------------------------------------------------

def _render_batch_sidebar() -> tuple[
    list[dict], list[bytes | None], list[str | None], bool, bool, dict[str, bool], bool
]:
    """Render batch-mode inputs. Returns (ats_list, resume_list, github_list,
    show_provenance, show_confidence, selected_fields, run_batch_btn)."""

    st.sidebar.markdown("#### 📋 ATS JSON Files *(one per candidate)*")
    ats_files = st.sidebar.file_uploader(
        "Upload ATS JSONs", type=["json"], accept_multiple_files=True,
        key="batch_ats_upload",
        help="Upload multiple ATS JSON files — one per candidate, matched by index order.",
    )

    st.sidebar.markdown("#### 📄 Resume PDFs *(one per candidate)*")
    resume_files = st.sidebar.file_uploader(
        "Upload Resume PDFs", type=["pdf"], accept_multiple_files=True,
        key="batch_resume_upload",
        help="Upload multiple PDFs. Matched to ATS JSONs by index order.",
    )

    st.sidebar.markdown("#### 🐙 GitHub URLs *(one per line)*")
    github_text = st.sidebar.text_area(
        "GitHub URLs (one per line)",
        placeholder="https://github.com/alice\nhttps://github.com/bob\nhttps://github.com/carol",
        key="batch_github_urls",
        height=100,
        help="One GitHub profile URL per line, matched by index order.",
    )

    # Parse GitHub lines
    github_lines: list[str | None] = [
        ln.strip() if ln.strip() else None
        for ln in (github_text or "").splitlines()
    ]

    # Preview counts
    n_ats     = len(ats_files)
    n_resume  = len(resume_files)
    n_github  = len([g for g in github_lines if g])
    n_total   = max(n_ats, len(resume_files), len(github_lines)) if (ats_files or resume_files or github_lines) else 0

    if n_total > 0:
        st.sidebar.markdown(
            f"<div style='font-size:0.82em; color:rgba(255,255,255,0.5); margin-top:6px;'>"
            f"🗂 {n_ats} ATS &nbsp;|&nbsp; 📄 {n_resume} PDFs &nbsp;|&nbsp; "
            f"🐙 {n_github} GitHub URLs &nbsp;→&nbsp; <b>{n_total} candidate slot(s)</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

    show_provenance, show_confidence, selected_fields = _render_common_config("batch")

    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    run_batch_btn = st.sidebar.button(
        f"🚀 Run Batch ({n_total} candidate{'s' if n_total != 1 else ''})",
        use_container_width=True,
        key="btn_run_batch",
        disabled=(n_total == 0),
    )

    ats_list: list[dict] = []
    for i in range(n_total):
        if i < len(ats_files):
            try:
                ats_files[i].seek(0)
                ats_list.append(json.loads(ats_files[i].read().decode("utf-8")))
            except Exception as exc:
                ats_list.append({})
        else:
            ats_list.append({})

    resume_list: list[bytes | None] = []
    for i in range(n_total):
        if i < len(resume_files):
            try:
                resume_files[i].seek(0)
                resume_list.append(resume_files[i].read())
            except Exception:
                resume_list.append(None)
        else:
            resume_list.append(None)

    github_list: list[str | None] = [
        github_lines[i] if i < len(github_lines) else None
        for i in range(n_total)
    ]

    return ats_list, resume_list, github_list, show_provenance, show_confidence, selected_fields, run_batch_btn


# ---------------------------------------------------------------------------
# Sidebar — shared config (used by both modes)
# ---------------------------------------------------------------------------

def _render_common_config(prefix: str) -> tuple[bool, bool, dict[str, bool]]:
    st.sidebar.markdown("#### ⚙️ Runtime Config")
    show_provenance = st.sidebar.toggle("Show Provenance", value=True, key=f"{prefix}_show_provenance")
    show_confidence = st.sidebar.toggle("Show Confidence", value=True, key=f"{prefix}_show_confidence")

    st.sidebar.markdown("#### 🎛️ Field Visibility")
    fields_to_toggle = [
        "candidate_id", "full_name", "emails", "phones", "location",
        "links", "headline", "skills", "experience", "education", "overall_confidence",
    ]

    col_all, col_none = st.sidebar.columns([1, 1.25])
    with col_all:
        if st.button("Select All", use_container_width=True, key=f"{prefix}_sel_all"):
            for f in fields_to_toggle:
                st.session_state[f"{prefix}_field_{f}"] = True
            st.rerun()
    with col_none:
        if st.button("Deselect All", use_container_width=True, key=f"{prefix}_sel_none"):
            for f in fields_to_toggle:
                st.session_state[f"{prefix}_field_{f}"] = False
            st.rerun()

    selected_fields: dict[str, bool] = {}
    for f in fields_to_toggle:
        key_name = f"{prefix}_field_{f}"
        if key_name not in st.session_state:
            st.session_state[key_name] = True
        selected_fields[f] = st.sidebar.checkbox(
            f, value=st.session_state[key_name], key=key_name,
        )

    return show_provenance, show_confidence, selected_fields


# ---------------------------------------------------------------------------
# Tab renderers (unchanged from single-candidate mode)
# ---------------------------------------------------------------------------

def render_canonical_visual_view(
    candidate: CanonicalCandidate,
    selected_fields: dict[str, bool],
    show_confidence: bool = True,
) -> None:
    """Render LinkedIn-style visual profile."""
    show_overall = show_confidence and selected_fields.get("overall_confidence", True)

    visible_metrics = []
    if show_overall:
        visible_metrics.append(("Overall Confidence", f"{candidate.overall_confidence:.0%}"))
    if selected_fields.get("skills", True):
        visible_metrics.append(("Skills", len(candidate.skills)))
    if selected_fields.get("experience", True):
        visible_metrics.append(("Experience", len(candidate.experience)))
    if selected_fields.get("education", True):
        visible_metrics.append(("Education", len(candidate.education)))

    if visible_metrics:
        cols = st.columns(len(visible_metrics))
        for idx, (label, val) in enumerate(visible_metrics):
            with cols[idx]:
                st.metric(label, val)
        st.markdown("<br>", unsafe_allow_html=True)

    # Identity
    show_identity = any(
        selected_fields.get(f, True)
        for f in ["full_name", "candidate_id", "headline", "years_experience", "location"]
    )
    if show_identity:
        with st.container(border=True):
            st.markdown("#### 👤 Identity")
            name_val = candidate.full_name if selected_fields.get("full_name", True) else None
            id_val   = candidate.candidate_id if selected_fields.get("candidate_id", True) else None
            if name_val or id_val:
                col_name, col_id = st.columns([3, 1])
                with col_name:
                    if name_val:
                        st.markdown(f"<h2 style='margin:0; font-size:1.8em;'>{name_val}</h2>", unsafe_allow_html=True)
                with col_id:
                    if id_val:
                        st.markdown(f"<div style='text-align:right; color:gray; font-size:0.8em;'>ID: {id_val[:8]}...</div>", unsafe_allow_html=True)
            if selected_fields.get("headline", True) and candidate.headline:
                st.markdown(f"**{candidate.headline}**")
            loc_disp = ""
            if selected_fields.get("location", True) and candidate.location:
                loc = candidate.location
                loc_parts = [p for p in [loc.city, loc.state] if p]
                if loc.country and not loc_parts:
                    loc_parts = [loc.country]
                elif loc.country and loc.country not in ("IN", "US", "GB"):
                    loc_parts.append(loc.country)
                loc_disp = ", ".join(loc_parts) or loc.raw or ""
            exp_disp = ""
            if selected_fields.get("years_experience", True) and candidate.years_experience is not None:
                exp_disp = f"💼 {candidate.years_experience} Years of Experience"
            if exp_disp or loc_disp:
                meta_parts = []
                if exp_disp:
                    meta_parts.append(exp_disp)
                if loc_disp:
                    meta_parts.append(f"📍 {loc_disp}")
                st.markdown(" · ".join(meta_parts))

    # Contact
    show_contact = any(selected_fields.get(f, True) for f in ["emails", "phones", "links"])
    if show_contact:
        with st.container(border=True):
            st.markdown("#### 📞 Contact Info")
            cols = st.columns(3)
            with cols[0]:
                if selected_fields.get("emails", True) and candidate.emails:
                    st.markdown("**✉️ Email(s)**")
                    for email in candidate.emails:
                        st.markdown(f"`{email}`")
                else:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
            with cols[1]:
                if selected_fields.get("phones", True) and candidate.phones:
                    st.markdown("**📞 Phone(s)**")
                    for phone in candidate.phones:
                        st.markdown(f"`{phone}`")
                else:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
            with cols[2]:
                if selected_fields.get("links", True) and candidate.links:
                    st.markdown("**🔗 Profile Links**")
                    links = candidate.links
                    if links.linkedin:
                        st.markdown(f"[LinkedIn]({links.linkedin})")
                    if links.github:
                        st.markdown(f"[GitHub]({links.github})")
                    if links.portfolio:
                        st.markdown(f"[Portfolio]({links.portfolio})")
                else:
                    st.markdown("&nbsp;", unsafe_allow_html=True)

    # Skills
    if selected_fields.get("skills", True) and candidate.skills:
        with st.container(border=True):
            st.markdown("#### 🛠️ Skills & Expertise")
            badges = "".join(
                render_skill_badge(s.name, s.confidence, show_confidence)
                for s in sorted(candidate.skills, key=lambda x: -x.confidence)
            )
            st.markdown(badges, unsafe_allow_html=True)

    # Experience
    if selected_fields.get("experience", True) and candidate.experience:
        with st.container(border=True):
            st.markdown("#### 💼 Work Experience")
            for idx, exp in enumerate(candidate.experience):
                with st.expander(f"**{exp.title}** at **{exp.company}**", expanded=(idx == 0)):
                    date_str = f"{exp.start_date or '?'} to {exp.end_date or 'Present'}"
                    st.markdown(f"*{date_str}*")
                    if exp.description:
                        st.write(exp.description)

    # Education
    if selected_fields.get("education", True) and candidate.education:
        with st.container(border=True):
            st.markdown("#### 🎓 Education History")
            for edu in candidate.education:
                degree_str = f"{edu.degree or ''} {edu.field_of_study or ''}".strip()
                st.markdown(f"**{edu.institution}**")
                if degree_str:
                    st.markdown(f"*{degree_str}*")
                if edu.end_date:
                    st.write(f"Graduated: {edu.end_date}")
                if edu.gpa:
                    if edu.gpa > 10.0:
                        st.write(f"Percentage: {edu.gpa}%")
                    else:
                        st.write(f"CGPA: {edu.gpa}")
                st.markdown("---")


def render_confidence_tab(candidate: CanonicalCandidate, selected_fields: dict[str, bool]) -> None:
    st.markdown("### 📊 Per-Field Confidence Scores")
    st.markdown("Confidence reflects source agreement and data quality.")
    st.markdown("<br>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    field_scores: dict[str, float] = {}
    if selected_fields.get("full_name", True) and candidate.full_name:
        field_scores["full_name"] = candidate.get_confidence_for("full_name") or 0.85
    if selected_fields.get("emails", True) and candidate.emails:
        field_scores["emails"] = 0.90
    if selected_fields.get("phones", True) and candidate.phones:
        field_scores["phones"] = 0.85
    if selected_fields.get("location", True) and candidate.location:
        field_scores["location"] = 0.80
    if selected_fields.get("headline", True) and candidate.headline:
        field_scores["headline"] = 0.80
    if selected_fields.get("skills", True) and candidate.skills:
        avg_skill_conf = sum(s.confidence for s in candidate.skills) / len(candidate.skills)
        field_scores["skills (avg)"] = avg_skill_conf
    for field, cs in candidate.confidence_scores.items():
        if field in selected_fields and not selected_fields[field]:
            continue
        field_scores[field] = cs.score

    if not field_scores:
        st.info("No confidence scores available.")
        return

    half  = len(field_scores) // 2
    items = list(field_scores.items())
    with col1:
        for label, score in items[:half]:
            st.markdown(render_confidence_bar(label, score), unsafe_allow_html=True)
    with col2:
        for label, score in items[half:]:
            st.markdown(render_confidence_bar(label, score), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class="card" style="text-align:center;">
        <div style="font-size:3em; font-weight:700; color:#6495ED;">
            {candidate.overall_confidence:.0%}
        </div>
        <div style="color:rgba(255,255,255,0.5); font-size:1em; margin-top:8px;">
            Overall Profile Confidence
        </div>
        <div style="color:rgba(255,255,255,0.3); font-size:0.8em; margin-top:4px;">
            Weighted average across {len(field_scores)} scored fields
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_merge_log_tab() -> None:
    st.markdown("### 🔀 Merge Decision Log")
    st.markdown("Every field conflict and resolution is recorded here.")
    try:
        if MERGE_LOG_PATH.exists():
            with open(MERGE_LOG_PATH, encoding="utf-8") as f:
                log_data = json.load(f)
        else:
            st.info("No merge log found. Generate a profile first.")
            return
        if not log_data:
            st.info("Merge log is empty.")
            return
        for entry in log_data:
            if not isinstance(entry, dict):
                continue
            field      = entry.get("field", "unknown")
            winner     = entry.get("winner", "—")
            confidence = entry.get("confidence", 0)
            reasoning  = entry.get("reasoning", "")
            candidates = entry.get("candidates", [])
            with st.expander(
                f"**{field}** → `{str(winner)[:60]}`  {render_confidence_badge(confidence)}",
                expanded=False,
            ):
                if reasoning:
                    st.markdown(f"**Reasoning:** {reasoning}")
                if candidates:
                    st.markdown("**Candidates considered:**")
                    for c in candidates:
                        src  = c.get("source", "?")
                        val  = c.get("value", "")
                        conf = c.get("confidence", 0)
                        badge    = render_source_badge(src)
                        selected = "✅" if str(val)[:60] == str(winner)[:60] else "❌"
                        st.markdown(
                            f"{selected} {badge} `{str(val)[:80]}` — confidence: {conf:.2f}",
                            unsafe_allow_html=True,
                        )
    except Exception as exc:
        st.error(f"Could not load merge log: {exc}")


def render_provenance_tab(candidate: CanonicalCandidate, selected_fields: dict[str, bool]) -> None:
    st.markdown("### 🔍 Provenance Trail")
    st.markdown("Every field value is traced back to its original source.")
    if not candidate.provenance:
        st.info("No provenance records available.")
        return
    fields_seen: dict[str, list] = {}
    for record in candidate.provenance:
        if record.field in selected_fields and not selected_fields[record.field]:
            continue
        fields_seen.setdefault(record.field, []).append(record)
    for field, records in sorted(fields_seen.items()):
        with st.expander(f"**{field}** ({len(records)} record(s))", expanded=False):
            for rec in records:
                badge = render_source_badge(rec.source)
                st.markdown(
                    f"{badge} **Method:** `{rec.method}`  "
                    f"**Confidence:** {rec.confidence:.2f}",
                    unsafe_allow_html=True,
                )
                if rec.raw_value is not None:
                    st.markdown(f"**Raw:** `{str(rec.raw_value)[:100]}`")
                if rec.normalized_value is not None:
                    st.markdown(f"**Normalised:** `{str(rec.normalized_value)[:100]}`")
                if rec.notes:
                    st.markdown(f"**Notes:** {rec.notes}")
                st.markdown("---")


def render_download_tab(projected: dict, candidate: CanonicalCandidate) -> None:
    st.markdown("### 📥 Download Output")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Projected Output JSON")
        projected_str = json.dumps(projected, indent=2, default=str)
        st.download_button(
            label="⬇️ Download Projected JSON",
            data=projected_str,
            file_name=f"candidate_{candidate.candidate_id[:8]}_projected.json",
            mime="application/json",
            use_container_width=True,
        )
        st.markdown('<div class="json-viewer">', unsafe_allow_html=True)
        st.json(projected, expanded=False)
        st.markdown('</div>', unsafe_allow_html=True)
    with col2:
        st.markdown("#### Full Canonical Profile JSON")
        canonical_str = candidate.model_dump_json(indent=2)
        st.download_button(
            label="⬇️ Download Canonical JSON",
            data=canonical_str,
            file_name=f"candidate_{candidate.candidate_id[:8]}_canonical.json",
            mime="application/json",
            use_container_width=True,
        )
        st.markdown('<div class="json-viewer">', unsafe_allow_html=True)
        st.json(json.loads(canonical_str), expanded=False)
        st.markdown('</div>', unsafe_allow_html=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    save_path = OUTPUT_DIR / f"candidate_{candidate.candidate_id[:8]}.json"
    write_json_file(save_path, projected)
    st.success(f"✅ Also saved to `{save_path}`")


def render_merge_explanation_tab(candidate: CanonicalCandidate, selected_fields: dict[str, bool]) -> None:
    st.markdown("### 🧠 AI Merge Explanation")
    st.markdown("Understand how and why every field in the canonical profile was merged, normalized, and selected.")
    st.markdown("<br>", unsafe_allow_html=True)

    fields_to_explain = [
        ("full_name", "👤 Full Name"),
        ("headline", "💼 Headline"),
        ("years_experience", "⏳ Years of Experience"),
        ("location", "📍 Location"),
        ("links", "🔗 Profile Links"),
        ("emails", "✉️ Emails"),
        ("phones", "📞 Phone Numbers"),
        ("skills", "🛠️ Skills"),
        ("experience", "💼 Work Experience"),
        ("education", "🎓 Education History")
    ]

    for field_key, field_name in fields_to_explain:
        if field_key in selected_fields and not selected_fields[field_key]:
            continue

        prov_records = candidate.get_provenance_for(field_key)
        final_val = getattr(candidate, field_key, None)

        if final_val is None or (isinstance(final_val, list) and not final_val):
            final_val_str = "*None*"
        elif field_key == "location" and final_val:
            parts = [p for p in [final_val.city, final_val.state, final_val.country] if p]
            final_val_str = ", ".join(parts) or final_val.raw or "*None*"
        elif field_key == "links" and final_val:
            links_dict = {k: v for k, v in final_val.model_dump().items() if v}
            final_val_str = str(links_dict) if links_dict else "*None*"
        elif field_key == "skills" and final_val:
            final_val_str = ", ".join(s.name for s in final_val[:10])
            if len(final_val) > 10:
                final_val_str += f" (+{len(final_val) - 10} more)"
        elif field_key == "experience" and final_val:
            final_val_str = f"{len(final_val)} roles: " + ", ".join(f"{e.title} @ {e.company}" for e in final_val[:3])
            if len(final_val) > 3:
                final_val_str += f" (+{len(final_val) - 3} more)"
        elif field_key == "education" and final_val:
            final_val_str = f"{len(final_val)} records: " + ", ".join(f"{edu.degree or 'Degree'} @ {edu.institution}" for edu in final_val[:2])
            if len(final_val) > 2:
                final_val_str += f" (+{len(final_val) - 2} more)"
        elif isinstance(final_val, list):
            final_val_str = ", ".join(str(x) for x in final_val)
        else:
            final_val_str = str(final_val)

        if field_key in candidate.confidence_scores:
            conf_obj = candidate.confidence_scores[field_key]
            final_score = conf_obj.score
            reasoning = conf_obj.reasoning
        elif field_key == "skills" and candidate.skills:
            final_score = sum(s.confidence for s in candidate.skills) / len(candidate.skills)
            reasoning = f"Average confidence across {len(candidate.skills)} merged skills."
        elif field_key == "experience" and candidate.experience:
            final_score = sum(e.confidence for e in candidate.experience) / len(candidate.experience)
            reasoning = f"Average extraction confidence across {len(candidate.experience)} experience records."
        elif field_key == "education" and candidate.education:
            final_score = sum(e.confidence for e in candidate.education) / len(candidate.education)
            reasoning = f"Average extraction confidence across {len(candidate.education)} education records."
        elif field_key in ("emails", "phones") and final_val:
            valid_provs = [r for r in prov_records if r.confidence > 0.20]
            if valid_provs:
                final_score = sum(r.confidence for r in valid_provs) / len(valid_provs)
            else:
                final_score = 0.20
            reasoning = f"Deduplicated and validated list. Valid values prioritized."
        else:
            final_score = 0.0
            reasoning = "No source data available."

        selected_sources = []
        if field_key in ("skills", "experience", "education"):
            selected_sources = list(set(r.source for r in prov_records))
        else:
            selected_sources = [r.source for r in prov_records if "Selected" in r.notes or r.notes == "Selected"]
            if not selected_sources and prov_records:
                selected_sources = [prov_records[0].source]

        selected_source_str = " & ".join(sorted(selected_sources)) if selected_sources else "None"

        agree_sources = set(r.source for r in prov_records if "Selected" in r.notes or r.notes == "Selected" or "Agreement" in r.notes or "Agreement" in getattr(candidate.confidence_scores.get(field_key), 'reasoning', ''))
        if not agree_sources and prov_records:
            agree_sources = {prov_records[0].source}
        if len(agree_sources) >= 3:
            agree_status = "Three-Source Agreement"
        elif len(agree_sources) == 2:
            agree_status = "Two-Source Agreement"
        elif len(agree_sources) == 1:
            agree_status = "Single Source"
        else:
            agree_status = "No Source / Empty"

        selection_reason = "No data available."
        if prov_records:
            has_invalid = any(r.confidence <= 0.20 for r in prov_records)
            has_agreement = len(agree_sources) > 1
            has_multiple = len(set(r.source for r in prov_records)) > 1

            if has_invalid and all(r.confidence <= 0.20 for r in prov_records):
                selection_reason = "Invalid value rejected / Low confidence"
            elif has_invalid:
                selection_reason = "Highest source confidence (Invalid value rejected)"
            elif has_agreement:
                selection_reason = "Source agreement after normalization"
            elif has_multiple:
                selection_reason = "Highest source confidence"
            else:
                selection_reason = "Only source available"

        conf_pct = f"{final_score:.0%}"
        header_text = f"{field_name} &nbsp;&nbsp;|&nbsp;&nbsp; Sources: **{selected_source_str}** &nbsp;&nbsp;|&nbsp;&nbsp; Confidence: **{conf_pct}**"

        with st.expander(header_text, expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Final Selected Value:**")
                if field_key == "links" and final_val:
                    if final_val.linkedin: st.markdown(f"- **LinkedIn:** {final_val.linkedin}")
                    if final_val.github: st.markdown(f"- **GitHub:** {final_val.github}")
                    if final_val.portfolio: st.markdown(f"- **Portfolio:** {final_val.portfolio}")
                    if final_val.other: st.markdown(f"- **Other:** {', '.join(final_val.other)}")
                elif field_key in ("skills", "experience", "education") and isinstance(final_val, list):
                    for idx, item in enumerate(final_val[:5]):
                        if field_key == "skills":
                            st.markdown(f"- **{item.name}** (Confidence: {item.confidence:.0%}, Sources: {', '.join(item.sources)})")
                        elif field_key == "experience":
                            st.markdown(f"- **{item.title}** @ **{item.company}** ({item.start_date or '?'} to {item.end_date or 'Present'})")
                        elif field_key == "education":
                            degree_str = f"{item.degree or ''} {item.field_of_study or ''}".strip()
                            st.markdown(f"- **{item.institution}** ({degree_str})")
                    if len(final_val) > 5:
                        st.markdown(f"*And {len(final_val) - 5} more records...*")
                else:
                    st.markdown(f"`{final_val_str}`")

                st.markdown("**Reason for Selection:**")
                st.info(selection_reason)

            with col2:
                st.markdown("**Agreement Status:**")
                st.markdown(f"`{agree_status}`")

                st.markdown("**Engine Explanation:**")
                st.write(reasoning)

            if prov_records:
                st.markdown("**Available Values from All Sources:**")
                source_data = []
                for rec in prov_records:
                    status = "Selected" if "Selected" in rec.notes or rec.notes == "Selected" else "Alternative / Overridden"
                    if rec.confidence <= 0.20:
                        status = "Rejected (Invalid Format)"
                    source_data.append({
                        "Source": rec.source,
                        "Extraction Method": rec.method,
                        "Raw Value": str(rec.raw_value)[:100] if rec.raw_value is not None else "—",
                        "Normalized Value": str(rec.normalized_value)[:100] if rec.normalized_value is not None else "—",
                        "Source Confidence": f"{rec.confidence:.0%}",
                        "Status": status
                    })
                st.table(source_data)



# ---------------------------------------------------------------------------
# Candidate output renderer (used by both modes)
# ---------------------------------------------------------------------------

def _render_candidate_output(
    canonical: CanonicalCandidate,
    errors: list,
    show_provenance: bool,
    show_confidence: bool,
    selected_fields: dict[str, bool],
    key_prefix: str = "",
) -> None:
    """Render the full output panel for a single candidate."""
    fields_to_toggle = [
        "candidate_id", "full_name", "emails", "phones", "location",
        "links", "headline", "skills", "experience", "education", "overall_confidence",
    ]

    canonical_dict = canonical.model_dump(mode="json")
    for f in fields_to_toggle:
        if not selected_fields.get(f, True):
            canonical_dict.pop(f, None)
    if not show_provenance:
        canonical_dict.pop("provenance", None)
    else:
        if "provenance" in canonical_dict and isinstance(canonical_dict["provenance"], list):
            canonical_dict["provenance"] = [
                rec for rec in canonical_dict["provenance"]
                if isinstance(rec, dict)
                and rec.get("field") in selected_fields
                and selected_fields[rec.get("field")]
            ]
    if not show_confidence or not selected_fields.get("overall_confidence", True):
        canonical_dict.pop("confidence_scores", None)
        canonical_dict.pop("overall_confidence", None)
    else:
        if "confidence_scores" in canonical_dict and isinstance(canonical_dict["confidence_scores"], dict):
            canonical_dict["confidence_scores"] = {
                k: v for k, v in canonical_dict["confidence_scores"].items()
                if k in selected_fields and selected_fields[k]
            }

    OUTPUT_DIR.mkdir(exist_ok=True)
    save_path = OUTPUT_DIR / f"candidate_{canonical.candidate_id[:8]}.json"
    write_json_file(save_path, canonical_dict)

    if errors:
        with st.expander("⚠️ Parse Warnings (non-fatal)", expanded=False):
            for err_group in errors:
                source = err_group.get("source", "?")
                for err in err_group.get("errors", []):
                    st.markdown(
                        f'<div class="alert-warning">⚠ [{source}] {err}</div>',
                        unsafe_allow_html=True,
                    )

    st.markdown("<br>", unsafe_allow_html=True)

    canonical_str = json.dumps(canonical_dict, indent=2)
    st.download_button(
        label="⬇️ Download Canonical Profile JSON",
        data=canonical_str,
        file_name=f"candidate_{canonical.candidate_id[:8]}_canonical.json",
        mime="application/json",
        use_container_width=True,
        key=f"dl_{key_prefix}_{canonical.candidate_id}",
    )

    st.markdown("<br>", unsafe_allow_html=True)

    tabs_list = ["🧑 JSON Profile", "📊 Visual Profile", "🧠 AI Merge Explanation"]
    if show_provenance:
        tabs_list.append("🔍 Provenance Trail")
    if show_confidence:
        tabs_list.append("📊 Confidence Summary")

    tabs = st.tabs(tabs_list)

    with tabs[0]:
        st.json(canonical_dict)

    with tabs[1]:
        render_canonical_visual_view(canonical, selected_fields, show_confidence)

    with tabs[2]:
        render_merge_explanation_tab(canonical, selected_fields)

    current_idx = 3
    if show_provenance:
        with tabs[current_idx]:
            render_provenance_tab(canonical, selected_fields)
        current_idx += 1

    if show_confidence:
        with tabs[current_idx]:
            render_confidence_tab(canonical, selected_fields)


# ---------------------------------------------------------------------------
# History sidebar (single-candidate mode)
# ---------------------------------------------------------------------------

def _render_history_sidebar(candidates: list) -> int:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 👥 Candidate History")
    if not candidates:
        st.sidebar.markdown(
            "<div style='color:rgba(255,255,255,0.3); font-size:0.85em;'>No candidates yet.</div>",
            unsafe_allow_html=True,
        )
        return 0
    labels      = [entry["label"] for entry in candidates]
    current_idx = st.session_state.get("active_idx", len(candidates) - 1)
    current_idx = min(current_idx, len(candidates) - 1)
    selected_label = st.sidebar.radio(
        "Select candidate to view:",
        options=labels, index=current_idx,
        key="candidate_radio",
        label_visibility="collapsed",
    )
    selected_idx = labels.index(selected_label)
    if st.sidebar.button("🗑️ Clear History", use_container_width=True, key="clear_history"):
        st.session_state.candidates = []
        st.session_state.active_idx = 0
        st.rerun()
    return selected_idx


# ---------------------------------------------------------------------------
# ZIP builder
# ---------------------------------------------------------------------------

def _build_zip(batch_results: list) -> bytes:
    """Build an in-memory ZIP of all successful canonical profiles."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for result in batch_results:
            if result["status"] != "ok":
                continue
            canonical: CanonicalCandidate = result["canonical"]
            filename = f"candidate_{canonical.candidate_id[:8]}_{canonical.full_name or 'unknown'}.json"
            filename = filename.replace(" ", "_").replace("/", "-")
            zf.writestr(filename, canonical.model_dump_json(indent=2))
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Batch results dashboard
# ---------------------------------------------------------------------------

def _render_batch_dashboard(
    batch_results: list,
    show_provenance: bool,
    show_confidence: bool,
    selected_fields: dict[str, bool],
) -> None:
    """Render the Batch Results Dashboard."""
    ok_count    = sum(1 for r in batch_results if r["status"] == "ok")
    err_count   = sum(1 for r in batch_results if r["status"] == "error")
    total_count = len(batch_results)

    # Summary header
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        st.metric("Total Processed", total_count)
    with col_b:
        st.metric("✅ Successful", ok_count)
    with col_c:
        st.metric("❌ Failed", err_count)
    with col_d:
        avg_conf = (
            sum(r["canonical"].overall_confidence for r in batch_results if r["status"] == "ok") / ok_count
            if ok_count > 0 else 0.0
        )
        st.metric("Avg Confidence", f"{avg_conf:.0%}")

    st.markdown("<br>", unsafe_allow_html=True)

    # Download all ZIP
    if ok_count > 0:
        zip_bytes = _build_zip(batch_results)
        st.download_button(
            label=f"📦 Download All {ok_count} Profiles as ZIP",
            data=zip_bytes,
            file_name="batch_candidate_profiles.zip",
            mime="application/zip",
            use_container_width=True,
            key="dl_all_zip",
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📋 Batch Results")
    st.markdown("Select a candidate below to view their full profile.")

    skipped_results = [r for r in batch_results if r["status"] == "skipped"]
    if skipped_results:
        st.warning("⚠️ Some candidates were skipped due to missing required inputs:")
        for r in skipped_results:
            name = r["label"].split(" · ")[1].replace(" (Skipped)", "") if " · " in r["label"] else f"Candidate {r['index'] + 1}"
            st.markdown(f"- **{name}** (Slot {r['index'] + 1}): {r['error_msg']}")

    # Candidate table header
    hdr_cols = st.columns([0.4, 2, 1.2, 1, 1, 0.8])
    with hdr_cols[0]: st.markdown("**#**")
    with hdr_cols[1]: st.markdown("**Name**")
    with hdr_cols[2]: st.markdown("**Candidate ID**")
    with hdr_cols[3]: st.markdown("**Confidence**")
    with hdr_cols[4]: st.markdown("**Sources**")
    with hdr_cols[5]: st.markdown("**Status**")
    st.markdown("---")

    # One row per result
    if "batch_selected_idx" not in st.session_state:
        st.session_state.batch_selected_idx = 0

    for i, result in enumerate(batch_results):
        row_cols = st.columns([0.4, 2, 1.2, 1, 1, 0.8])

        if result["status"] == "ok":
            canonical = result["canonical"]
            name      = canonical.full_name or "Unknown"
            short_id  = canonical.candidate_id[:12]
            conf_str  = f"{canonical.overall_confidence:.0%}"
            # Detect which sources were used via provenance
            sources_used = set()
            for rec in canonical.provenance:
                sources_used.add(rec.source)
            source_str = " · ".join(sorted(sources_used)) if sources_used else "—"
            status_html = '<span class="batch-status-ok">✅ OK</span>'
        elif result["status"] == "skipped":
            name = result["label"].split(" · ")[1].replace(" (Skipped)", "") if " · " in result["label"] else f"Candidate {result['index'] + 1}"
            short_id  = "—"
            conf_str  = "—"
            source_str = "—"
            status_html = f'<span class="batch-status-warning" style="color:#FFA500; font-weight:600;" title="{result["error_msg"]}">⚠️ Skipped</span>'
        else:
            name      = f"Slot {result['index'] + 1}"
            short_id  = "—"
            conf_str  = "—"
            source_str = "—"
            status_html = '<span class="batch-status-error">❌ Error</span>'

        with row_cols[0]:
            st.markdown(f"**{i + 1}**")
        with row_cols[1]:
            st.markdown(name)
        with row_cols[2]:
            st.markdown(f"`{short_id}`")
        with row_cols[3]:
            st.markdown(conf_str)
        with row_cols[4]:
            st.markdown(source_str)
        with row_cols[5]:
            st.markdown(status_html, unsafe_allow_html=True)

        if result["status"] == "ok":
            if st.button(
                "View Profile",
                key=f"view_batch_{i}",
                use_container_width=True,
            ):
                st.session_state.batch_selected_idx = i
                st.rerun()

        st.markdown("---")

    # ── Detailed view for selected candidate ──────────────────────────────
    selected_idx = st.session_state.get("batch_selected_idx", 0)
    selected_idx = min(selected_idx, len(batch_results) - 1)

    if batch_results and batch_results[selected_idx]["status"] == "ok":
        selected = batch_results[selected_idx]
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            f"<div style='display:flex; align-items:center; gap:12px; margin-bottom:8px;'>"
            f"<span style='background:rgba(100,149,237,0.2); border:1px solid rgba(100,149,237,0.4);"
            f"border-radius:20px; padding:4px 14px; font-size:0.9em; color:#A8C4FF;'>"
            f"👤 Viewing: {selected['label']}</span>"
            f"<span style='color:rgba(255,255,255,0.35); font-size:0.85em;'>"
            f"Batch result {selected_idx + 1} of {len(batch_results)}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _render_candidate_output(
            canonical=selected["canonical"],
            errors=selected["errors"],
            show_provenance=show_provenance,
            show_confidence=show_confidence,
            selected_fields=selected_fields,
            key_prefix=f"batch_{selected_idx}",
        )
    elif batch_results and batch_results[selected_idx]["status"] == "error":
        st.error(f"❌ {batch_results[selected_idx]['error_msg']}")


# ---------------------------------------------------------------------------
# Cached service
# ---------------------------------------------------------------------------

@st.cache_resource
def get_transformer_service() -> TransformerService:
    """Returns a cached singleton TransformerService — loaded once per process."""
    return TransformerService()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Hero header
    st.markdown("""
    <div style="text-align:center; padding: 20px 0 10px 0;">
        <h1 class="gradient-text" style="font-size:2.5em; margin-bottom:8px;">
            🎯 Candidate Profile Transformer
        </h1>
        <p style="color:rgba(255,255,255,0.5); font-size:1.1em; max-width:700px; margin: 0 auto;">
            Transform raw ATS data, scanned resumes, and GitHub profiles into
            a single trusted canonical candidate record — one or many at a time.
        </p>
    </div>
    <br>
    """, unsafe_allow_html=True)

    # ── Session state bootstrap ────────────────────────────────────────────
    if "candidates" not in st.session_state:
        st.session_state.candidates = []
    if "active_idx" not in st.session_state:
        st.session_state.active_idx = 0
    if "batch_results" not in st.session_state:
        st.session_state.batch_results = []
    if "batch_selected_idx" not in st.session_state:
        st.session_state.batch_selected_idx = 0
    if "app_mode" not in st.session_state:
        st.session_state.app_mode = "Single Candidate"

    # ── Mode toggle (top of sidebar) ──────────────────────────────────────
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center; padding: 20px 0 10px 0;">
            <div style="font-size: 2.5em;">🎯</div>
            <h2 class="gradient-text" style="margin:0; font-size:1.3em;">TalentFusion</h2>
            <p style="color:rgba(255,255,255,0.4); font-size:0.8em; margin-top:6px;">
                Multi-Source Profile Builder
            </p>
        </div>
        <hr style="border-color: rgba(255,255,255,0.08); margin-bottom:16px;">
        """, unsafe_allow_html=True)

        st.markdown("#### ⚡ Processing Mode")
        mode = st.radio(
            "Mode",
            options=["Single Candidate", "Batch Mode"],
            index=0 if st.session_state.app_mode == "Single Candidate" else 1,
            key="mode_radio",
            horizontal=True,
            label_visibility="collapsed",
        )
        st.session_state.app_mode = mode

        # Mode pill
        if mode == "Single Candidate":
            st.markdown('<span class="mode-pill mode-single">🔹 Single</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="mode-pill mode-batch">🔸 Batch</span>', unsafe_allow_html=True)

        st.markdown("<hr style='border-color:rgba(255,255,255,0.06); margin:12px 0;'>", unsafe_allow_html=True)

    # ── Mode-specific sidebar + logic ─────────────────────────────────────
    if mode == "Single Candidate":
        # ── Single mode ───────────────────────────────────────────────────
        ats_data, resume_bytes, github_url, show_provenance, show_confidence, selected_fields, generate = (
            _render_single_sidebar()
        )

        active_idx = _render_history_sidebar(st.session_state.candidates)
        st.session_state.active_idx = active_idx

        if generate:
            missing = []
            if not ats_data:
                st.error("❌ ATS JSON is required.")
                missing.append("ATS JSON")
            if not resume_bytes:
                st.error("❌ Resume PDF is required.")
                missing.append("Resume PDF")
            if not github_url or not github_url.strip():
                st.error("❌ GitHub Profile URL is required.")
                missing.append("GitHub Profile URL")

            if missing:
                st.error("❌ Please provide all three input sources to generate the canonical profile.")
                return

            with st.spinner("🔄 Processing — parsing, normalising, and merging your data..."):
                try:
                    if resume_bytes:
                        try:
                            with open(ROOT / "uploaded_resume.pdf", "wb") as fp:
                                fp.write(resume_bytes)
                        except Exception as e:
                            logging.error("Failed to write uploaded_resume.pdf: %s", e)
                    if ats_data:
                        try:
                            with open(ROOT / "uploaded_ats.json", "w") as fp:
                                json.dump(ats_data, fp, indent=2)
                        except Exception as e:
                            logging.error("Failed to write uploaded_ats.json: %s", e)

                    service    = get_transformer_service()
                    resume_io  = io.BytesIO(resume_bytes) if resume_bytes else None
                    canonical, _projected, errors = service.transform(
                        ats_data=ats_data,
                        resume_source=resume_io,
                        github_url=github_url,
                        output_config=None,
                    )

                    run_num  = len(st.session_state.candidates) + 1
                    name     = canonical.full_name or "Unknown"
                    short_id = canonical.candidate_id[:8]
                    label    = f"#{run_num} · {name} ({short_id})"

                    st.session_state.candidates.append({
                        "label":     label,
                        "canonical": canonical,
                        "errors":    errors,
                    })
                    st.session_state.active_idx = len(st.session_state.candidates) - 1
                    st.rerun()

                except Exception as exc:
                    st.error(f"❌ Pipeline error: {exc}")
                    return

        if st.session_state.candidates:
            active    = st.session_state.candidates[st.session_state.active_idx]
            canonical = active["canonical"]
            errors    = active["errors"]
            total     = len(st.session_state.candidates)
            idx       = st.session_state.active_idx

            st.markdown(
                f"<div style='display:flex; align-items:center; gap:12px; margin-bottom:8px;'>"
                f"<span style='background:rgba(100,149,237,0.2); border:1px solid rgba(100,149,237,0.4);"
                f"border-radius:20px; padding:4px 14px; font-size:0.9em; color:#A8C4FF;'>"
                f"👤 Viewing: {active['label']}</span>"
                f"<span style='color:rgba(255,255,255,0.35); font-size:0.85em;'>"
                f"{total} candidate{'s' if total != 1 else ''} in session</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            _render_candidate_output(
                canonical=canonical,
                errors=errors,
                show_provenance=show_provenance,
                show_confidence=show_confidence,
                selected_fields=selected_fields,
                key_prefix=f"single_{idx}",
            )
        else:
            st.markdown("""
            <div style="text-align:center; padding: 80px 0;">
                <div style="font-size:4em; margin-bottom:16px;">🧬</div>
                <h3 style="color:rgba(255,255,255,0.4); font-weight:400;">
                    Upload your data sources and click Generate Profile
                </h3>
                <p style="color:rgba(255,255,255,0.25); font-size:0.9em;">
                    ATS JSON · Scanned Resume PDF · GitHub Profile URL
                </p>
            </div>
            """, unsafe_allow_html=True)

    else:
        # ── Batch mode ────────────────────────────────────────────────────
        ats_list, resume_list, github_list, show_provenance, show_confidence, selected_fields, run_batch_btn = (
            _render_batch_sidebar()
        )

        # Clear batch history from sidebar
        with st.sidebar:
            st.markdown("---")
            if st.session_state.batch_results:
                st.markdown(
                    f"<div style='color:rgba(255,255,255,0.4); font-size:0.82em;'>"
                    f"Last batch: {len(st.session_state.batch_results)} result(s)</div>",
                    unsafe_allow_html=True,
                )
            if st.button("🗑️ Clear Batch Results", use_container_width=True, key="clear_batch"):
                st.session_state.batch_results = []
                st.session_state.batch_selected_idx = 0
                st.rerun()

            st.markdown("""
            <hr style="border-color:rgba(255,255,255,0.08); margin-top:24px;">
            <div style="color:rgba(255,255,255,0.3); font-size:0.75em; text-align:center;">
                EightFold AI · Internship Assignment<br>
                Multi-Source TalentFusion
            </div>
            """, unsafe_allow_html=True)

        if run_batch_btn:
            n_total = len(ats_list)
            # Build slots
            slots: list[CandidateSlot] = [
                CandidateSlot(
                    ats_data=ats_list[i] if ats_list[i] else None,
                    resume_bytes=resume_list[i],
                    github_url=github_list[i],
                )
                for i in range(n_total)
            ]
            import logging
            logging.info("Batch execution slots: %s", [{k: (type(v) if k == 'resume_bytes' and v else v) for k, v in slot.items()} for slot in slots])

            service  = get_transformer_service()
            progress = st.progress(0, text="Starting batch...")
            status_placeholder = st.empty()

            results_accumulator: list = []

            def on_progress(done: int, total: int, label: str) -> None:
                pct = int((done / total) * 100)
                progress.progress(pct, text=f"Processing {label} ({done}/{total})...")
                status_placeholder.markdown(
                    f"<div style='color:rgba(255,255,255,0.5); font-size:0.9em;'>"
                    f"⚙️ {label}</div>",
                    unsafe_allow_html=True,
                )

            with st.spinner(f"🔄 Running batch — {n_total} candidate(s)..."):
                batch_results = run_batch(service, slots, on_progress=on_progress)

            progress.progress(100, text="✅ Batch complete!")
            status_placeholder.empty()

            st.session_state.batch_results = batch_results
            st.session_state.batch_selected_idx = 0
            st.rerun()

        # Show batch dashboard if results exist
        if st.session_state.batch_results:
            _render_batch_dashboard(
                batch_results=st.session_state.batch_results,
                show_provenance=show_provenance,
                show_confidence=show_confidence,
                selected_fields=selected_fields,
            )
        else:
            st.markdown("""
            <div style="text-align:center; padding: 80px 0;">
                <div style="font-size:4em; margin-bottom:16px;">🗂️</div>
                <h3 style="color:rgba(255,255,255,0.4); font-weight:400;">
                    Batch Mode — Process Multiple Candidates at Once
                </h3>
                <p style="color:rgba(255,255,255,0.3); font-size:0.95em; max-width:520px; margin:0 auto;">
                    Upload multiple ATS JSONs, Resume PDFs, and/or GitHub URLs.<br>
                    Files are matched <strong style="color:rgba(255,255,255,0.55);">by index order</strong>:
                    ATS[0] + Resume[0] + GitHub[0] → Candidate 1, and so on.
                </p>
                <br>
                <div style="display:flex; justify-content:center; gap:24px; flex-wrap:wrap; margin-top:16px;">
                    <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08);
                                border-radius:12px; padding:16px 24px; min-width:160px;">
                        <div style="font-size:1.8em;">📋</div>
                        <div style="color:rgba(255,255,255,0.6); font-size:0.9em; margin-top:6px;">
                            Multiple ATS JSONs
                        </div>
                    </div>
                    <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08);
                                border-radius:12px; padding:16px 24px; min-width:160px;">
                        <div style="font-size:1.8em;">📄</div>
                        <div style="color:rgba(255,255,255,0.6); font-size:0.9em; margin-top:6px;">
                            Multiple Resume PDFs
                        </div>
                    </div>
                    <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08);
                                border-radius:12px; padding:16px 24px; min-width:160px;">
                        <div style="font-size:1.8em;">🐙</div>
                        <div style="color:rgba(255,255,255,0.6); font-size:0.9em; margin-top:6px;">
                            GitHub URLs (one per line)
                        </div>
                    </div>
                    <div style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08);
                                border-radius:12px; padding:16px 24px; min-width:160px;">
                        <div style="font-size:1.8em;">📦</div>
                        <div style="color:rgba(255,255,255,0.6); font-size:0.9em; margin-top:6px;">
                            ZIP Download All
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
