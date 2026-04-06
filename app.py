"""
CV Tailor — AI-powered CV customisation for job applications.
Run with: streamlit run app.py
"""
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent import CVTailorAgent
from pdf_utils import extract_cv_text, generate_cv_pdf

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
PROFILE_FILE = DATA_DIR / "profile.json"
BASE_CV_FILE = DATA_DIR / "base_cv.pdf"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CV Tailor",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
    /* Global */
    .main { padding-top: 1.5rem; }
    h1 { font-size: 1.9rem !important; }
    h2 { font-size: 1.3rem !important; }
    h3 { font-size: 1.05rem !important; }

    /* Score badge */
    .ats-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 84px;
        height: 84px;
        border-radius: 50%;
        font-size: 1.7rem;
        font-weight: 800;
        color: white;
        margin-bottom: 4px;
    }
    .score-high   { background: linear-gradient(135deg,#1e7e34,#28a745); }
    .score-medium { background: linear-gradient(135deg,#856404,#ffc107); }
    .score-low    { background: linear-gradient(135deg,#721c24,#dc3545); }

    /* Keyword tags */
    .tag {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.78rem;
        margin: 2px 3px;
        font-weight: 500;
    }
    .tag-green  { background:#d4edda; color:#155724; border:1px solid #c3e6cb; }
    .tag-red    { background:#f8d7da; color:#721c24; border:1px solid #f5c6cb; }
    .tag-blue   { background:#cce5ff; color:#004085; border:1px solid #b8daff; }

    /* Card */
    .result-card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
        border-left: 4px solid #4A90D9;
    }

    /* Download button */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #1A3A5C, #4A90D9) !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 0.55rem 1.4rem !important;
    }
    .stDownloadButton > button:hover {
        opacity: 0.92 !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ── Profile helpers ───────────────────────────────────────────────────────────

def load_profile() -> dict:
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_profile(profile: dict) -> None:
    PROFILE_FILE.write_text(json.dumps(profile, indent=2))


def has_base_cv() -> bool:
    return BASE_CV_FILE.exists()


# ── Score helpers ─────────────────────────────────────────────────────────────

def score_class(score: int) -> str:
    if score >= 75:
        return "score-high"
    if score >= 55:
        return "score-medium"
    return "score-low"


def score_label(score: int) -> str:
    if score >= 85:
        return "Excellent match"
    if score >= 75:
        return "Strong match"
    if score >= 60:
        return "Good match"
    if score >= 45:
        return "Fair match"
    return "Weak match — consider upskilling"


# ── Header ────────────────────────────────────────────────────────────────────
col_logo, col_title = st.columns([1, 8])
with col_logo:
    st.markdown("## 📄")
with col_title:
    st.markdown("## CV Tailor &nbsp; — &nbsp; AI-Powered Application Optimiser")

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_tailor, tab_profile = st.tabs(["🎯 &nbsp; Tailor My CV", "👤 &nbsp; My Profile"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — TAILOR CV
# ═══════════════════════════════════════════════════════════════════════════════
with tab_tailor:
    profile = load_profile()
    cv_ready = has_base_cv()

    # ── Setup nudge ───────────────────────────────────────────────────────────
    if not profile or not cv_ready:
        st.info(
            "👋 **First time here?** Head to the **My Profile** tab to upload your CV "
            "and fill in your details — it only takes a minute.",
            icon="ℹ️",
        )

    # ── Inputs ────────────────────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.subheader("Job Details")
        job_title = st.text_input("Job Title", placeholder="e.g. Senior Product Manager")
        company = st.text_input("Company (optional)", placeholder="e.g. Stripe")
        job_description = st.text_area(
            "Job Description *",
            height=340,
            placeholder="Paste the full job description here…",
        )

    with col_right:
        st.subheader("Your CV")
        cv_option = st.radio(
            "Which CV to use?",
            options=["Use saved base CV", "Upload a different PDF for this application"],
            horizontal=True,
            disabled=not cv_ready,
        )

        uploaded_cv = None
        if cv_option == "Upload a different PDF for this application" or not cv_ready:
            uploaded_cv = st.file_uploader(
                "Upload CV (PDF)",
                type=["pdf"],
                help="Upload a text-based PDF (not a scanned image).",
            )

        st.markdown("")
        tailor_btn = st.button(
            "✨ &nbsp; Tailor My CV",
            type="primary",
            use_container_width=True,
            disabled=(not job_description.strip()),
        )

    # ── Run ───────────────────────────────────────────────────────────────────
    if tailor_btn:
        # Resolve CV source
        cv_path = None
        tmp_file = None

        if uploaded_cv:
            tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp_file.write(uploaded_cv.read())
            tmp_file.close()
            cv_path = tmp_file.name
        elif cv_ready:
            cv_path = str(BASE_CV_FILE)
        else:
            st.error("Please upload your CV before continuing.")
            st.stop()

        if not job_description.strip():
            st.error("Please paste the job description.")
            st.stop()

        # Check API key
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.error(
                "ANTHROPIC_API_KEY not set. Create a `.env` file with your key "
                "(see `.env.example`) and restart the app."
            )
            st.stop()

        # Extract CV text
        with st.spinner("Reading your CV…"):
            try:
                cv_text = extract_cv_text(cv_path)
            except Exception as e:
                st.error(f"Could not read PDF: {e}")
                if tmp_file:
                    Path(tmp_file.name).unlink(missing_ok=True)
                st.stop()

        # Call Claude
        with st.spinner("Analysing job description and tailoring your CV…  (this takes ~30–60 s)"):
            try:
                agent = CVTailorAgent()
                result = agent.tailor_cv(
                    cv_text=cv_text,
                    job_description=job_description,
                    user_profile=profile,
                    job_title=job_title,
                    company=company,
                )
            except Exception as e:
                st.error(f"Tailoring failed: {e}")
                if tmp_file:
                    Path(tmp_file.name).unlink(missing_ok=True)
                st.stop()

        # Generate PDF
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_company = "".join(c for c in company if c.isalnum() or c in "-_")[:20]
        output_filename = f"CV_{safe_company or 'tailored'}_{timestamp}.pdf"
        output_path = str(OUTPUT_DIR / output_filename)

        with st.spinner("Generating PDF…"):
            try:
                generate_cv_pdf(result.cv.model_dump(), output_path)
            except Exception as e:
                st.error(f"PDF generation failed: {e}")
                if tmp_file:
                    Path(tmp_file.name).unlink(missing_ok=True)
                st.stop()

        if tmp_file:
            Path(tmp_file.name).unlink(missing_ok=True)

        # ── Results ───────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### ✅ CV Tailored Successfully")

        # Score + download row
        r1, r2, r3 = st.columns([1.2, 2.5, 2.5])

        with r1:
            cls = score_class(result.ats_score)
            st.markdown(
                f'<div class="ats-badge {cls}">{result.ats_score}</div>'
                f'<div style="font-size:0.78rem;color:#555;text-align:center">'
                f'<b>ATS Score</b><br>{score_label(result.ats_score)}</div>',
                unsafe_allow_html=True,
            )

        with r2:
            st.markdown("**Keywords incorporated**")
            tags = "".join(
                f'<span class="tag tag-green">{kw}</span>'
                for kw in result.keywords_incorporated
            )
            st.markdown(tags or "_None detected_", unsafe_allow_html=True)

        with r3:
            st.markdown("**Skills gap (in JD, not in CV)**")
            if result.missing_skills:
                tags = "".join(
                    f'<span class="tag tag-red">{s}</span>'
                    for s in result.missing_skills
                )
                st.markdown(tags, unsafe_allow_html=True)
            else:
                st.success("No significant gaps detected!")

        st.markdown("")

        # Download
        with open(output_path, "rb") as f:
            st.download_button(
                label="⬇️  Download Tailored CV (PDF)",
                data=f.read(),
                file_name=output_filename,
                mime="application/pdf",
                use_container_width=False,
            )

        # Details expanders
        col_a, col_b = st.columns(2)

        with col_a:
            with st.expander("📝 Changes made", expanded=True):
                for change in result.changes_summary:
                    st.markdown(f"- {change}")

        with col_b:
            with st.expander("⭐ Why you're a strong match", expanded=True):
                for highlight in result.match_highlights:
                    st.markdown(f"- {highlight}")

        with st.expander("👁️ Preview tailored summary"):
            summary = result.cv.summary
            st.markdown(
                f'<div class="result-card">{summary}</div>',
                unsafe_allow_html=True,
            )

        with st.expander("🛠️ Full skills list (as ordered in CV)"):
            st.markdown(", ".join(result.cv.skills))


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — PROFILE SETUP
# ═══════════════════════════════════════════════════════════════════════════════
with tab_profile:
    st.subheader("Your Professional Profile")
    st.markdown(
        "This is saved locally and sent to Claude with every tailoring request, "
        "so it understands your background and goals without you repeating yourself."
    )

    profile = load_profile()

    # ── Base CV upload ────────────────────────────────────────────────────────
    with st.expander("📎 &nbsp; Upload Base CV (PDF)", expanded=not has_base_cv()):
        if has_base_cv():
            st.success(f"✅ Base CV saved: `{BASE_CV_FILE}`")
            if st.button("Replace CV"):
                BASE_CV_FILE.unlink(missing_ok=True)
                st.rerun()
        else:
            new_cv = st.file_uploader("Upload your CV (PDF)", type=["pdf"], key="profile_cv")
            if new_cv:
                with open(BASE_CV_FILE, "wb") as f:
                    f.write(new_cv.read())
                st.success("CV saved!")
                st.rerun()

    st.markdown("---")

    # ── Personal info ─────────────────────────────────────────────────────────
    st.markdown("#### 👤 Personal Info")
    c1, c2 = st.columns(2)
    with c1:
        p_name = st.text_input("Full Name", value=profile.get("name", ""))
        p_title = st.text_input("Current / Most Recent Job Title", value=profile.get("current_title", ""))
        p_email = st.text_input("Email", value=profile.get("email", ""))
    with c2:
        p_phone = st.text_input("Phone", value=profile.get("phone", ""))
        p_linkedin = st.text_input("LinkedIn URL", value=profile.get("linkedin", ""))
        p_location = st.text_input("Location (City, Country)", value=profile.get("location", ""))

    # ── Background ────────────────────────────────────────────────────────────
    st.markdown("#### 💼 Professional Background")
    p_background = st.text_area(
        "Brief background narrative",
        value=profile.get("background", ""),
        height=120,
        placeholder=(
            "e.g. I'm a product manager with 6 years of experience in B2B SaaS, "
            "specialising in growth and monetisation. I've led cross-functional teams "
            "of up to 12 people and shipped products used by 500k+ users."
        ),
    )
    p_years = st.number_input(
        "Years of professional experience",
        min_value=0,
        max_value=50,
        value=int(profile.get("years_experience", 0)),
    )

    # ── Job search goals ──────────────────────────────────────────────────────
    st.markdown("#### 🎯 What You're Looking For")
    c3, c4 = st.columns(2)
    with c3:
        p_target_roles = st.text_input(
            "Target job titles (comma-separated)",
            value=profile.get("target_roles", ""),
            placeholder="e.g. Senior Product Manager, Group Product Manager",
        )
        p_industries = st.text_input(
            "Preferred industries",
            value=profile.get("industries", ""),
            placeholder="e.g. FinTech, SaaS, HealthTech",
        )
    with c4:
        p_seniority = st.selectbox(
            "Target seniority level",
            ["", "Junior", "Mid-level", "Senior", "Lead", "Manager", "Director", "VP", "C-Level"],
            index=(
                ["", "Junior", "Mid-level", "Senior", "Lead", "Manager", "Director", "VP", "C-Level"].index(
                    profile.get("seniority", "")
                )
                if profile.get("seniority", "") in ["", "Junior", "Mid-level", "Senior", "Lead", "Manager", "Director", "VP", "C-Level"]
                else 0
            ),
        )
        p_remote = st.selectbox(
            "Work preference",
            ["", "Remote", "Hybrid", "On-site", "Flexible"],
            index=(
                ["", "Remote", "Hybrid", "On-site", "Flexible"].index(profile.get("remote", ""))
                if profile.get("remote", "") in ["", "Remote", "Hybrid", "On-site", "Flexible"]
                else 0
            ),
        )

    # ── Key skills ────────────────────────────────────────────────────────────
    st.markdown("#### 🔧 Core Skills & Expertise")
    p_skills = st.text_area(
        "Your strongest skills (comma-separated or one per line)",
        value=profile.get("key_skills", ""),
        height=80,
        placeholder="e.g. Product Strategy, Roadmapping, SQL, Figma, Agile, Stakeholder Management",
    )

    # ── Achievements ──────────────────────────────────────────────────────────
    st.markdown("#### 🏆 Notable Achievements")
    p_achievements = st.text_area(
        "Key achievements to highlight (helps Claude emphasise the right things)",
        value=profile.get("achievements", ""),
        height=100,
        placeholder=(
            "e.g.\n"
            "• Launched mobile app that reached 1M downloads in 6 months\n"
            "• Increased ARR by 40% through pricing strategy overhaul\n"
            "• Built and scaled a team from 3 to 18 engineers"
        ),
    )

    # ── Extra context ─────────────────────────────────────────────────────────
    p_extra = st.text_area(
        "Anything else Claude should know about you (optional)",
        value=profile.get("extra_context", ""),
        height=70,
        placeholder="e.g. I'm relocating to London in 3 months. I'm looking for sponsorship-friendly companies.",
    )

    # ── Save ──────────────────────────────────────────────────────────────────
    st.markdown("")
    if st.button("💾 &nbsp; Save Profile", type="primary"):
        new_profile = {
            "name": p_name,
            "email": p_email,
            "phone": p_phone,
            "linkedin": p_linkedin,
            "location": p_location,
            "current_title": p_title,
            "years_experience": p_years,
            "background": p_background,
            "target_roles": p_target_roles,
            "industries": p_industries,
            "seniority": p_seniority,
            "remote": p_remote,
            "key_skills": p_skills,
            "achievements": p_achievements,
            "extra_context": p_extra,
        }
        save_profile(new_profile)
        st.success("✅ Profile saved! Head to the **Tailor My CV** tab to get started.")


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div style="text-align:center;font-size:0.75rem;color:#999">'
    "CV Tailor &nbsp;•&nbsp; Powered by Claude Opus 4.6 &nbsp;•&nbsp; "
    "All data stays on your machine"
    "</div>",
    unsafe_allow_html=True,
)
