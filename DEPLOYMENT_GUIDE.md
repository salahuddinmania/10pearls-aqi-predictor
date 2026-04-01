# 🚀 GitHub Actions & Streamlit Cloud Setup Guide

## What's Configured

Your project now has **fully automated CI/CD** with GitHub Actions and **live dashboard** on Streamlit Cloud!

### GitHub Actions Workflows

#### 1. **Feature Pipeline** (`.github/workflows/feature_pipeline.yml`)
- **Schedule:** Runs **every hour** at minute 0
- **Trigger:** `0 * * * *` (UTC)
- **What it does:** Fetches latest weather data from Open-Meteo API and updates feature store
- **Manual trigger:** Available via GitHub Actions UI

#### 2. **Training Pipeline** (`.github/workflows/training_pipeline.yml`)
- **Schedule:** Runs **daily at 00:30 UTC** 
- **Trigger:** `30 0 * * *` (UTC)
- **What it does:** Trains models, evaluates metrics, updates model registry
- **Manual trigger:** Available via GitHub Actions UI

#### 3. **Dashboard Deployment** (`.github/workflows/streamlit-deploy.yml`)
- **Trigger:** On every push to `main` or `master` branch
- **What it does:** Auto-deploys latest code to Streamlit Cloud
- **Live URL:** `https://aqi-predictor.streamlit.app` (after setup)

### Streamlit Configuration
- **Entry Point:** `streamlit_app.py` (root directory)
- **Config File:** `.streamlit/config.toml` (Streamlit settings & theme)
- **Secrets:** Environment variables via Streamlit Cloud secrets panel

---

## Step-by-Step Deployment Instructions

### Step 1: Push to GitHub

```bash
git add .
git commit -m "refactor: Clean up code and setup CI/CD automation"
git push origin main
```

### Step 2: Configure GitHub Secrets

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:
   
   | Secret Name | Value |
   |---|---|
   | `SUPABASE_URL` | Your Supabase project URL |
   | `SUPABASE_KEY` | Your Supabase anon key |

3. Save each secret

### Step 3: Deploy Dashboard to Streamlit Cloud

1. Visit [streamlit.io/cloud](https://streamlit.io/cloud)
2. Click **New app**
3. Select:
   - **Repository:** Your forked repo
   - **Branch:** main
   - **Main file path:** `streamlit_app.py`
4. Click **Deploy**

### Step 4: Add Streamlit Cloud Secrets

1. In Streamlit Cloud app settings, click **Secrets** (bottom left)
2. Copy-paste your `.env` content:
   ```
   SUPABASE_URL=your_url
   SUPABASE_KEY=your_key
   ```
3. Save

**Your dashboard is now live! 🎉**

---

## Workflow Automation Timeline

| Time (UTC) | Action |
|---|---|
| Hourly (0:00, 1:00, 2:00...) | ⬆️ Feature Pipeline updates data |
| 00:30 | 🧠 Training Pipeline trains models |
| On Git Push | 🎨 Dashboard auto-deploys to Streamlit Cloud |

---

## Monitoring Workflows

### View Workflow Runs
1. Go to **Actions** tab on GitHub
2. Select workflow to see all past and current runs
3. Click a run to see detailed logs

### Debugging Failed Workflows
- Check the **Logs** tab for error details
- Common issues:
  - Missing GitHub Secrets
  - Incorrect Supabase credentials
  - Network timeouts (retry manually)

---

## Files Added/Modified

| File | Purpose |
|---|---|
| `.github/workflows/feature_pipeline.yml` | Hourly feature updates |
| `.github/workflows/training_pipeline.yml` | Daily model training |
| `.github/workflows/streamlit-deploy.yml` | Auto-deploy to Streamlit |
| `.streamlit/config.toml` | Streamlit theme & settings |
| `streamlit_app.py` | Dashboard entry point |
| `.gitignore` | Enhanced with Streamlit secrets |
| `README.md` | Added CI/CD documentation |

---

## Best Practices

✅ **Never commit `.env` file** - Use GitHub Secrets instead  
✅ **Monitor workflow runs** - Especially first deployment  
✅ **Test locally first** - Run `streamlit run streamlit_app.py` locally  
✅ **Keep secrets secure** - Rotate API keys quarterly  
✅ **Review logs** - Check for warnings/errors in automation  

---

## Useful Commands

```bash
# Run feature pipeline locally
python src/features/feature_pipeline.py

# Run training locally
python src/models/train_model.py

# Run dashboard locally
streamlit run streamlit_app.py
```

---

## Next Steps (Optional Enhancements)

- [ ] Add Slack/Email notifications for failed workflows
- [ ] Setup branch protection rules (require passing tests)
- [ ] Add linting (pylint) to CI/CD
- [ ] Create pytest suite for unit tests
- [ ] Add performance monitoring dashboard

---

**Your project is now production-ready with full CI/CD automation! 🚀**
