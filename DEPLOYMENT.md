# Deploying GPS Emergency Tracker on Render

This guide outlines how to deploy the production-ready Flask & WebSockets application to Render.

---

## Prerequisites

1. A **GitHub** repository containing your project.
2. A **Render** account (sign up free at [render.com](https://render.com)).
3. (Optional) Credentials for **Twilio** (SMS/Calls) and **Gmail SMTP** (Emails) if you want active alerting enabled in production.

---

## Step-by-Step Deployment Guide

### Step 1: Push Project to GitHub
Commit all local changes and push the codebase to your GitHub repository:
```bash
git add .
git commit -m "Configure for Render production deployment"
git push origin main
```

### Step 2: Create a Render Account
Log in to your dashboard at [dashboard.render.com](https://dashboard.render.com).

### Step 3: Connect Your GitHub Repository
1. In the Render dashboard, click the **New +** button in the top right and select **Web Service**.
2. Connect your GitHub account and select your project repository from the list.

### Step 4: Configure Web Service Details
Fill in the following details:
- **Name**: `gps-emergency-tracker` (or your choice)
- **Region**: Select the region closest to your target audience.
- **Branch**: `main`
- **Runtime**: `Python`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn --worker-class eventlet -w 1 app:app`

*(Note: The eventlet worker class is required to handle WebSocket connections for real-time tracking updates.)*

### Step 5: Select Plan
Select the **Free** tier (or paid tiers if you require persistent storage or more resources).

---

## Step 6: Configure Environment Variables

Click the **Advanced** button or go to the **Environment** tab, then add the following environment variables:

| Variable | Recommended / Default Value | Description |
| :--- | :--- | :--- |
| `SECRET_KEY` | *(Click "Generate" or enter a long random string)* | Used for session encryption. |
| `ADMIN_EMAIL` | `admin@gpstracker.com` | Primary admin dashboard login email. |
| `ADMIN_PASSWORD` | `admin123` *(Change in production)* | Primary admin dashboard password. |
| `MAIL_SERVER` | `smtp.gmail.com` | SMTP Server (defaults to Gmail). |
| `MAIL_PORT` | `587` | TLS Port for Gmail SMTP. |
| `MAIL_USERNAME` | *(Your Gmail email, e.g., email@gmail.com)* | Email login for SMTP alerts. |
| `MAIL_PASSWORD` | *(Your 16-character Gmail App Password)* | App password from Google Account settings. |
| `TWILIO_ACCOUNT_SID` | `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` | Your Twilio Account SID. |
| `TWILIO_AUTH_TOKEN` | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` | Your Twilio Auth Token. |
| `TWILIO_FROM_NUMBER` | `+1XXXXXXXXXX` | Your Twilio purchased phone number. |
| `DATABASE_URL` | *(Optional, see Database Persistence below)* | Remote database URI. |

---

## Database Persistence on Render

By default, Render's web service uses a local SQLite database (`gps_tracker.db`). However, **Render's filesystem is ephemeral**, meaning all SQLite database changes will be wiped on restarts, redeploys, or regular service cycles.

### Option A: Use Render PostgreSQL (Recommended)
1. In the Render dashboard, click **New +** -> **PostgreSQL**.
2. Copy the **Internal Database URL** or **External Database URL**.
3. Go back to your Web Service -> **Environment** tab.
4. Add a new variable `DATABASE_URL` and paste the database URL. The application will automatically rewrite legacy `postgres://` to `postgresql://` and build the tables on startup.

### Option B: Use Render Persistent Disk
1. In your Web Service configuration, go to the **Disks** section.
2. Click **Add Disk**:
   - **Name**: `sqlite-data`
   - **Mount Path**: `/data`
   - **Size**: `1 GB` (Free tier limit is usually sufficient)
3. Under environment variables, set the path to your database:
   - `DATABASE_URL=sqlite:////data/gps_tracker.db`
4. Click Save to mount the persistent disk.

---

### Step 7: Deploy
Click **Create Web Service** at the bottom of the page. Render will build your dependencies, create database tables, seed the admin user, and start the service!

Once the log shows `Initializing WebSockets` and `Gunicorn running`, click the generated live link to open your production-ready GPS Emergency Tracker.
