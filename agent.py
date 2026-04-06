"""
CV Tailor Agent — Claude Opus 4.6 powered CV optimization.
"""
import re
import json
import anthropic
from pydantic import BaseModel, Field
from typing import List, Optional


# ── Structured output schema ──────────────────────────────────────────────────

class ContactInfo(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    location: str = ""
    website: str = ""


class Role(BaseModel):
    job_title: str
    dates: str = ""
    bullets: List[str]


class WorkExperience(BaseModel):
    company: str
    location: str = ""
    dates: str
    roles: List[Role]


class Education(BaseModel):
    degree: str
    institution: str
    dates: str
    details: str = ""


class CVData(BaseModel):
    contact: ContactInfo
    summary: str
    experience: List[WorkExperience]
    education: List[Education]
    skills: List[str]
    certifications: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


class TailorResult(BaseModel):
    cv: CVData
    keywords_incorporated: List[str] = Field(
        description="Keywords from the job description that were woven into the CV"
    )
    changes_summary: List[str] = Field(
        description="Bullet-point list of the specific changes made"
    )
    ats_score: int = Field(
        description="Estimated ATS match score 0-100 based on keyword overlap with the job description"
    )
    match_highlights: List[str] = Field(
        description="Top reasons why this candidate is a strong match for the role"
    )
    missing_skills: List[str] = Field(
        description="Skills or requirements in the job description not found in the CV"
    )


# ── Post-processing ───────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Remove em/en dashes and separator hyphens from text."""
    # Remove em and en dashes entirely (replace with a space, then collapse double spaces)
    text = text.replace("\u2014", " ").replace("\u2013", " ")
    # Replace ' - ' used as a separator with a comma+space
    text = re.sub(r"\s+-\s+", ", ", text)
    # Collapse any double spaces
    text = re.sub(r"  +", " ", text).strip()
    return text


def _enforce_limits(result: "TailorResult") -> "TailorResult":
    """Enforce structural limits: 3 bullets per role, 12 skills max, 3-sentence summary."""
    cv = result.cv

    # Trim bullets to 3 per role
    trimmed_experience = [
        exp.model_copy(update={
            "roles": [
                role.model_copy(update={"bullets": role.bullets[:3]})
                for role in exp.roles
            ]
        })
        for exp in cv.experience
    ]

    # Keep max 12 skills (most relevant already ordered by Claude)
    trimmed_skills = cv.skills[:12]

    # Trim summary to 3 sentences
    sentences = re.split(r"(?<=[.!?])\s+", cv.summary.strip())
    trimmed_summary = " ".join(sentences[:3])

    cleaned_cv = cv.model_copy(update={
        "experience": trimmed_experience,
        "skills": trimmed_skills,
        "summary": trimmed_summary,
    })
    return result.model_copy(update={"cv": cleaned_cv})


def _sanitise_text(result: "TailorResult") -> "TailorResult":
    """Apply _clean() to every string field in the result."""
    cv = result.cv

    contact = cv.contact.model_copy(update={
        k: _clean(v) for k, v in cv.contact.model_dump().items() if isinstance(v, str)
    })

    experience = [
        exp.model_copy(update={
            **{k: _clean(v) for k, v in exp.model_dump().items() if isinstance(v, str)},
            "roles": [
                role.model_copy(update={
                    **{k: _clean(v) for k, v in role.model_dump().items() if isinstance(v, str)},
                    "bullets": [_clean(b) for b in role.bullets],
                })
                for role in exp.roles
            ],
        })
        for exp in cv.experience
    ]

    education = [
        edu.model_copy(update={
            k: _clean(v) for k, v in edu.model_dump().items() if isinstance(v, str)
        })
        for edu in cv.education
    ]

    cleaned_cv = cv.model_copy(update={
        "contact": contact,
        "summary": _clean(cv.summary),
        "experience": experience,
        "education": education,
        "skills": [_clean(s) for s in cv.skills],
        "certifications": [_clean(c) for c in cv.certifications],
        "languages": [_clean(l) for l in cv.languages],
    })

    return result.model_copy(update={
        "cv": cleaned_cv,
        "keywords_incorporated": [_clean(k) for k in result.keywords_incorporated],
        "changes_summary": [_clean(c) for c in result.changes_summary],
        "match_highlights": [_clean(m) for m in result.match_highlights],
        "missing_skills": [_clean(m) for m in result.missing_skills],
    })


# ── Agent ─────────────────────────────────────────────────────────────────────

class CVTailorAgent:
    SYSTEM_PROMPT = """You are an expert CV writer and ATS (Applicant Tracking System) \
optimization specialist with deep knowledge of recruitment across all industries.

Your task: tailor a candidate's CV for a specific job description.

RULES:
1. AUTHENTICITY — Never fabricate or exaggerate. Only rephrase, reorder, and emphasize what already exists.
2. KEYWORDS — Incorporate exact keywords and phrases from the job description naturally. Include both \
abbreviations and full forms (e.g. "Artificial Intelligence (AI)").
3. SUMMARY — Write a concise professional summary of 2 to 3 sentences maximum. It must be tight, \
impactful, and speak directly to this specific role. No waffle.
4. EXPERIENCE — Group roles by company. Each company entry has a company name, location, overall \
tenure dates, and one or more roles underneath. Each role has a job title, its own dates (required \
even for single-role companies), and up to 3 bullets. Include a maximum of 3 bullet points per role. \
Choose only the most impactful and relevant ones. Each bullet must be one line. Use strong action verbs. No filler.
5. SKILLS — List only the 8 to 12 skills most relevant to this specific job. Cut anything generic or \
not mentioned in the job description. Quality over quantity.
6. LAYOUT — The CV must fit within 2 pages. Keep every section lean and purposeful.
7. ATS FORMAT — Simple structure, no tables. Standard section headers. Single column.
8. SCORING — Estimate ATS score 0-100 based on keyword overlap. 70+ is good, 85+ is excellent.
9. PUNCTUATION — Never use em dashes (—), en dashes (–), or hyphens as separators between phrases. \
Use commas or rewrite the sentence instead. Hyphens are only acceptable inside compound words \
(e.g. "cross-functional"). These are well-known AI writing signals and must be avoided."""

    def __init__(self):
        self.client = anthropic.Anthropic()

    def tailor_cv(
        self,
        cv_text: str,
        job_description: str,
        user_profile: dict,
        job_title: str = "",
        company: str = "",
    ) -> TailorResult:
        """
        Tailor the CV for a job description.
        Returns a TailorResult with structured CV data and metadata.
        """
        profile_section = json.dumps(user_profile, indent=2) if user_profile else "No additional profile info provided."
        schema = json.dumps(TailorResult.model_json_schema(), indent=2)

        user_message = f"""Please tailor the CV below for the job description provided.

## Candidate Profile & Job Search Goals
{profile_section}

## Target Position
- Job Title: {job_title or 'See job description'}
- Company: {company or 'See job description'}

## Original CV Content
{cv_text}

## Job Description
{job_description}

Instructions:
1. Parse the full CV into structured sections
2. Tailor every section to maximise relevance to this specific role
3. Incorporate keywords from the job description naturally throughout
4. Keep the summary to 2-3 sentences, skills to 8-12 items, bullets to 3 per role max
5. Estimate an ATS match score (0-100)
6. List what you changed and what skills from the JD are missing from the CV

IMPORTANT: Respond with ONLY a valid JSON object matching this exact schema. No markdown, no code fences, no extra text:
{schema}"""

        response = self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            raise ValueError("Claude returned no text response. Please try again.")

        # Strip markdown code fences if Claude added them anyway
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()

        data = json.loads(text)
        result = TailorResult.model_validate(data)
        result = _enforce_limits(result)   # cap bullets/skills/summary
        result = _sanitise_text(result)    # remove dashes
        return result
