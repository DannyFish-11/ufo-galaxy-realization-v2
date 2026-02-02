"""Node 16: Email - 邮件发送"""
import os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 16 - Email", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

class EmailRequest(BaseModel):
    to: List[str]
    subject: str
    body: str
    html: bool = False
    attachments: Optional[List[str]] = None

@app.get("/health")
async def health():
    return {"status": "healthy" if SMTP_USER else "degraded", "node_id": "16", "name": "Email", "smtp_configured": bool(SMTP_USER), "timestamp": datetime.now().isoformat()}

@app.post("/send")
async def send_email(request: EmailRequest):
    if not SMTP_USER or not SMTP_PASS:
        raise HTTPException(status_code=503, detail="SMTP not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS")
    
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = ', '.join(request.to)
        msg['Subject'] = request.subject
        
        msg.attach(MIMEText(request.body, 'html' if request.html else 'plain'))
        
        if request.attachments:
            for filepath in request.attachments:
                if os.path.exists(filepath):
                    with open(filepath, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(filepath)}"')
                        msg.attach(part)
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        
        return {"success": True, "to": request.to, "subject": request.subject}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "send": return await send_email(EmailRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8016)
