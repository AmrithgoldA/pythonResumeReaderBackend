from flask import Flask, request, jsonify
from flask_cors import CORS
import tempfile
import os
import requests
import json
from config import DEEPSEEK_API_KEY
from utils.extractors import extract_pdf_text, extract_docx_text

app = Flask(__name__)
CORS(app)

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

        prompt = f"""Extract the following personal details from this resume text:
- Full Name
- Email
- Phone number
- Address (if available)
- LinkedIn URL (if any)

Text:
\"\"\"{text}\"\"\""""

        print("🚀 Sending request to DeepSeek via OpenRouter")

        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5173",
                "X-Title": "Resume Parser"
            },
            data=json.dumps({
                "model": "deepseek/deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2
            }),
        )

        if res.status_code == 200:
            print("✅ DeepSeek response received")
            data = res.json()["choices"][0]["message"]["content"]
            return jsonify({
                "data": data,
                "extracted_text": text
            })
        else:
            print("❌ DeepSeek API call failed")
            print("Status Code:", res.status_code)
            print("Response:", res.text)
            return jsonify({"error": "DeepSeek failed", "details": res.text}), 500

    finally:
        os.remove(file_path)
        print(f"🧹 Temporary file deleted: {file_path}")

if __name__ == "__main__":
    print("🚀 Starting Flask server on http://localhost:5000")
    app.run(port=5000, debug=True)
