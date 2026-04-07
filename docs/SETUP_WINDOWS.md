# מדריך הקמה מלא – Windows
## מערכת ניהול ראיות ומסמכים (PLMS)

> **הערת אבטחה חשובה ⚠️**  
> **אל תעלי קבצים אישיים / מסמכים / ראיות לתוך ריפו GitHub!**  
> קבצים עוברים **דרך האפליקציה** → נשמרים ב-**AWS S3** בלבד.  
> הריפו מכיל קוד בלבד.

---

## תוכן עניינים

- [A – הקמה מקומית על Windows](#a--הקמה-מקומית-על-windows)
- [B – הכנת משאבי AWS](#b--הכנת-משאבי-aws)
- [C – ייצוא קבצים מהמחשב ומ-Google Drive](#c--ייצוא-קבצים-מהמחשב-ומ-google-drive)
- [D – העלאה מרוכזת של קבצים (bulk upload)](#d--העלאה-מרוכזת-של-קבצים-bulk-upload)
- [E – פתרון בעיות נפוצות ב-Windows](#e--פתרון-בעיות-נפוצות-ב-windows)
- [F – אזהרת אבטחה: לא מעלים קבצים ל-GitHub!](#f--אזהרת-אבטחה-לא-מעלים-קבצים-ל-github)
- [G – קישורים מהירים בריפו](#g--קישורים-מהירים-בריפו)

---

## A – הקמה מקומית על Windows

### דרישות מקדימות

| כלי | קישור הורדה | בדיקת גרסה |
|-----|-------------|------------|
| **Docker Desktop for Windows** | https://www.docker.com/products/docker-desktop/ | `docker --version` |
| **Git for Windows** | https://git-scm.com/download/win | `git --version` |
| **Python 3.11+** | https://www.python.org/downloads/windows/ | `python --version` |

> **הערה:** בעת התקנת Python יש לסמן ✅ **"Add Python to PATH"**

---

### שלב 1 – התקנת Docker Desktop

1. הורידי את Docker Desktop מהקישור למעלה.
2. הפעילי את קובץ ה-`.exe` ועקבי אחרי האשף.
3. **הפעילי מחדש את המחשב** כשתתבקשי.
4. פתחי את Docker Desktop וודאי שהסמל בשורת המשימות ירוק (Running).
5. בחלון PowerShell:
   ```powershell
   docker --version
   docker-compose --version
   ```

---

### שלב 2 – שכפול הריפו

פתחי **PowerShell** (לחצי Start → "PowerShell") והריצי:

```powershell
# עברי לתיקייה שבה תרצי לשמור את הפרויקט
cd C:\Users\YourName\Projects

# שכפלי את הריפו
git clone https://github.com/edn22126-ops/efrat.git
cd efrat
```

---

### שלב 3 – הגדרת קובץ הסביבה (.env)

```powershell
# העתיקי את תבנית ה-.env
copy .env.example .env

# פתחי לעריכה (notepad או VS Code)
notepad .env
```

מלאי את הפרטים (ראי [חלק B](#b--הכנת-משאבי-aws) לפרטי AWS):

```env
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
S3_BUCKET=efrat-evidence-files
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/efrat-ocr-jobs
```

> ⚠️ **אל תשמרי קובץ `.env` ב-git!** הוא כבר מוכנס ל-`.gitignore`.

---

### שלב 4 – הרצת המערכת עם Docker Compose

```powershell
# מתוך תיקיית הפרויקט:
docker-compose up --build
```

המתיני עד שתראי את ההודעות:
```
backend_1  | INFO:     Application startup complete.
db_1       | LOG:  database system is ready to accept connections
```

#### אימות שהמערכת עובדת

פתחי דפדפן:
- **API Docs (Swagger):** http://localhost:8000/docs
- **Health check:** http://localhost:8000/health → אמור להחזיר `{"status": "ok"}`

---

### שלב 5 – הרצת Migrations (בפעם הראשונה)

פתחי PowerShell **חדש** (בזמן שה-compose רץ):

```powershell
cd C:\Users\YourName\Projects\efrat

docker-compose exec backend alembic upgrade head
```

הפקודה תיצור את טבלאות ה-DB: `documents`, `tags`, `audit_logs`.

---

### שלב 6 – עצירת המערכת

```powershell
# עצור (Ctrl+C בחלון הראשי), אח"כ:
docker-compose down

# עצור ומחק נתונים (DB):
docker-compose down -v
```

---

## B – הכנת משאבי AWS

> **הערה:** תצטרכי חשבון AWS פעיל. אם אין – פתחי בחינם ב- https://aws.amazon.com/free/

---

### B.1 – יצירת S3 Bucket לקבצי ראיות

1. כנסי ל-[AWS Console](https://console.aws.amazon.com) → **S3** → **Create bucket**
2. שם: `efrat-evidence-files` (חייב להיות ייחודי גלובלית)
3. Region: `us-east-1` (או כל region שקרוב אלייך)
4. **Block all public access** → ✅ (השאירי מסומן – זה חשוב לאבטחה)
5. **Versioning** → Enable (מומלץ)
6. **Encryption** → Server-side encryption with Amazon S3-managed keys (SSE-S3)
7. לחצי **Create bucket**

---

### B.2 – יצירת IAM User עם הרשאות מינימליות

1. AWS Console → **IAM** → **Users** → **Create user**
2. שם: `efrat-app-user`
3. בחרי **"Attach policies directly"** → לחצי **Create policy** (JSON):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::efrat-evidence-files",
        "arn:aws:s3:::efrat-evidence-files/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "textract:DetectDocumentText",
        "textract:AnalyzeDocument"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-1:*:efrat-ocr-jobs"
    }
  ]
}
```

4. שמרי ה-Policy בשם `EfratAppPolicy`, צרפי ל-User.
5. צרי **Access Key**: Users → Security credentials → **Create access key** → Application running outside AWS
6. **שמרי את ה-Key ID וה-Secret** (מופיעים פעם אחת בלבד!) → הכניסי ל-`.env`

---

### B.3 – RDS Postgres

לסביבת ייצור (production) מומלץ RDS. בסביבה מקומית Docker מטפל ב-Postgres.

1. AWS Console → **RDS** → **Create database**
2. Engine: **PostgreSQL 15**
3. Template: **Free tier** (לבדיקות) / Production (בייצור)
4. DB identifier: `efrat-db`
5. Master username: `efrat`, סיסמה: בחרי סיסמה חזקה
6. Instance class: `db.t3.micro` (Free tier)
7. Storage: 20 GB gp2
8. **Connectivity** → VPC ברירת מחדל, Public access: **No** (אם השרת ב-EC2/ECS) / **Yes** (לבדיקות זמניות)
9. לאחר יצירה, עדכני `DATABASE_URL` ב-`.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://efrat:PASSWORD@efrat-db.xxxx.us-east-1.rds.amazonaws.com:5432/efrat
   ```

---

### B.4 – SQS Queue לעבודות OCR

1. AWS Console → **SQS** → **Create queue**
2. Type: **Standard**
3. Name: `efrat-ocr-jobs`
4. Message retention: 4 days
5. לחצי **Create Queue**
6. העתיקי את ה-**Queue URL** ל-`.env`:
   ```
   SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/efrat-ocr-jobs
   ```

---

## C – ייצוא קבצים מהמחשב ומ-Google Drive

### C.1 – קבצים מהמחשב המקומי

פשוט תאתרי את התיקיות הרלוונטיות ותשכפלי ל-"staging folder":

```powershell
# דוגמה: העתיקי כל קבצי PDF מ-Documents לתיקיית עבודה
robocopy "C:\Users\YourName\Documents" "C:\Staging\Evidence" *.pdf *.docx *.jpg /S /E

# בדקי כמה קבצים:
(Get-ChildItem "C:\Staging\Evidence" -Recurse -File).Count
```

---

### C.2 – ייצוא מ-Google Drive (מומלץ: rclone)

**rclone** הוא כלי חינמי ומאובטח להורדה מ-Google Drive:

#### התקנה:
1. הורידי את הגרסה ל-Windows: https://rclone.org/downloads/
2. חלצי את ה-`.exe` לתיקיית `C:\rclone\`
3. הוסיפי ל-PATH (הסבר: [rclone docs](https://rclone.org/install/#windows))

#### הגדרת Google Drive:
```powershell
rclone config
```
עקבי אחרי האשף:
- בחרי `n` (New remote)
- Name: `gdrive`
- Type: `drive` (Google Drive)
- אמתי דרך הדפדפן שייפתח

#### הורדה מ-Google Drive:
```powershell
# הורידי תיקייה ספציפית:
rclone copy gdrive:"שם תיקייה ב-Drive" "C:\Staging\Evidence\gdrive" --progress

# הורידי הכל:
rclone copy gdrive: "C:\Staging\Evidence\gdrive" --progress

# צפי מה יורד לפני שמורידים:
rclone ls gdrive: | head -50
```

> **חלופה:** Google Drive for Desktop – https://www.google.com/drive/download/  
> מסנכרן כל הקבצים אוטומטית לתיקייה מקומית.

---

## D – העלאה מרוכזת של קבצים (bulk upload)

### דרישות:

```powershell
pip install requests tqdm
```

### שימוש בסיסי:

```powershell
# ודאי שהמערכת רצה (docker-compose up)
# ואז:

python tools\upload_bulk.py `
    --folder "C:\Staging\Evidence" `
    --api-url "http://localhost:8000" `
    --category "legal" `
    --tags "2024,court"
```

### אפשרויות מלאות:

| אפשרות | תיאור | ברירת מחדל |
|--------|-------|-----------|
| `--folder` | נתיב לתיקיית הקבצים | (חובה) |
| `--api-url` | כתובת ה-API | `http://localhost:8000` |
| `--category` | קטגוריה לכל הקבצים | ריק |
| `--tags` | תגיות (מופרדות בפסיק) | ריק |
| `--recursive` | סרוק תת-תיקיות | לא |
| `--output-csv` | שם קובץ CSV של תוצאות | `upload_results.csv` |

### דוגמאות נוספות:

```powershell
# העלאה רקורסיבית עם קטגוריה ותגיות
python tools\upload_bulk.py `
    --folder "C:\Staging\Evidence" `
    --recursive `
    --category "medical" `
    --tags "2023,doctor,important" `
    --output-csv "C:\Logs\upload_2024.csv"

# העלאה מ-Google Drive (אחרי rclone download)
python tools\upload_bulk.py `
    --folder "C:\Staging\Evidence\gdrive" `
    --category "gdrive-export" `
    --tags "google-drive,backup"
```

### בדיקת תוצאות:

אחרי ההעלאה:
- פתחי `upload_results.csv` ב-Excel
- בדקי שעמודת `status` מציגה `ok` לכל הקבצים
- בדקי ב-Swagger: http://localhost:8000/docs → GET /documents

---

## E – פתרון בעיות נפוצות ב-Windows

### ❌ "Docker Desktop is not running"

**פתרון:**
1. פתחי Docker Desktop מה-Start Menu
2. המתיני שהסמל בשורת המשימות יהפוך לירוק
3. נסי שוב את הפקודה

---

### ❌ "port 5432 already in use"

Postgres מקומי פועל ומתנגש עם Docker.

**פתרון:** שני אפשרויות –
1. עצרי את Postgres המקומי:
   ```powershell
   Stop-Service -Name postgresql*
   ```
2. **או** שני את ה-port ב-`docker-compose.yml`:
   ```yaml
   ports:
     - "5433:5432"   # מפה port 5433 מחוץ ל-5432 בפנים
   ```

---

### ❌ "port 8000 already in use"

```powershell
# מצאי מה תופס את הפורט:
netstat -ano | findstr :8000

# הרגי את התהליך (החלפי XXXX ב-PID):
taskkill /PID XXXX /F
```

---

### ❌ "WSL 2 installation is incomplete"

Docker ב-Windows דורש WSL 2.

**פתרון:**
```powershell
# הריצי ב-PowerShell כ-Administrator:
wsl --install
wsl --update
wsl --set-default-version 2
```
הפעילי מחדש את המחשב.

---

### ❌ "Error response from daemon: Mounts denied"

Docker לא מורשה לגשת לתיקיית הפרויקט.

**פתרון:**
1. פתחי Docker Desktop → Settings → Resources → **File Sharing**
2. הוסיפי את הנתיב `C:\Users\YourName\Projects\efrat`
3. Apply & Restart

---

### ❌ "python is not recognized"

Python לא ב-PATH.

**פתרון:**
1. פתחי Settings → Apps → Advanced app settings → **App execution aliases**
2. כבי את `python.exe` ו-`python3.exe` aliases
3. התקיני Python מחדש עם ✅ "Add Python to PATH"

---

### ❌ הסקריפט לא מוצא קבצים

ודאי שהנתיב נכון:
```powershell
# בדקי שהתיקייה קיימת:
Test-Path "C:\Staging\Evidence"

# ספרי קבצים:
(Get-ChildItem "C:\Staging\Evidence" -Recurse -File).Count
```

---

### ❌ שגיאת "AWS credentials" / "NoCredentialsError"

1. ודאי שקובץ `.env` קיים ומלאה בו את הפרטים
2. ודאי ש-`AWS_ACCESS_KEY_ID` ו-`AWS_SECRET_ACCESS_KEY` מלאות
3. הרצי `docker-compose down && docker-compose up --build` כדי לטעון מחדש

---

### טיפ כללי – לוגים של Docker

```powershell
# ראי לוגים בזמן אמת:
docker-compose logs -f backend

# ראי לוגים של כל ה-services:
docker-compose logs -f
```

---

## F – אזהרת אבטחה: לא מעלים קבצים ל-GitHub!

### ✅ מה כן להכניס ל-Git (הריפו):
- קוד Python / YAML / SQL
- קובץ `.env.example` (ללא ערכים אמיתיים)
- Documentation / README

### ❌ מה אסור להכניס ל-Git:
- קבצי ראיות, מסמכים, תמונות, PDF
- קובץ `.env` עם מפתחות אמיתיים
- מפתחות AWS / סיסמאות
- קבצים אישיים מכל סוג

### מבנה נכון:
```
GitHub Repo (efrat)
└── קוד בלבד

AWS S3 (efrat-evidence-files)
└── documents/
    └── <uuid>/<filename>  ← כל הקבצים האישיים נשמרים כאן

AWS RDS (PostgreSQL)
└── מטה-דאטה, תגיות, OCR text, audit trail
```

### בדיקה שלא הכנסת קבצים בטעות:
```powershell
# בדקי מה git עומד לשלוח:
git status
git diff --staged

# אם יש קבצים שלא אמורים להיות שם:
git reset HEAD <filename>
```

---

## G – קישורים מהירים בריפו

| קובץ/תיקייה | תיאור |
|-------------|-------|
| [`README.md`](../README.md) | דף הבית של הפרויקט |
| [`docker-compose.yml`](../docker-compose.yml) | הגדרות Docker (DB + Backend + Worker) |
| [`.env.example`](../.env.example) | תבנית קובץ הסביבה |
| [`backend/`](../backend/) | קוד Python/FastAPI |
| [`backend/app/main.py`](../backend/app/main.py) | נקודת כניסה לאפליקציה |
| [`backend/app/api/`](../backend/app/api/) | נתיבי API (documents, upload, search) |
| [`backend/app/models/`](../backend/app/models/) | מודלי DB (Document, Tag, AuditLog) |
| [`backend/migrations/`](../backend/migrations/) | Alembic migrations |
| [`tools/upload_bulk.py`](../tools/upload_bulk.py) | כלי להעלאה מרוכזת של קבצים |
| [`docs/SETUP_WINDOWS.md`](SETUP_WINDOWS.md) | מדריך זה |

### API Endpoints עיקריים

| Method | Path | תיאור |
|--------|------|-------|
| GET | `/health` | בדיקת תקינות |
| GET | `/docs` | Swagger UI |
| GET | `/documents/` | רשימת מסמכים |
| GET | `/documents/{id}` | מסמך בודד |
| DELETE | `/documents/{id}` | מחיקת מסמך |
| POST | `/upload/presign` | בקשת URL להעלאה |
| POST | `/upload/confirm` | אישור העלאה + תור OCR |
| GET | `/search/?q=…` | חיפוש טקסט מלא |

---

*מדריך זה עודכן: אפריל 2026*
