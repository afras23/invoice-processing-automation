import pdfplumber
import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def extract_text_from_pdf(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

def extract_invoice_data(pdf_path: str) -> dict:
    raw_text = extract_text_from_pdf(pdf_path)

    with open("prompts/invoice_extraction.txt") as f:
        prompt = f.read()

    message = client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": f"{prompt}\n\nINVOICE TEXT:\n{raw_text}"}
        ]
    )

    return eval(message.content[0].text)
