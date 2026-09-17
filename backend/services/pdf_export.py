import io
import os
import subprocess
import tempfile
import logging
import PyPDF2

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_INSTALLED = True
except Exception:
    WEASYPRINT_INSTALLED = False

logger = logging.getLogger('ats_resume_scorer')

def _find_browser() -> str | None:
    candidate_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return p
    return None

def _generate_pdf_with_browser(html_docs: dict[str, str]) -> bytes:
    browser = _find_browser()
    if not browser:
        raise RuntimeError("No headless browser (Edge/Chrome) found for PDF export.")

    merger = PyPDF2.PdfMerger()
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, content in html_docs.items():
            html_path = os.path.join(tmpdir, f"{name}.html")
            pdf_path = os.path.join(tmpdir, f"{name}.pdf")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)

            cmd = [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                html_path
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=25)
            merger.append(pdf_path)

        out_buf = io.BytesIO()
        merger.write(out_buf)
        merger.close()
        return out_buf.getvalue()

def generate_combined_pdf(html_docs: dict[str, str]) -> bytes:
    if WEASYPRINT_INSTALLED:
        try:
            documents = []
            for name, html_str in html_docs.items():
                doc = HTML(string=html_str).render()
                documents.append(doc)
            first_doc = documents[0]
            for other_doc in documents[1:]:
                for page in other_doc.pages:
                    first_doc.pages.append(page)
            return first_doc.write_pdf()
        except Exception as exc:
            logger.warning(f"WeasyPrint rendering failed ({exc}); falling back to headless browser printing.")

    # Primary or fallback: headless browser rendering
    return _generate_pdf_with_browser(html_docs)
