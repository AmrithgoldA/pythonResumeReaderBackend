from flask import Flask, request, jsonify
from flask_cors import CORS
import tempfile
import os
import requests
import json
from dotenv import load_dotenv
from utils.extractors import extract_pdf_text, extract_docx_text

load_dotenv()

print("Environment variables loaded:")
for key, value in os.environ.items():
    if "DEEPSEEK" in key:
        print(f"{key}: {'*' * len(value) if value else 'NOT SET'}")

app = Flask(__name__)
CORS(app)
app = Flask(__name__)
CORS(app)

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
    
    def rotate_key(self):
        self.failed_keys.add(self.current_index)

        if len(self.failed_keys) == len(self.keys):
            print("⚠️ All API keys exhausted, resetting and trying again")
            self.failed_keys.clear()

        original_index = self.current_index
        while True:
            self.current_index = (self.current_index + 1) % len(self.keys)
            if self.current_index not in self.failed_keys:
                break
            if self.current_index == original_index:
                raise RuntimeError("No working API keys available")
        
        print(f"🔄 Rotated to API key index {self.current_index}")
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
    
    for attempt in range(max_retries):
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
            error_code = error_data.get("code")
            error_message = error_data.get("message", "")
            
            if res.status_code == 402 or "Insufficient credits" in error_message:
                print(f"❌ API key {key_manager.current_index} has insufficient credits")
                last_error = "Insufficient API credits"
                key_manager.rotate_key()
            elif res.status_code == 429 or error_code == 429:
                print(f"❌ API key {key_manager.current_index} rate limited")
                last_error = "API rate limit exceeded"
                key_manager.rotate_key()
            else:
                last_error = f"API error: {res.status_code} - {res.text}"
                print(f"❌ API error: {last_error}")
                break
                
        except requests.exceptions.RequestException as e:
            last_error = f"Request failed: {str(e)}"
            print(f"❌ Request exception: {last_error}")
            key_manager.rotate_key()
    
    return None, last_error

@app.route("/upload", methods=["POST"])
def upload_resume():
    print("📥 Received upload request")

    if "file" not in request.files:
        print("❌ No file provided")
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    print(f"📄 File received: {file.filename}")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        file_path = tmp.name
        file.save(file_path)
        print(f"💾 File saved to temp path: {file_path}")

    try:
        if file.filename.endswith(".pdf"):
            print("🔍 Extracting text from PDF")
            text = extract_pdf_text(file_path)
        elif file.filename.endswith(".docx"):
            print("🔍 Extracting text from DOCX")
            text = extract_docx_text(file_path)
        else:
            print("❌ Unsupported file type")
            return jsonify({"error": "Unsupported file type"}), 400

        if not text.strip():
            print("❌ No text extracted")
            return jsonify({"error": "No text extracted"}), 400

        print("✅ Text extraction complete")

        prompt = f"""
Extract the following personal details from this resume in strict JSON format only with the following keys:
- "Full Name"  
- "Email"  
- "Phone number"  
- "Address"  
- "LinkedIn URL"  
- "Qualification"  
- "location": This should be the candidate's personal or current location. Use cities found near the contact section or explicitly labeled as the candidate's location. If none are available, return an empty string. Do not use college name or address as location.  
- "previous Career details" (work experience): A list of actual companies the person has worked for as an employee. **Exclude any clients, project organizations, or freelance work.** Each item must contain:
  - "company name"  
  - "years of experience": Convert date ranges like "Feb 2021 – May 2023" into decimal years (e.g., 2.3), rounded to 1 decimal place.  
  - "Relevant Experience (years)": Count only if the job description shows they actively used core technologies (e.g., React, Flutter, Node.js, etc. — as mentioned in About Me, Skills, or Work Experience). Round to 1 decimal place.  

- "total professional experience (years)":  
  Only calculate based on entries in **Experience** or **Work Experience** sections (not Summary, About, or Projects).  
  Sum durations across all valid employers using the formula:  
  `(end year - start year) + (end month - start month)/12`.  
  For roles ending in "Present", assume today's date is **July 2, 2025** and calculate accordingly.  
  Round the final total to 1 decimal place.
  Sum durations across valid companies only.  
- "primary skills": Technologies and tools the person has hands-on experience with, mentioned in skills or experience.  
- "secondary skills": Soft skills or tools that support their work (e.g., communication, Agile, version control, testing tools, etc.)

Instructions:
- **Only include companies where the candidate was directly employed** (exclude client projects, freelance work, or academic projects)
- Do not include clients or organizations mentioned under "Key Projects", "Clients", or similar sections
- Only include companies that appear under Work Experience with job title and dates
- Extract technologies listed in About Me, Skills, or used in job/project roles
- Round all years to 1 decimal place
- If any duration ends with the word "Present", use the current date (today) for calculation
- Return a **valid JSON object only**. No markdown, no explanation, no comments.

Resume text:
\"\"\"{text}\"\"\"
"""

        print("🚀 Sending request to DeepSeek via OpenRouter")
        res, error = call_deepseek_api(prompt)

        if res is None:
            print("❌ All API attempts failed")
            return jsonify({"error": "API request failed", "details": error}), 500

        print("✅ DeepSeek response received")
        content = res.json()["choices"][0]["message"]["content"]
        clean_json = content.strip().strip("`").strip()
        if clean_json.startswith("json"):
            clean_json = clean_json[4:].strip()
        try:
            parsed_data = json.loads(clean_json)
        except json.JSONDecodeError:
            print("❌ Invalid JSON after cleaning")
            return jsonify({"error": "Invalid JSON returned", "raw": content}), 500

        return jsonify({
            "data": parsed_data,
            "extracted_text": text
        })

    finally:
        os.remove(file_path)
        print(f"🧹 Temporary file deleted: {file_path}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 5000)
    print(f"🚀 Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)