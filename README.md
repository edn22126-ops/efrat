# efrat – PLMS (Personal Legal / Document Management System)

מערכת לניהול ראיות ומסמכים משפטיים אישיים: העלאה ל-S3, OCR אוטומטי, חיפוש טקסט, ניהול תגיות וביקורת.

---

## 🚀 התחלה מהירה

1. **קראי את מדריך ההקמה המלא (Windows):** [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md)
2. **שכפלי את הריפו:**
   ```powershell
   git clone https://github.com/edn22126-ops/efrat.git
   cd efrat
   copy .env.example .env   # ערכי את הפרטים
   ```
3. **הפעילי את המערכת:**
   ```powershell
   docker-compose up --build
   ```
4. **API Docs:** http://localhost:8000/docs

---

## 📁 מבנה הפרויקט

```
efrat/
├── backend/               # FastAPI application (Python)
│   ├── app/
│   │   ├── main.py        # Entry point
│   │   ├── api/           # Routers: documents, upload, search
│   │   ├── models/        # ORM models (Document, Tag, AuditLog)
│   │   ├── db/            # DB session
│   │   ├── core/          # Config, AWS helpers
│   │   └── worker.py      # OCR SQS worker
│   ├── migrations/        # Alembic DB migrations
│   ├── Dockerfile
│   └── requirements.txt
├── tools/
│   └── upload_bulk.py     # Bulk file upload script
├── docs/
│   └── SETUP_WINDOWS.md   # Step-by-step Windows setup guide
├── docker-compose.yml
├── .env.example
└── .gitignore
```

---

## ⚠️ אבטחה חשובה

> **אל תעלי קבצים אישיים / מסמכים / ראיות לריפו GitHub!**  
> קבצים עוברים **דרך האפליקציה** → נשמרים ב-**AWS S3** בלבד.

---

## 🔗 קישורים מהירים

| קובץ | תיאור |
|------|-------|
| [`docs/SETUP_WINDOWS.md`](docs/SETUP_WINDOWS.md) | מדריך הקמה מלא ל-Windows |
| [`docker-compose.yml`](docker-compose.yml) | הגדרות Docker |
| [`.env.example`](.env.example) | תבנית קובץ סביבה |
| [`tools/upload_bulk.py`](tools/upload_bulk.py) | כלי העלאה מרוכזת |
| [`backend/`](backend/) | קוד ה-Backend |
