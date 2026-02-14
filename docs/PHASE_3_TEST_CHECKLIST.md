# Phase 3 Manual Test Checklist

## 1. Authentication & API Client Initialization
- [ ] Start the backend server (`python web_interface/app.py`).
- [ ] Start the desktop application (`python start.py`).
- [ ] Login with valid credentials.
- [ ] Verify `shopkeeper_app.log` contains: `API session token obtained successfully`.
- [ ] (Edge Case) Stop backend server, then login. Verify `shopkeeper_app.log` contains: `Could not obtain API session token: Cannot connect to backend API`.

## 2. Dashboard API Loading
- [ ] With backend server running, open the Dashboard.
- [ ] Verify `shopkeeper_app.log` contains: `Using API data for Dashboard KPIs`.
- [ ] Verify KPIs (Total Jobs, Revenue, etc.) match expectations.
- [ ] (Fallback Test) Stop backend server and click refresh (or wait for auto-refresh).
- [ ] Verify `shopkeeper_app.log` contains: `API Dashboard fetch failed, falling back to database`.
- [ ] Verify KPIs are still displayed correctly (now from DB).

## 3. Configuration & Pricing API Loading
- [ ] Navigate to "Pricing" or "Profile" page.
- [ ] Verify `shopkeeper_app.log` contains: `Shop configuration fetched successfully from API`.
- [ ] (Fallback Test) Stop backend server and reload page.
- [ ] Verify `shopkeeper_app.log` contains: `API Config fetch failed, falling back to database`.
- [ ] Verify pricing values are still loaded correctly from DB.

## 4. UI Stability & Performance
- [ ] Verify Recent Jobs list on Dashboard displays items correctly regardless of source (API or DB).
- [ ] Verify switching pages does not cause stuttering or freezes (especially with backend stopped).
- [ ] Verify no "401 Unauthorized" popups appear (handled silently in background).

## 5. Printing Verification (No Regression)
- [ ] Select a job and click "Print".
- [ ] Verify job status updates to "Printing" then "Completed".
- [ ] Verify local database is updated as expected.
- [ ] Verify actual printer output (if printer available).
