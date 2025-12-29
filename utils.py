import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header


def send_email(subject, content, attachments=None):
    sender = "xuemengm7@163.com"
    password = "RZWmkczvtXzkrJDx"  # 网易邮箱客户端授权码
    receiver = "xuemengm7@163.com"

    # 邮件对象
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = Header(subject, "utf-8")

    # 邮件正文
    msg.attach(MIMEText(content, "plain", "utf-8"))

    # 附件部分
    if attachments:
        for file in attachments:
            with open(file, "rb") as f:
                attachment = MIMEText(f.read(), "base64", "utf-8")
                attachment["Content-Type"] = "application/octet-stream"
                attachment["Content-Disposition"] = f"attachment; filename={file}"
                msg.attach(attachment)

    try:
        # 网易 SMTP 服务器（SSL）
        smtp = smtplib.SMTP_SSL("smtp.163.com", 465)
        smtp.login(sender, password)
        smtp.sendmail(sender, receiver, msg.as_string())
        smtp.quit()

        print("📧 网易邮箱邮件发送成功！")

    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
