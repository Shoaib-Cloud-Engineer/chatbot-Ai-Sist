from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import boto3
from io import BytesIO
import PyPDF2
import openpyxl
import re
import difflib

# === FastAPI App ===
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# === AWS Credentials ===
AWS_ACCESS_KEY_ID = "<paste>"
AWS_SECRET_ACCESS_KEY = "<paste>"
REGION_NAME = "us-east-1"
BUCKET_NAME = "botchat-bucket-1"
FOLDER_PREFIX = "chatbot/"

# === S3 Client ===
s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=REGION_NAME
)

# === List PDF/Excel Files ===
def list_files(bucket, prefix):
    keys = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".pdf", ".xlsx", ".xls")):
                keys.append(key)
    return keys

# === Read PDF ===
def read_pdf(key):
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        file_stream = BytesIO(response['Body'].read())
        reader = PyPDF2.PdfReader(file_stream)
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        return f"Error reading {key}: {e}"

# === Read Excel ===
def read_excel(key):
    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        file_stream = BytesIO(response['Body'].read())
        wb = openpyxl.load_workbook(file_stream, data_only=True)
        rows = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                if row and any(cell is not None for cell in row):
                    row_text = "  ".join(str(cell) for cell in row if cell is not None)
                    rows.append(row_text)
        return "\n".join(rows)
    except Exception as e:
        return f"Error reading {key}: {e}"

# === Keyword Highlighter ===
def highlight(text, keyword):
    words = set(re.findall(r'\w+', keyword.lower()))
    for word in words:
        text = re.sub(fr"(?i)\b({re.escape(word)})\b", r"<b>\1</b>", text)
    return text

# === Smart Search ===
def search_query(query):
    keys = list_files(BUCKET_NAME, FOLDER_PREFIX)
    if not keys:
        return "No files found in the folder."

    results = []
    query_lower = query.lower()

    for key in keys:
        content = read_pdf(key) if key.endswith(".pdf") else read_excel(key)
        if "Error" in content:
            continue

        lines = content.split("\n")

        # ==== PDF Matching (2 lines before/after) ====
        if key.endswith(".pdf"):
            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(i - 2, 0)
                    end = min(i + 3, len(lines))
                    snippet = "\n".join(lines[start:end])
                    results.append(f"<b>{key}</b>:<br>" + highlight(snippet, query))

        # ==== Excel Matching (Exact, Substring, Fuzzy Word) ====
        else:
            for row in lines:
                row_lower = row.lower()
                if query_lower in row_lower:
                    results.append(f"<b>{key}</b>:<br>" + highlight(row.strip(), query))
                    continue

                for word in re.findall(r'\w+', row_lower):
                    ratio = difflib.SequenceMatcher(None, query_lower, word).ratio()
                    if ratio > 0.8:
                        results.append(f"<b>{key}</b>:<br>" + highlight(row.strip(), query))
                        break

    return "<br><br>".join(results) if results else f"❌ No relevant content found for: '{query}'"

# === Routes ===
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/ask", response_class=HTMLResponse)
async def ask(request: Request, query: str = Form(...)):
    answer = search_query(query)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "question": query,
        "answer": answer
    })

# === Local Run ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
