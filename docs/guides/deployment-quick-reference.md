# Deployment Quick Reference - Hardware Config Update

## ✅ What's Been Done

**Updated Files:** 14 total
- **Backend:** 3 Python files
- **Frontend:** 3 JavaScript files
- **Config:** 2 CSV files (+ 2 backups)
- **Docs:** 2 guides
- **Tests:** 2 test scripts

**CSV Structure:**
```
OLD: hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate (10 columns)
NEW: hw_id,pos_id,ip,mavlink_port,serial_port,baudrate (6 columns)
```

> **Note:** Positions (x,y) are not in config.json. They come exclusively from trajectory CSV files (`shapes/swarm/processed/Drone {pos_id}.csv`).

---

## 🚀 Quick Deploy Guide

### For This GCS/Development Machine

**No action needed!** Files already updated:
- ✅ config.json has required fields with defaults
- ✅ config_sitl.csv has N/A values
- ✅ Backups created
- ✅ All tests passing

**To verify:**
```bash
python3 test_config_simple.py
```

### For Remote Drones (After Git Sync)

**The drones will automatically pull the updated config.json via git sync.**

**If you have Raspberry Pi 5 drones, update their entries:**
```csv
# Change from:
5,5,192.0.2.73,14555,/dev/ttyS0,57600

# To:
5,5,192.0.2.73,14555,/dev/ttyAMA0,57600
                        ^^^^^^^^^^^^
```

**Then restart drone service:**
```bash
ssh drone5
sudo systemctl restart coordinator
```

---

## 🔧 Hardware Port Reference

| Drone Type | Serial Port | Baudrate |
|------------|-------------|----------|
| Raspberry Pi 4 | `/dev/ttyS0` | 57600 |
| **Raspberry Pi 5** | `/dev/ttyAMA0` | 57600 |
| Jetson | `/dev/ttyTHS1` | 921600 |
| SITL | N/A | N/A |

---

## 🎯 Common Tasks

### Check Which Hardware a Drone Has
```bash
ssh drone_ip
cat /proc/cpuinfo | grep "Model"
```

### Update Single Drone's Serial Port
1. Open Mission Config UI in dashboard
2. Find the drone row
3. Click Edit
4. Select correct serial port from dropdown
5. Save

### Update All Drones to RP5

Use the Mission Config UI to update serial ports, or edit config.json directly.

### Verify Config Structure
```bash
python3 -c "import json; d=json.load(open('config.json')); print(f'Version: {d[\"version\"]}, Drones: {len(d[\"drones\"])}')"
```

---

## 🧪 Testing

### Backend Test
```bash
python3 test_config_simple.py
```
**Expected:** All tests pass ✓

### Frontend Test
```bash
cd app/dashboard/drone-dashboard
npm start
```
Navigate to Mission Config → verify new columns visible

### Integration Test
1. Update one drone's serial_port in config.json
2. Git push (auto-commit should work)
3. SSH to drone, verify config pulled
4. Restart coordinator
5. Check MAVLink connection

---

## 📋 Rollback Procedure

If something goes wrong:

```bash
# Record the failed and last-known-good revisions before changing the checkout
git rev-parse HEAD
git show --no-patch <last-known-good-tag-or-commit>

# Restore configuration backups when the release changed them
cp config.json.backup config.json
cp config_sitl.csv.backup config_sitl.csv

# Deploy the recorded last-known-good revision in a clean release checkout.
# Preserve the failed checkout and its logs for diagnosis.
git clone <official-repository-url> mds-rollback
cd mds-rollback
git checkout --detach <last-known-good-tag-or-commit>

# Restart services
sudo systemctl restart gcs-server
sudo systemctl restart coordinator
```

Verify the runtime mode, fleet identity, telemetry, Simurgh safety settings, and
unexpected SITL instance count after restart. Do not use an unscoped
`git reset --hard HEAD~1` as a production rollback procedure.

---

## 📖 Full Documentation

- **Migration Guide:** `docs/guides/csv-migration.md`
- **Implementation Summary:** `IMPLEMENTATION_SUMMARY.md`
- **Test Script:** `test_config_simple.py`

---

## ⚠️ Important Notes

1. **All RP4 drones work immediately** (defaults to `/dev/ttyS0`)
2. **RP5 drones need manual update** to `/dev/ttyAMA0`
3. **SITL mode unaffected** (uses N/A values, ignored)
4. **Not backward compatible** - old CSVs must be migrated to 6-column format
5. **Git sync works** - changes commit normally

---

## 🐛 Troubleshooting

**Issue:** Drone not connecting after update
```bash
# Check serial port
ssh drone_ip
ls -la /dev/tty* | grep -E "ttyS0|ttyAMA0|ttyTHS1"

# Verify config loaded
cat config.json | python3 -m json.tool | head -10
```

**Issue:** CSV upload fails
- Ensure header has exactly 6 columns: `hw_id,pos_id,ip,mavlink_port,serial_port,baudrate`
- No spaces around commas
- All rows have same column count

**Issue:** Git auto-commit fails
- Check CSV format (6 columns)
- Verify no syntax errors
- Review `git status` for details

---

## ✅ Deployment Checklist

**Before deploying to production:**
- [ ] Run test_config_simple.py (all pass)
- [ ] Verify hardware types for all drones
- [ ] Update RP5 drones to /dev/ttyAMA0
- [ ] Test one drone first
- [ ] Backup config.json
- [ ] Document any custom configurations

**After deploying:**
- [ ] Verify MAVLink connections
- [ ] Test mission execution
- [ ] Check git auto-commit
- [ ] Monitor for errors
- [ ] Update documentation if needed

---

## 🎉 Success Criteria

✅ All drones connect to Pixhawk
✅ MAVLink telemetry streaming
✅ Missions execute normally
✅ Git sync works
✅ Mixed hardware fleet operational (if applicable)

---

**Quick Help:** If stuck, check `test_config_simple.py` output for specific error details.
