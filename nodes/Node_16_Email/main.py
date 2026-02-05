"""
Node 16: Email - 邮件服务节点
================================
提供SMTP发送邮件、邮件模板、批量发送功能
"""
import os
import smtplib
import ssl
from datetime import datetime
from typing import Dict, Any, List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

app = FastAPI(title="Node 16 - Email", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]))

# SMTP配置
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower() == "true"

class EmailRequest(BaseModel):
    to: List[EmailStr]
    subject: str
    body: str
    html: bool = False
    cc: List[EmailStr] = []
    bcc: List[EmailStr] = []
    attachments: List[str] = []  # 文件路径列表

class TemplateEmailRequest(BaseModel):
    to: List[EmailStr]
    template: str
    variables: Dict[str, Any] = {}

class EmailManager:
    def __init__(self):
        self.smtp_host = SMTP_HOST
        self.smtp_port = SMTP_PORT
        self.smtp_user = SMTP_USER
        self.smtp_password = SMTP_PASSWORD
        self.smtp_tls = SMTP_TLS
        self._templates = self._load_templates()

    def _load_templates(self) -> Dict[str, str]:
        """加载邮件模板"""
        return {
            "welcome": """
                <h1>Welcome {{name}}!</h1>
                <p>Thank you for joining us.</p>
            """,
            "notification": """
                <h2>Notification</h2>
                <p>{{message}}</p>
            """,
            "reset_password": """
                <h2>Password Reset</h2>
                <p>Click <a href="{{link}}">here</a> to reset your password.</p>
            """
        }

    def _render_template(self, template: str, variables: Dict[str, Any]) -> str:
        """渲染模板"""
        result = template
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def send_email(self, to: List[str], subject: str, body: str, 
                   html: bool = False, cc: List[str] = None, 
                   bcc: List[str] = None, attachments: List[str] = None) -> Dict:
        """发送邮件"""
        if not self.smtp_user or not self.smtp_password:
            raise RuntimeError("SMTP credentials not configured")

        msg = MIMEMultipart()
        msg['From'] = self.smtp_user
        msg['To'] = ', '.join(to)
        msg['Subject'] = subject

        if cc:
            msg['Cc'] = ', '.join(cc)
        if bcc:
            msg['Bcc'] = ', '.join(bcc)

        # 添加正文
        content_type = 'html' if html else 'plain'
        msg.attach(MIMEText(body, content_type, 'utf-8'))

        # 添加附件
        if attachments:
            for file_path in attachments:
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {os.path.basename(file_path)}'
                    )
                    msg.attach(part)

        # 发送邮件
        context = ssl.create_default_context()

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.smtp_tls:
                server.starttls(context=context)
            server.login(self.smtp_user, self.smtp_password)

            all_recipients = to + (cc or []) + (bcc or [])
            server.sendmail(self.smtp_user, all_recipients, msg.as_string())

        return {
            "success": True,
            "recipients": len(all_recipients),
            "timestamp": datetime.now().isoformat()
        }

    def send_template_email(self, to: List[str], template_name: str, 
                           variables: Dict[str, Any], subject: str = "") -> Dict:
        """发送模板邮件"""
        template = self._templates.get(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        body = self._render_template(template, variables)
        return self.send_email(to, subject or template_name, body, html=True)

# 全局邮件管理器
email_manager = EmailManager()

# ============ API 端点 ============

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": "16",
        "name": "Email",
        "smtp_host": SMTP_HOST,
        "smtp_user": SMTP_USER,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/send")
async def send_email(request: EmailRequest):
    """发送邮件"""
    try:
        result = email_manager.send_email(
            to=request.to,
            subject=request.subject,
            body=request.body,
            html=request.html,
            cc=request.cc,
            bcc=request.bcc,
            attachments=request.attachments
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-template")
async def send_template_email(request: TemplateEmailRequest, subject: str = ""):
    """发送模板邮件"""
    try:
        result = email_manager.send_template_email(
            to=request.to,
            template_name=request.template,
            variables=request.variables,
            subject=subject
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/templates")
async def list_templates():
    """列出可用模板"""
    return {"templates": list(email_manager._templates.keys())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8016)
