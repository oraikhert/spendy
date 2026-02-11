# Install and run troubleshooting

## Successful install

If install worked:

- **Virtual environment** exists (`venv/`), dependencies are installed.
- **Scripts:** `./install.sh` — install (venv + deps, with SSL workaround if needed); `./start.sh` — run the app.
- **Check:** Activate venv (`source venv/bin/activate`), run `python -c "import fastapi; import uvicorn; print('OK')"`, then `python run.py`. You should see "Database initialized" and "Uvicorn running on http://0.0.0.0:8000".
- **Next:** Open http://localhost:8000/docs and try the API (`python test_api.py`). If something fails, use the sections below.

---

## Problem 1: "externally-managed-environment"

**Symptoms:**
```
error: externally-managed-environment
× This environment is externally managed
```

**Cause:** On macOS, Python from Homebrew does not allow global package installs.

**Fix:** Use a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Or run: `./install.sh`

---

## Problem 2: SSL certificate errors

**Symptoms:**
```
SSLError(SSLCertVerificationError('OSStatus -26276'))
Could not fetch URL https://pypi.org/simple/...
```

**Cause:** Python on macOS may not have SSL certificates configured.

**Fix 1 — Quick (trusted hosts):**

```bash
source venv/bin/activate
pip install --trusted-host pypi.org \
            --trusted-host pypi.python.org \
            --trusted-host files.pythonhosted.org \
            -r requirements.txt
```

Or run: `./install.sh` (it will use these flags if needed).

**Fix 2 — Permanent (install certs):**

**Option A:** Run:
```bash
/usr/local/bin/python3 -m pip install --upgrade certifi
/Applications/Python\ 3.*/Install\ Certificates.command
```

**Option B — Manual:** Install certifi and check paths:
```bash
pip install --upgrade certifi

cat << EOF > /tmp/fix_ssl.py
import ssl
import certifi

print(f"Default SSL paths: {ssl.get_default_verify_paths()}")
print(f"Certifi bundle: {certifi.where()}")
EOF

python /tmp/fix_ssl.py
```

---

## Problem 3: Package versions not compatible with Python 3.13

**Symptoms:** `ERROR: Could not find a version that satisfies the requirement...`

**Fix:** `requirements.txt` uses flexible versions (`>=`). If it still fails:

```bash
pip install --upgrade pip
pip install fastapi
pip install uvicorn[standard]
# etc. one by one to see which fails
```

---

## Problem 4: Missing system dependencies

**Symptoms:**
```
error: command 'gcc' failed
error: Microsoft Visual C++ 14.0 is required
```

**macOS:**
```bash
xcode-select --install
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3-dev python3-pip build-essential libpq-dev
```

**Windows:** Install Visual Studio Build Tools, or use WSL2 with Ubuntu.

---

## Problem 5: psycopg2-binary install fails

**Symptoms:** `ERROR: Failed building wheel for psycopg2-binary`

**Fix 1 — Use SQLite only:** Remove `psycopg2-binary>=2.9.9` from `requirements.txt`.

**Fix 2 — Install system deps:**

**macOS:** `brew install postgresql`

**Linux:** `sudo apt-get install libpq-dev`

---

## Problem 6: Port 8000 already in use

**Symptoms:** `ERROR: [Errno 48] Address already in use`

**Fix:** Change port in `run.py`:

```python
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,  # e.g. 8001 instead of 8000
        reload=True
    )
```

Or find and stop the process:
```bash
lsof -i :8000
kill -9 <PID>
```

---

## Problem 6b: Missing tables (e.g. accounts, transactions)

**Symptoms:** `no such table: accounts` or similar after pulling transaction features.

**Fix:** Apply migrations with venv active and from project root:

```bash
source venv/bin/activate
alembic upgrade head
```

See [MIGRATIONS.md](MIGRATIONS.md).

---

## Problem 7: Module not found on run

**Symptoms:**
```
ModuleNotFoundError: No module named 'fastapi'
ModuleNotFoundError: No module named 'app'
```

**Fix:**

1. Activate venv: `source venv/bin/activate` (prompt should show `(venv)`).
2. Run from project root: `pwd` should be the spendy project directory.
3. Install deps: `pip list | grep fastapi`.

---

## Problem 8: Database file not created

**Symptoms:** `sqlite3.OperationalError: unable to open database file`

**Fix:** Check permissions:

```bash
pwd
ls -la
chmod +w .   # if needed
```

---

## Quick check script

Run this to check your environment:

```bash
cat << 'EOF' > check_env.sh
#!/bin/bash
echo "=== Spendy environment check ==="
echo ""
echo "1. Python:"
python3 --version
echo ""
echo "2. venv:"
if [ -d "venv" ]; then echo "✅ Found"; else echo "❌ Not found - run: python3 -m venv venv"; fi
echo ""
echo "3. venv active:"
if [[ "$VIRTUAL_ENV" != "" ]]; then echo "✅ $VIRTUAL_ENV"; else echo "❌ Run: source venv/bin/activate"; fi
echo ""
echo "4. Packages:"
pip list 2>/dev/null | grep -E "fastapi|uvicorn|sqlalchemy" || echo "❌ Not installed"
echo ""
echo "5. Project files:"
ls -1 app/*.py 2>/dev/null | head -5 || echo "❌ Not found"
echo "==================================="
EOF

chmod +x check_env.sh
./check_env.sh
```

---

## Still not working: full reinstall

```bash
rm -rf venv
rm -f spendy.db
pip cache purge

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install --trusted-host pypi.org \
            --trusted-host pypi.python.org \
            --trusted-host files.pythonhosted.org \
            -r requirements.txt

python run.py
```

---

## Get help

If the problem remains:

1. Check Python: `python3 --version` (3.10+ required).
2. Check full error and logs.
3. Open a GitHub issue with: Python version, OS, full error text, and `pip list` output.

---

## Useful commands

```bash
python3 --version
pip --version
pip list
pip install --upgrade pip
pip cache purge
which python
deactivate
```
