# Git Setup Commands

Run these commands in order in the `wifi-dashboard-v2` directory:

```bash
# 1. Initialize git repository
git init

# 2. Add all files
git add .

# 3. Create initial commit
git commit -m "Initial commit: Wi-Fi Dashboard v2.0 - Containerized Manager-Worker Architecture"

# 4. Set main branch
git branch -M main

# 5. Add remote (if you haven't already created the repo on GitHub, do that first)
git remote add origin https://github.com/danryan06/wifi-dashboard-v2.git

# 6. Push to GitHub
git push -u origin main
```

## If the GitHub repo doesn't exist yet:

1. Go to https://github.com/new
2. Repository name: `wifi-dashboard-v2`
3. Description: "Containerized Wi-Fi Test Dashboard v2.0 - Manager-Worker Architecture"
4. Set to **Public** (or Private)
5. **DO NOT** initialize with README, .gitignore, or license
6. Click "Create repository"
7. Then run the commands above

## Verify after pushing:

```bash
# Check the setup script is accessible
curl -I https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh
```

Should return `200 OK`.
