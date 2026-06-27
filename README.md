## Data Sources

> ⚠️ **Security Notice:** Real revenue files are excluded from this repository for privacy compliance. A minimal sample dataset demonstrating schema structure is included in `/data/sample/`. Production deployments require secure authentication against external APIs or authorized CSV exports.

| Platform | Format | Sample Available | Full Implementation |
|----------|--------|------------------|---------------------|
| ACX Audiobook Reports | Excel (.xlsx) | ✅ Yes | ✅ Yes |
| Amazon KDP | Excel (.xlsx) | 🔲 Planned | 🔲 Pending |
| Draft2Digital | CSV | 🔲 Planned | 🔲 Pending |

To test with your own data:
```bash
mkdir data/raw/acx-new
# Place your royalty export files here
python src/main.py --process-all