"""
PDF utilities: extract text from PDF, generate ATS-friendly CV PDF.
"""
from pathlib import Path

import pdfplumber
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER


# ── PDF Reading ───────────────────────────────────────────────────────────────

def extract_cv_text(pdf_path: str) -> str:
    """Extract all text from a PDF, preserving line structure."""
    text_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        raise RuntimeError(f"Could not read PDF: {e}") from e

    if not text_parts:
        raise ValueError(
            "The PDF appears to be empty or image-based (scanned). "
            "Please use a text-based PDF."
        )
    return "\n\n".join(text_parts)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape HTML special characters for ReportLab paragraphs."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ACCENT   = HexColor("#1A3A5C")
_BLUE     = HexColor("#4A90D9")
_MUTED    = HexColor("#555555")
_RULE_LT  = HexColor("#D0D8E4")


def _build_styles(fs: float) -> dict:
    """
    Build paragraph styles scaled by `fs` (base font size).
    Reducing `fs` shrinks everything proportionally.
    """
    return {
        "name": ParagraphStyle(
            "Name",
            fontName="Helvetica-Bold",
            fontSize=fs + 7,
            alignment=TA_CENTER,
            spaceAfter=2,
            textColor=_ACCENT,
        ),
        "contact": ParagraphStyle(
            "Contact",
            fontName="Helvetica",
            fontSize=fs - 1,
            alignment=TA_CENTER,
            spaceAfter=0,
            textColor=_MUTED,
        ),
        "section": ParagraphStyle(
            "Section",
            fontName="Helvetica-Bold",
            fontSize=fs - 0.5,
            spaceBefore=7,
            spaceAfter=2,
            textColor=_ACCENT,
        ),
        "job_header": ParagraphStyle(
            "JobHeader",
            fontName="Helvetica-Bold",
            fontSize=fs,
            spaceBefore=5,
            spaceAfter=1,
        ),
        "job_meta": ParagraphStyle(
            "JobMeta",
            fontName="Helvetica-Oblique",
            fontSize=fs - 1,
            spaceAfter=2,
            textColor=_MUTED,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            fontName="Helvetica",
            fontSize=fs,
            leftIndent=12,
            spaceAfter=1,
            leading=fs + 3,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=fs,
            spaceAfter=2,
            leading=fs + 3,
        ),
        "company_header": ParagraphStyle(
            "CompanyHeader",
            fontName="Helvetica-Bold",
            fontSize=fs,
            spaceBefore=6,
            spaceAfter=1,
            textColor=_ACCENT,
        ),
        "role_title": ParagraphStyle(
            "RoleTitle",
            fontName="Helvetica-Bold",
            fontSize=fs,
            spaceBefore=4,
            spaceAfter=1,
            leftIndent=0,
        ),
        "skills": ParagraphStyle(
            "Skills",
            fontName="Helvetica",
            fontSize=fs,
            spaceAfter=2,
            leading=fs + 4,
        ),
    }


def _section_header(title: str, st: dict) -> list:
    return [
        Paragraph(title.upper(), st["section"]),
        HRFlowable(width="100%", thickness=1, color=_BLUE, spaceAfter=3),
    ]


def _build_story(cv_data: dict, st: dict) -> list:
    """Assemble the ReportLab story from cv_data using the given styles."""
    story = []

    # ── Header: name then contact on separate line ────────────────────────────
    contact = cv_data.get("contact", {})
    name = contact.get("name", "").strip()
    if name:
        story.append(Paragraph(_esc(name), st["name"]))

    parts = [
        contact.get("email", ""),
        contact.get("phone", ""),
        contact.get("location", ""),
        contact.get("linkedin", ""),
        contact.get("website", ""),
    ]
    contact_line = "  \u2022  ".join(_esc(p) for p in parts if p)
    if contact_line:
        story.append(Spacer(1, 3))
        story.append(Paragraph(contact_line, st["contact"]))

    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_ACCENT, spaceAfter=4))

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = cv_data.get("summary", "").strip()
    if summary:
        story += _section_header("Professional Summary", st)
        story.append(Paragraph(_esc(summary), st["body"]))

    # ── Experience ────────────────────────────────────────────────────────────
    experience = cv_data.get("experience", [])
    if experience:
        story += _section_header("Professional Experience", st)
        for exp in experience:
            company  = _esc(exp.get("company", ""))
            dates    = _esc(exp.get("dates", ""))
            location = _esc(exp.get("location", ""))

            # Company header: Company | Location | Dates
            company_parts = [p for p in [company, location, dates] if p]
            story.append(Paragraph("  |  ".join(company_parts), st["company_header"]))

            roles = exp.get("roles", [])
            multi_role = len(roles) > 1
            for role in roles:
                title      = _esc(role.get("job_title", ""))
                role_dates = _esc(role.get("dates", ""))

                # Role title: "Job Title | Dates" for multi-role, "Job Title" for single
                if multi_role and role_dates:
                    story.append(Paragraph(f"<b>{title}</b>  |  <i>{role_dates}</i>", st["role_title"]))
                else:
                    story.append(Paragraph(f"<b>{title}</b>", st["role_title"]))

                for bullet in role.get("bullets", [])[:3]:
                    story.append(Paragraph(f"&#8226;  {_esc(bullet)}", st["bullet"]))

    # ── Education ─────────────────────────────────────────────────────────────
    education = cv_data.get("education", [])
    if education:
        story += _section_header("Education", st)
        for edu in education:
            degree      = _esc(edu.get("degree", ""))
            institution = _esc(edu.get("institution", ""))
            dates       = _esc(edu.get("dates", ""))

            # All inline: Degree (bold) | Institution | Year
            edu_parts = [p for p in [institution, dates] if p]
            suffix = "  |  " + "  |  ".join(edu_parts) if edu_parts else ""
            story.append(Paragraph(f"<b>{degree}</b>{suffix}", st["body"]))

    # ── Skills ────────────────────────────────────────────────────────────────
    skills = cv_data.get("skills", [])[:12]   # hard cap at 12
    if skills:
        story += _section_header("Skills", st)
        # Split into rows of 6 for readability
        for i in range(0, len(skills), 6):
            row = "  |  ".join(_esc(s) for s in skills[i : i + 6])
            story.append(Paragraph(row, st["skills"]))

    # ── Certifications ────────────────────────────────────────────────────────
    certs = cv_data.get("certifications", [])
    if certs:
        story += _section_header("Certifications", st)
        for cert in certs:
            story.append(Paragraph(f"&#8226;  {_esc(cert)}", st["bullet"]))

    # ── Languages ─────────────────────────────────────────────────────────────
    langs = cv_data.get("languages", [])
    if langs:
        story += _section_header("Languages", st)
        story.append(Paragraph("  \u2022  ".join(_esc(l) for l in langs), st["skills"]))

    return story


# ── PDF Generation ────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = letter
MARGIN = 0.60 * inch
MAX_PAGES = 2


def generate_cv_pdf(cv_data: dict, output_path: str) -> str:
    """
    Generate an ATS-optimised CV PDF.
    Auto-scales font size down if content exceeds 2 pages.
    Returns output_path on success.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Try font sizes from 9.5 down to 8.0 until it fits in 2 pages
    for base_fs in (9.5, 9.0, 8.5, 8.0):
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=0.55 * inch,
            bottomMargin=0.55 * inch,
        )
        st = _build_styles(base_fs)
        story = _build_story(cv_data, st)
        doc.build(story)

        # Check page count
        with pdfplumber.open(output_path) as pdf:
            pages = len(pdf.pages)

        if pages <= MAX_PAGES:
            break   # fits — done

    return output_path
