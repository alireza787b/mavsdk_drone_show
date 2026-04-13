# SITL Control Interaction Hardening

Date: 2026-04-13

## Summary

This follow-up refinement reduces perceived page churn and makes the instance
workflow feel local to the selected container.

## What Changed

- background inventory refresh no longer shows a page-level refresh banner
- poll-driven SITL load failures now use a reusable throttled-toast helper
- compact/mobile layouts expand selected instance detail inline under the row
- wide desktop keeps the docked detail panel
- `Add next` and exact-slot add now live in one grouped control cluster

## Validation

- focused backend SITL Control tests: passed
- focused frontend SITL Control tests: passed

## Notes

- this pass keeps the earlier create-one API intact
- no customer-specific logic was added to official MDS
