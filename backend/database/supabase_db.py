import logging
import httpx
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict

logger = logging.getLogger('ats_resume_scorer')

from backend.core.config import SUPABASE_URL, SUPABASE_KEY

DB_PATH = os.path.join(os.path.dirname(__file__), 'local_history.db')

def _init_sqlite():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                filename TEXT,
                ats_score REAL,
                keyword_match REAL,
                missing_keywords TEXT,
                created_at TEXT,
                analysis_result TEXT
            )
        ''')
        conn.commit()
    finally:
        conn.close()

_init_sqlite()

def _save_local(doc: dict) -> str:
    inserted_id = str(doc.get("id") or uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            INSERT OR REPLACE INTO analyses 
            (id, user_id, filename, ats_score, keyword_match, missing_keywords, created_at, analysis_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            inserted_id,
            doc.get("user_id", ""),
            doc.get("filename", "resume"),
            float(doc.get("ats_score", 0)),
            float(doc.get("keyword_match", 0)),
            json.dumps(doc.get("missing_keywords", [])),
            doc.get("created_at", datetime.now(timezone.utc).isoformat()),
            json.dumps(doc.get("analysis_result", {})),
        ))
        conn.commit()
        return inserted_id
    finally:
        conn.close()

def _get_local(user_id: str) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('''
            SELECT id, filename, ats_score, keyword_match, missing_keywords, created_at, analysis_result 
            FROM analyses 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))
        rows = c.fetchall()
        results = []
        for r in rows:
            try:
                analysis_res = json.loads(r[6]) if r[6] else {}
            except Exception:
                analysis_res = {}
            try:
                missing_kw = json.loads(r[4]) if r[4] else []
            except Exception:
                missing_kw = []

            results.append({
                "id": r[0],
                "filename": r[1] or "resume",
                "resume_name": r[1] or "resume",
                "job_title": analysis_res.get("jd_match_analysis", {}).get("job_title", "Software Engineer") if isinstance(analysis_res.get("jd_match_analysis"), dict) else "Software Engineer",
                "ats_score": r[2],
                "keyword_match": r[3],
                "missing_keywords": missing_kw,
                "date": r[5],
                "created_at": r[5],
                "analysis_result": analysis_res,
            })
        return results
    finally:
        conn.close()

def _delete_local(analysis_id: str, user_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute('DELETE FROM analyses WHERE id = ? AND user_id = ?', (analysis_id, user_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()

def _get_headers():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

async def save_analysis(user_id: str, filename: str, analysis_result: Dict) -> Optional[str]:
    def _json_default(o):
        if hasattr(o, 'model_dump'):
            return o.model_dump()
        return str(o)
    serializable_result = json.loads(json.dumps(analysis_result, default=_json_default))

    doc = {
        "user_id": user_id,
        "filename": filename,
        "ats_score": serializable_result.get("ats_score", serializable_result.get("ATS_score", 0)),
        "keyword_match": serializable_result.get("keyword_match", 0),
        "missing_keywords": serializable_result.get("missing_keywords", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_result": serializable_result,
    }

    # Always save locally so history is never lost
    local_id = _save_local(doc)

    # Also try Supabase if configured
    headers = _get_headers()
    if headers:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/analyses"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=doc, timeout=10)
                if response.status_code in (200, 201):
                    data = response.json()
                    if data and len(data) > 0:
                        return str(data[0].get("id"))
                else:
                    logger.warning(f"Supabase returned status {response.status_code}, using local history fallback.")
        except Exception as exc:
            logger.warning(f"Failed to save analysis to Supabase ({exc}), using local history fallback.")

    return local_id

async def get_user_history(user_id: str) -> List[Dict]:
    headers = _get_headers()
    if headers:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/analyses"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, 
                    headers=headers, 
                    params={
                        "user_id": f"eq.{user_id}",
                        "order": "created_at.desc"
                    },
                    timeout=10
                )
                if response.status_code == 200:
                    docs = response.json()
                    results = []
                    for doc in docs:
                        results.append({
                            "id": str(doc.get("id")),
                            "filename": doc.get("filename", "resume"),
                            "resume_name": doc.get("filename", "resume"),
                            "job_title": "Software Engineer",
                            "ats_score": doc.get("ats_score", 0),
                            "keyword_match": doc.get("keyword_match", 0),
                            "missing_keywords": doc.get("missing_keywords", []),
                            "date": doc.get("created_at", ""),
                            "created_at": doc.get("created_at", ""),
                            "analysis_result": doc.get("analysis_result", {}),
                        })
                    if results:
                        return results
        except Exception as exc:
            logger.warning(f"Failed to fetch history from Supabase ({exc}), fetching from local fallback.")

    # Fallback to local SQLite database
    return _get_local(user_id)

async def delete_analysis(analysis_id: str, user_id: str) -> bool:
    deleted_local = _delete_local(analysis_id, user_id)

    headers = _get_headers()
    if headers:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/analyses"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url, 
                    headers=headers, 
                    params={
                        "id": f"eq.{analysis_id}",
                        "user_id": f"eq.{user_id}"
                    },
                    timeout=10
                )
                if response.status_code in (200, 204):
                    return True
        except Exception as exc:
            logger.warning(f"Failed to delete analysis from Supabase: {exc}")

    return deleted_local
