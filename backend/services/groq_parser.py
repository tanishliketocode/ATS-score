import os
import json 
import logging
from typing import Dict

from groq import Groq

logger=logging.getLogger('ats_resume_scorer')


GROQ_MODEL = os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')
FALLBACK_MODELS = ['openai/gpt-oss-120b', 'openai/gpt-oss-20b']

_client=None

def _get_client()->Groq:
    global _client
    if _client is None:
        api_key=os.getenv('GROQ_API_KEY')

        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")
        _client=Groq(api_key=api_key)
    return _client

RESUME_SYSTEM_PROMPT = (
    "You are a resume parser. Extract information from the resume "
    "and return ONLY a valid JSON object. No explanation, no markdown."
)

RESUME_USER_PROMPT = """Extract the following from this resume and return as JSON:
{{
  "name": "full name",
  "email": "email address",
  "phone": "phone number",
  "linkedin": "LinkedIn URL if present, otherwise null",
  "github": "GitHub URL if present, otherwise null",
  "professional_summary": "the full text of the Summary, Profile, About Me, Objective, or Professional Summary section at the top of the resume. Copy the ENTIRE paragraph exactly as written. If no such section exists, return an empty string.",
  "skills": ["list", "of", "skills"],
  "experience": [
    {{
      "job_title": "",
      "company": "",
      "start_date": "",
      "end_date": "",
      "duration_months": 0,
      "description": ""
    }}
  ],
  "education": [
    {{
      "degree": "",
      "institution": "",
      "year": ""
    }}
  ],
  "certifications": ["list of certifications"],
  "projects": [
    {{
      "title": "project name",
      "description": "what the project does and how it was built",
      "technologies": ["tech", "used"]
    }}
  ],
  "action_verbs": ["strong action verbs used in bullet points, e.g. developed, implemented, designed"],
  "keywords": ["important keywords and phrases from the resume for ATS matching"]
}}

Important instructions:
- For duration_months, calculate the number of months between start_date and end_date. If end_date is "Present" or "Current", calculate from start_date to now.
- For skills, extract ALL technical and soft skills mentioned anywhere in the resume.
- For action_verbs, find verbs that start bullet points or describe achievements.
- For keywords, extract noun phrases and technical terms relevant to ATS matching.
- Return ONLY valid JSON. No markdown code fences, no explanation.

Resume Text:
{raw_text}"""

def _call_groq(client: Groq, system_prompt: str, user_prompt: str) -> str:
    models_to_try = [GROQ_MODEL] + [m for m in FALLBACK_MODELS if m != GROQ_MODEL]
    last_error = None
    for model_name in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                temperature=0.0,
                max_tokens=8192,
                response_format={'type': 'json_object'}
            )
            return response.choices[0].message.content.strip()
        except Exception as err:
            logger.warning(f"Groq call with model '{model_name}' (json_object) failed: {err}. Retrying without response_format...")
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt}
                    ],
                    temperature=0.0,
                    max_tokens=8192
                )
                return response.choices[0].message.content.strip()
            except Exception as e2:
                logger.warning(f"Groq call with model '{model_name}' failed: {e2}")
                last_error = e2
    raise last_error

