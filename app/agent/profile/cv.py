from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile


SKILL_KEYWORDS = (
    "Python",
    "JavaScript",
    "TypeScript",
    "React",
    "Node.js",
    "SQL",
    "Power BI",
    "Tableau",
    "Data Analytics",
    "Machine Learning",
    "AI",
    "API",
    "Frontend",
    "Backend",
    "Automation",
    "Git",
    "Azure",
    "AWS",
)


def extract_cv_text(path: str | Path) -> dict[str, Any]:
    source_path = Path(path)
    suffix = source_path.suffix.casefold()
    if suffix == ".docx":
        text = _extract_docx_text(source_path)
    elif suffix in {".txt", ".md"}:
        text = source_path.read_text(encoding="utf-8-sig")
    else:
        raise ValueError(f"Unsupported CV format for deterministic extraction: {source_path.suffix}")
    normalized = _normalize_text(text)
    return {
        "contract_version": "cv_text_extraction_v1",
        "source_path": str(source_path),
        "source_format": suffix.lstrip("."),
        "text_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "character_count": len(normalized),
        "line_count": len(_lines(normalized)),
        "text": normalized,
    }


def build_candidate_profile_from_cv_text(text: str, *, source_path: str | Path | None = None) -> dict[str, Any]:
    normalized = _normalize_text(text)
    lines = _lines(normalized)
    email = _first_regex(normalized, r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
    phone = _first_regex(normalized, r"(?:\+?\d[\d\s().-]{6,}\d)")
    name = _guess_name(lines)
    location = _guess_location(lines)
    skills = _extract_skills(normalized)
    target_roles = _target_roles_from_text(normalized)
    experience_summary = _experience_summary(lines)
    education_summary = _education_summary(lines)
    return {
        "contract_version": "candidate_profile_v1",
        "profile_source": "real_user_candidate_profile_v1",
        "profile_purpose": "real_resume_profile",
        "profile_generation": {
            "contract_version": "candidate_profile_generation_v1",
            "source": "cv_text_extraction_v1",
            "source_path": str(source_path) if source_path else None,
            "source_text_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "method": "deterministic_cv_text_parser",
            "review_required": True,
        },
        "candidate_name": name or "",
        "email": email or "",
        "phone": phone or "",
        "city": location.get("city") or "",
        "suburb": "",
        "github_url": _first_regex(normalized, r"https?://(?:www\.)?github\.com/[^\s)]+") or "",
        "linkedin_url": _first_regex(normalized, r"https?://(?:www\.)?linkedin\.com/[^\s)]+") or "",
        "portfolio_url": _first_regex(normalized, r"https?://(?!.*(?:github|linkedin))[^\s)]+") or "",
        "skills": skills,
        "target_roles": target_roles,
        "location_constraints": location.get("constraints") or [],
        "experience_summary": experience_summary,
        "education_summary": education_summary,
        "work_rights_summary": "",
        "availability_summary": "",
        "salary_preference": "",
        "preferred_work_modes": [],
        "avoid_roles": [],
        "avoid_companies": [],
        "do_not_apply_to": [],
        "risk_do_not_invent": True,
        "profile_review_required": True,
        "draft_notes": [
            "Generated from a local CV by deterministic extraction.",
            "Review and complete work_rights_summary before live Apply Entry or safe-fill.",
            "Do not add skills or experience that are not supported by the CV.",
        ],
    }


def _extract_docx_text(path: Path) -> str:
    with ZipFile(path) as archive:
        document = archive.read("word/document.xml")
    root = ElementTree.fromstring(document)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = ["".join(node.itertext()).strip() for node in root.findall(".//w:p", ns)]
    return "\n".join(paragraph for paragraph in paragraphs if paragraph)


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in str(text or "").replace("\r\n", "\n").split("\n") if line.strip())


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _first_regex(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0).strip() if match else None


def _guess_name(lines: list[str]) -> str | None:
    for line in lines[:5]:
        words = line.split()
        if 1 < len(words) <= 4 and all(word.replace("-", "").isalpha() for word in words):
            return " ".join(word.capitalize() for word in words)
    return None


def _guess_location(lines: list[str]) -> dict[str, Any]:
    joined = " ".join(lines[:10])
    constraints: list[str] = []
    city = ""
    if re.search(r"\bAuckland\b", joined, flags=re.IGNORECASE):
        city = "Auckland"
        constraints.append("Auckland")
    if re.search(r"\bNew Zealand\b|\bNZ\b", joined, flags=re.IGNORECASE):
        constraints.append("New Zealand")
    return {"city": city, "constraints": constraints}


def _extract_skills(text: str) -> list[str]:
    lowered = text.casefold()
    skills: list[str] = []
    for skill in SKILL_KEYWORDS:
        if skill.casefold() in lowered:
            skills.append(skill)
    return skills


def _target_roles_from_text(text: str) -> list[str]:
    lowered = text.casefold()
    roles: list[str] = []
    if "software engineer" in lowered or "frontend" in lowered or "backend" in lowered:
        roles.append("Software Engineer")
    if "data analytics" in lowered or "data analyst" in lowered or "business intelligence" in lowered:
        roles.append("Data Analyst")
    if "frontend" in lowered or "react" in lowered:
        roles.append("Frontend Developer")
    return roles


def _experience_summary(lines: list[str]) -> list[str]:
    selected: list[str] = []
    for line in lines:
        lowered = line.casefold()
        if any(term in lowered for term in ("experience", "built", "developed", "implemented", "integrating", "applications")):
            selected.append(line)
        if len(selected) >= 6:
            break
    return selected


def _education_summary(lines: list[str]) -> list[str]:
    selected: list[str] = []
    for line in lines:
        lowered = line.casefold()
        if any(term in lowered for term in ("university", "honours", "gpa", "degree", "graduate")):
            selected.append(line)
        if len(selected) >= 4:
            break
    return selected
