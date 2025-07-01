import fitz
import docx

def extract_pdf_text(file_path):
    with fitz.open(file_path) as doc:
        return "\n".join([page.get_text() for page in doc])

def extract_docx_text(file_path):
    return "\n".join([para.text for para in docx.Document(file_path).paragraphs])