def _try_parse_json(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
        cleaned = cleaned[first_newline + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    try:
        import json_repair
        parsed = json_repair.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return None
    
def _fallback_parse_resume(raw_text: str) -> Dict:
    """Heuristic fallback parser when Groq cannot return valid JSON."""
    import re
    email_match = re.search(r'[\w\.-]+@[\w\.-]+', raw_text)
    phone_match = re.search(r'\+?\d[\d\s-]{8,}\d', raw_text)
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    first_line = lines[0] if lines else ""

    fallback = {
        "name": first_line[:50],
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "professional_summary": "",
        "skills": [],
        "experience": [],
        "projects": [],
        "keywords": [w for w in raw_text.split() if len(w) > 4][:25],
    }
    return _validate_resume_result(fallback)

def parse_resume(raw_text: str)->Dict:
    try:
        client = _get_client()
    except Exception as exc:
        logger.warning(f"Could not initialize Groq client ({exc}); using fallback parse")
        return _fallback_parse_resume(raw_text)

    prompt = RESUME_USER_PROMPT.format(raw_text=raw_text)
    try:
        raw_response = _call_groq(client, RESUME_SYSTEM_PROMPT, prompt)
        result = _try_parse_json(raw_response)
        if result is not None:
            return _validate_resume_result(result)
    except Exception as exc:
        logger.warning(f"Groq resume parse failed: {exc}")

    logger.warning("Groq resume parse: first attempt returned invalid JSON, retrying...")
    strict_prompt = (
        "Your previous response was not valid JSON. "
        "Return ONLY the raw JSON object, no markdown, no explanation, no code fences.\n\n"
        + prompt
    )
    try:
        raw_response = _call_groq(client, RESUME_SYSTEM_PROMPT, strict_prompt)
        result = _try_parse_json(raw_response)
        if result is not None:
            return _validate_resume_result(result)
    except Exception as exc:
        logger.warning(f"Groq retry parse failed: {exc}")

    logger.warning("Groq parse unparseable after retry; using graceful fallback")
    return _fallback_parse_resume(raw_text)
    
JD_SYSTEM_PROMPT = (
    "You are a job description parser. Extract information and "
    "return ONLY a valid JSON object. No explanation, no markdown."
)

JD_USER_PROMPT = """Extract the following from this job description and return as JSON:
{{
  "job_title": "",
  "required_skills": ["list of must-have skills"],
  "preferred_skills": ["list of nice-to-have skills"],
  "experience_required": "",
  "education_required": "",
  "key_responsibilities": ["list of responsibilities"],
  "keywords": ["important keywords and phrases for ATS matching"]
}}

Important instructions:
- required_skills: skills explicitly stated as required or must-have.
- preferred_skills: skills stated as preferred, nice-to-have, or bonus.
- keywords: extract ALL important terms an ATS system would match against,
  including skills, technologies, certifications, and domain terms.
- Return ONLY valid JSON. No markdown code fences, no explanation.

Job Description Text:
{raw_text}"""

def _fallback_parse_jd(raw_text: str) -> Dict:
    """Heuristic fallback when Groq cannot return valid JD JSON."""
    words = [w.strip('.,()[]{}:;') for w in raw_text.split() if len(w) > 3]
    return _validate_jd_result({
        "job_title": "",
        "required_skills": words[:10],
        "preferred_skills": [],
        "keywords": list(set(words))[:20],
    })

def parse_job_description(raw_text: str) -> Dict:
    try:
        client = _get_client()
    except Exception as exc:
        logger.warning(f"Could not initialize Groq client for JD ({exc}); using fallback")
        return _fallback_parse_jd(raw_text)

    prompt = JD_USER_PROMPT.format(raw_text=raw_text)
    try:
        raw_response = _call_groq(client, JD_SYSTEM_PROMPT, prompt)
        result = _try_parse_json(raw_response)
        if result is not None:
            return _validate_jd_result(result)
    except Exception as exc:
        logger.warning(f"Groq JD parse failed: {exc}")

    logger.warning("Groq JD parse: first attempt returned invalid JSON, retrying...")
    strict_prompt = (
        "Your previous response was not valid JSON. "
        "Return ONLY the raw JSON object, no markdown, no explanation, no code fences.\n\n"
        + prompt
    )
    try:
        raw_response = _call_groq(client, JD_SYSTEM_PROMPT, strict_prompt)
        result = _try_parse_json(raw_response)
        if result is not None:
            return _validate_jd_result(result)
    except Exception as exc:
        logger.warning(f"Groq retry JD parse failed: {exc}")

    logger.warning("Groq JD parse unparseable after retry; using graceful fallback")
    return _fallback_parse_jd(raw_text)

#it will make sure, that the parse json has all the valid fields we expect
def _validate_jd_result(result: dict) -> dict:
    
    defaults = {
        "job_title": "",
        "required_skills": [],
        "preferred_skills": [],
        "experience_required": "",
        "education_required": "",
        "key_responsibilities": [],
        "keywords": [],
    }

    for key, default in defaults.items():
        if key not in result or result[key] is None:
            result[key] = default
        if isinstance(default, list) and not isinstance(result[key], list):
            result[key] = default

    return result


#to make sure the parse json has all the valid json fields
def _validate_resume_result(result: dict) -> dict:

    defaults = {
        "name": "",
        "email": None,
        "phone": None,
        "linkedin": None,
        "github": None,
        "professional_summary": "",
        "skills": [],
        "experience": [],
        "education": [],
        "certifications": [],
        "projects": [],
        "action_verbs": [],
        "keywords": [],
    }
    for key, default in defaults.items():
        if key not in result or result[key] is None:
            result[key] = default
            
        # Ensure list fields are actually lists
        if isinstance(default, list) and not isinstance(result[key], list):
            result[key] = default

    #Validate experience entries
    for exp in result.get("experience", []):
        if not isinstance(exp, dict):
            continue
        exp.setdefault("job_title", "")
        exp.setdefault("company", "")
        exp.setdefault("start_date", "")
        exp.setdefault("end_date", "")
        exp.setdefault("duration_months", 0)
        exp.setdefault("description", "")
        #Ensure duration_months is an int
        try:
            exp["duration_months"] = int(exp["duration_months"])
        except (ValueError, TypeError):
            exp["duration_months"] = 0

    #Validate project entries
    for proj in result.get("projects", []):
        if not isinstance(proj, dict):
            continue
        proj.setdefault("title", "")
        proj.setdefault("description", "")
        proj.setdefault("technologies", [])

    return result


