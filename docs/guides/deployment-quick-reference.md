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
OLD: hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip (8 columns)
NEW: hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate (10 columns)
```

---

## 🚀 Quick Deploy Guide

### For This GCS/Development Machine

**No action needed!** Files already updated:
- ✅ config.csv has new columns with defaults
- ✅ config_sitl.csv has N/A values
- ✅ Backups created
- ✅ All tests passing

**To verify:**
```bash
python3 test_config_simple.py
```

### For Remote Drones (After Git Sync)

**The drones will automatically pull the updated config.csv via git sync.**

**If you have Raspberry Pi 5 drones, update their entries:**
```csv
# Change from:
5,5,-2.5,-10.0,100.96.177.73,14555,13545,100.96.32.75,/dev/ttyS0,57600

# To:
5,5,-2.5,-10.0,100.96.177.73,14555,13545,100.96.32.75,/dev/ttyAMA0,57600
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
```bash
sed -i 's|/dev/ttyS0|/dev/ttyAMA0|g' config.csv
```

### Verify CSV Structure
```bash
head -1 config.csv
# Should show: hw_id,pos_id,x,y,ip,mavlink_port,debug_port,gcs_ip,serial_port,baudrate
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
1. Update one drone's serial_port in config.csv
2. Git push (auto-commit should work)
3. SSH to drone, verify config pulled
4. Restart coordinator
5. Check MAVLink connection

---

## 📋 Rollback Procedure

If something goes wrong:

```bash
# Restore backups
cp config.csv.backup config.csv
cp config_sitl.csv.backup config_sitl.csv

# Revert code changes
git checkout HEAD~1 gcs-server/config.py
git checkout HEAD~1 functions/read_config.py
git checkout HEAD~1 src/drone_config.py
# ... (or just git reset --hard HEAD~1)

# Restart services
sudo systemctl restart gcs-server
sudo systemctl restart coordinator
```

---

## 📖 Full Documentation

- **Migration Guide:** `docs/CONFIG_CSV_MIGRATION_GUIDE.md`
- **Implementation Summary:** `IMPLEMENTATION_SUMMARY.md`
- **Test Script:** `test_config_simple.py`

---

## ⚠️ Important Notes

1. **All RP4 drones work immediately** (defaults to `/dev/ttyS0`)
2. **RP5 drones need manual update** to `/dev/ttyAMA0`
3. **SITL mode unaffected** (uses N/A values, ignored)
4. **Backward compatible** - old CSVs auto-upgrade with defaults
5. **Git sync works** - changes commit normally

---

## 🐛 Troubleshooting

**Issue:** Drone not connecting after update
```bash
# Check serial port
ssh drone_ip
ls -la /dev/tty* | grep -E "ttyS0|ttyAMA0|ttyTHS1"

# Verify config loaded
cat config.csv | grep "^DRONE_HW_ID,"
```

**Issue:** CSV upload fails
- Ensure header has exactly 10 columns
- No spaces around commas
- All rows have same column count

**Issue:** Git auto-commit fails
- Check CSV format (10 columns)
- Verify no syntax errors
- Review `git status` for details

---

## ✅ Deployment Checklist

**Before deploying to production:**
- [ ] Run test_config_simple.py (all pass)
- [ ] Verify hardware types for all drones
- [ ] Update RP5 drones to /dev/ttyAMA0
- [ ] Test one drone first
- [ ] Backup config.csv
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
