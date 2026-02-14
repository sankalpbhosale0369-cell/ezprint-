# Phase 2: Quick Start Testing Guide
## Test the New APIs in 5 Minutes

**Date:** 2026-02-09  
**Status:** Ready for Testing

---

## Prerequisites

1. **Backend server is running**
   ```bash
   python start.py
   ```

2. **You have valid shopkeeper credentials**
   - Username or email
   - Password

---

## Quick Test (5 Minutes)

### Step 1: Login (Get Token)

**Copy and run this command** (replace with your credentials):

```bash
curl -X POST http://localhost:5000/api/auth/login -H "Content-Type: application/json" -d "{\"username\":\"YOUR_USERNAME\",\"password\":\"YOUR_PASSWORD\"}"
```

**Expected output:**
```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "shop_id": "abc-123-...",
    ...
  }
}
```

**✅ SAVE THE TOKEN AND SHOP_ID!**

---

### Step 2: Get Dashboard Data

**Copy and run this command** (replace TOKEN and SHOP_ID):

```bash
curl -X GET "http://localhost:5000/api/shop/YOUR_SHOP_ID/dashboard?period=today&limit=10" -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected output:**
```json
{
  "success": true,
  "data": {
    "kpis": {
      "total_jobs": 42,
      "pending_jobs": 5,
      "total_revenue": 1250.50,
      ...
    },
    "jobs": [...]
  }
}
```

**✅ Check that KPIs match your desktop dashboard!**

---

### Step 3: Get Pricing

**Copy and run this command:**

```bash
curl -X GET "http://localhost:5000/api/shop/YOUR_SHOP_ID/pricing" -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected output:**
```json
{
  "success": true,
  "data": {
    "bw_single": 2.0,
    "bw_double": 1.5,
    "color_single": 10.0,
    "color_double": 8.0
  }
}
```

**✅ Check that pricing matches your desktop settings!**

---

### Step 4: Update Pricing

**Copy and run this command:**

```bash
curl -X PUT "http://localhost:5000/api/shop/YOUR_SHOP_ID/pricing" -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" -d "{\"bw_single\":2.5}"
```

**Expected output:**
```json
{
  "success": true,
  "message": "Pricing updated successfully",
  "data": {
    "bw_single": 2.5,
    ...
  }
}
```

**✅ Verify pricing was updated in database!**

---

### Step 5: Verify Backward Compatibility

**Open your desktop app:**
1. Login with same credentials
2. Check dashboard loads
3. Check jobs list loads
4. Check pricing settings load

**✅ Desktop should still work with direct DB access!**

---

## Test Results

### ✅ Success Criteria:

- [ ] Login returns session_token
- [ ] Dashboard returns KPIs and jobs
- [ ] Pricing returns correct values
- [ ] Pricing update works
- [ ] Desktop app still works (direct DB)

### ❌ If Any Test Fails:

1. Check backend logs for errors
2. Verify credentials are correct
3. Verify shop_id is correct
4. Verify token is copied correctly
5. Check `docs/PHASE_2_TEST_CHECKLIST.md` for detailed troubleshooting

---

## Using Postman (Recommended)

### Import Collection

1. Open Postman
2. Create new collection "EzPrint APIs"
3. Add requests:

**Login:**
- Method: POST
- URL: `http://localhost:5000/api/auth/login`
- Body (JSON):
  ```json
  {
    "username": "YOUR_USERNAME",
    "password": "YOUR_PASSWORD"
  }
  ```

**Dashboard:**
- Method: GET
- URL: `http://localhost:5000/api/shop/{{shop_id}}/dashboard?period=today&limit=10`
- Headers:
  - `Authorization: Bearer {{token}}`

**Pricing:**
- Method: GET
- URL: `http://localhost:5000/api/shop/{{shop_id}}/pricing`
- Headers:
  - `Authorization: Bearer {{token}}`

### Set Variables

1. Create environment "Local"
2. Add variables:
   - `token` = (paste token from login response)
   - `shop_id` = (paste shop_id from login response)

---

## Next Steps

After quick testing:

1. **Full Testing:** See `docs/PHASE_2_TEST_CHECKLIST.md`
2. **Performance Testing:** Measure response times
3. **Security Testing:** Test authorization and token expiration
4. **Data Accuracy:** Compare API data with desktop data

---

**Happy Testing!** 🚀
