from flask import Flask, request, jsonify
from flask_cors import CORS
import tempfile
import os
import requests
import json
import time
import logging
from dotenv import load_dotenv
from utils.extractors import extract_pdf_text, extract_docx_text

load_dotenv()

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

API_KEYS = [
    os.getenv("DEEPSEEK_API_KEY1"),
    os.getenv("DEEPSEEK_API_KEY2"),
    os.getenv("DEEPSEEK_API_KEY3"),
    os.getenv("DEEPSEEK_API_KEY4"),
    os.getenv("DEEPSEEK_API_KEY5"),
    os.getenv("DEEPSEEK_API_KEY6"),
]
API_KEYS = [key for key in API_KEYS if key is not None]

if not API_KEYS:
    raise ValueError("No API keys found in .env file")

class APIKeyManager:
    def __init__(self, keys):
        self.keys = keys
        self.current_index = 0
        self.failed_keys = set()
    
    def get_current_key(self):
        return self.keys[self.current_index]
    
    def get_current_index(self):
        return self.current_index
    
    def rotate_key(self):
        self.failed_keys.add(self.current_index)
        if len(self.failed_keys) == len(self.keys):
            self.failed_keys.clear()
        original_index = self.current_index
        while True:
            self.current_index = (self.current_index + 1) % len(self.keys)
            if self.current_index not in self.failed_keys:
                break
            if self.current_index == original_index:
                raise RuntimeError("No working API keys available")
        return self.keys[self.current_index]

key_manager = APIKeyManager(API_KEYS)

def call_deepseek_api(prompt):
    headers = {
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "Resume Parser"
    }
    data = {
        "model": "deepseek/deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    max_retries = len(API_KEYS) * 2
    last_error = None

    for _ in range(max_retries):
        current_key = key_manager.get_current_key()
        headers["Authorization"] = f"Bearer {current_key}"
        try:
            res = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                data=json.dumps(data),
                timeout=30
            )
            if res.status_code == 200:
                return res, None
            error_data = res.json().get("error", {})
            error_message = error_data.get("message", "")
            if res.status_code == 402 or "Insufficient credits" in error_message:
                key_manager.rotate_key()
            elif res.status_code == 429 or error_data.get("code") == 429:
                key_manager.rotate_key()
            else:
                last_error = f"{res.status_code} - {res.text}"
                break
        except requests.exceptions.RequestException as e:
            last_error = str(e)
            key_manager.rotate_key()
    return None, last_error

@app.route("/upload", methods=["POST"])
def upload_resume():
    request_id = os.urandom(4).hex()
    start_time = time.time()

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file_path = tmp.name
        file.save(file_path)

    try:
        if file.filename.endswith(".pdf"):
            text = extract_pdf_text(file_path)
        elif file.filename.endswith(".docx"):
            text = extract_docx_text(file_path)
        else:
            return jsonify({"error": "Unsupported file type"}), 400

        if not text.strip():
            return jsonify({"error": "No text extracted"}), 400

        prompt = f"""
Extract the following personal details from this resume in strict JSON format only with the following keys:
- "Full Name"
- "Email"
- "Phone number"
- "Address"
- "LinkedIn URL"
- "Qualification"
- "location"
- "previous Career details": a list of {{ "company name", "years of experience", "Relevant Experience (years)" }}
- "total professional experience (years)"
- "primary skills"
- "secondary skills"
Instructions:
- Only include companies where the candidate was directly employed
- Do not include clients, freelance or academic projects
- Extract technologies from Skills/About/Experience
- Round all years to 1 decimal place
- For "Present", use July 2, 2025 as end date
Return valid JSON only
Resume text:
\"\"\"{text}\"\"\"
"""
        res, error = call_deepseek_api(prompt)
        if res is None:
            return jsonify({"error": "API request failed", "details": error}), 500

        content = res.json()["choices"][0]["message"]["content"]
        clean_json = content.strip().strip("`")
        if clean_json.startswith("json"):
            clean_json = clean_json[4:].strip()
        try:
            parsed_data = json.loads(clean_json)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON returned", "raw": content}), 500

        improvement_prompt = f"""
Analyze the following resume content and provide clear, constructive suggestions to improve it.
For each suggestion, include:
- The current content from the resume
- The identified issue
- Specific recommendation for improvement
- Suggested improved content
Return the result in JSON format:
{{
  "summary": "...",
  "suggestions": [
    {{
      "section": "...",
      "currentContent": "...",
      "issue": "...",
      "recommendation": "...",
      "suggestedContent": "..."
    }}
  ]
}}
Resume:
\"\"\"{text}\"\"\"
"""
        res2, error2 = call_deepseek_api(improvement_prompt)
        resume_suggestions = {}
        if res2:
            try:
                suggestion_content = res2.json()["choices"][0]["message"]["content"]
                suggestion_clean = suggestion_content.strip().strip("`")
                if suggestion_clean.startswith("json"):
                    suggestion_clean = suggestion_clean[4:].strip()
                resume_suggestions = json.loads(suggestion_clean)
            except:
                resume_suggestions = {"error": "Failed to parse suggestions", "raw": suggestion_content}
        else:
            resume_suggestions = {"error": error2 or "Unknown error"}

        return jsonify({
            "data": parsed_data,
            "extracted_text": text,
            "resume_suggestions": resume_suggestions
        })
    except:
        return jsonify({"error": "Internal server error"}), 500
    finally:
        try:
            os.remove(file_path)
        except:
            pass

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 5000)
    app.run(host="0.0.0.0", port=port)
