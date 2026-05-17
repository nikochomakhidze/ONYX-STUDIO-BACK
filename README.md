# ONYX STUDIO — Backend Deploy Guide

## 1. Railway-ზე Backend Deploy

1. გადადი [railway.app](https://railway.app) → Sign Up (GitHub-ით)
2. **New Project → Deploy from GitHub repo**
   - ატვირთე `onyx-backend` ფოლდერი GitHub-ზე ჯერ
3. Environment Variables-ში დაამატე:
   ```
   JWT_SECRET=შეარჩიე-რანდომული-სტრინგი
   ANTHROPIC_API_KEY=sk-ant-...
   RESEND_API_KEY=re_...
   FROM_EMAIL=noreply@onyxstudio.ge
   FACEBOOK_APP_ID=...
   FACEBOOK_APP_SECRET=...
   FRONTEND_URL=https://შენი-სახელი.netlify.app
   BACKEND_URL=https://შენი-სახელი.up.railway.app
   ```
4. Deploy-ის შემდეგ მიიღებ URL-ს (მაგ: `https://onyx-backend-production.up.railway.app`)

---

## 2. Netlify-ზე Frontend Deploy

1. გადადი [netlify.app](https://netlify.app) → Sign Up
2. **Add new site → Deploy manually**
3. ატვირთე `index.html` ფაილი
4. მზადაა!

**მნიშვნელოვანი:** `index.html`-ში შეცვალე API URL:
```javascript
const API = 'https://შენი-railway-url.up.railway.app';
```

---

## 3. Facebook OAuth Setup

1. გადადი [developers.facebook.com](https://developers.facebook.com)
2. **Create App → Consumer**
3. Add Product → **Facebook Login**
4. Settings → Valid OAuth Redirect URIs:
   ```
   https://შენი-railway-url.up.railway.app/auth/facebook/callback
   ```
5. App ID და App Secret → Railway Environment Variables-ში

---

## 4. Resend Setup (Email)

1. გადადი [resend.com](https://resend.com) → Sign Up (უფასო)
2. API Keys → Create API Key
3. Domains → Add Domain (ან გამოიყენე Resend-ის უფასო domain)
4. API Key → Railway-ში `RESEND_API_KEY`

---

## Local Development

```bash
cd onyx-backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# შეავსე .env ფაილი
uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs
