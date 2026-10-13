# eFarm Zehunger — MERN Stack Conversion Guide

> A complete, step-by-step guide for converting the BSF Farm Management System from Flask + PostgreSQL + Vanilla JS to MongoDB + Express.js + React + Node.js (MERN).

---

## Table of Contents

1. [Current vs Target Stack](#1-current-vs-target-stack)
2. [MERN Project Structure](#2-mern-project-structure)
3. [Dependencies](#3-dependencies)
4. [Database: PostgreSQL → MongoDB](#4-database-postgresql--mongodb)
5. [Backend: Flask → Express.js](#5-backend-flask--expressjs)
6. [Authentication: Flask-Login → JWT](#6-authentication-flask-login--jwt)
7. [API Route Mapping](#7-api-route-mapping)
8. [All Mongoose Models](#8-all-mongoose-models)
9. [All Express Route Files](#9-all-express-route-files)
10. [Frontend: Vanilla HTML/JS → React](#10-frontend-vanilla-htmljs--react)
11. [React Component Breakdown](#11-react-component-breakdown)
12. [Analytics: Migrating Chart.js](#12-analytics-migrating-chartjs)
13. [Export: Excel & PDF in React](#13-export-excel--pdf-in-react)
14. [Environment Variables](#14-environment-variables)
15. [Replit-Specific Setup](#15-replit-specific-setup)
16. [Conversion Checklist](#16-conversion-checklist)

---

## 1. Current vs Target Stack

| Layer | Current (Flask) | Target (MERN) |
|---|---|---|
| Language | Python 3.11 | JavaScript / Node.js 20 |
| Web framework | Flask 3.1.1 | Express.js 4.x |
| Database | PostgreSQL 16 (raw SQL via psycopg2) | MongoDB (Mongoose ODM) |
| Auth | Flask-Login + Flask-Session (SQLAlchemy, server-side) | JWT (jsonwebtoken) + bcrypt |
| Frontend framework | Vanilla HTML / CSS / JS (no build step) | React 18 (Vite) |
| Routing (frontend) | Server-side Flask routes returning HTML files | React Router v6 (SPA) |
| Forms | WTForms (server-side) + vanilla JS fetch | React Hook Form |
| Charts | Chart.js (CDN, vanilla JS) | react-chartjs-2 + Chart.js |
| Excel export | SheetJS (CDN) | xlsx (npm) |
| PDF export | jsPDF (CDN) | jspdf (npm) |
| WSGI server | Gunicorn | Node.js HTTP / PM2 |
| Session store | PostgreSQL (flask_sessions table) | Stateless JWT (no session store needed) |

---

## 2. MERN Project Structure

Replace the current `backend/` and `frontend/` layout with the following:

```
bsf-farm-mern/
├── server/                          # Express backend (replaces backend/)
│   ├── index.js                     # Entry point — starts Express server
│   ├── app.js                       # Express app setup, middleware registration
│   ├── config/
│   │   └── db.js                    # Mongoose connection (replaces database.py)
│   ├── middleware/
│   │   ├── auth.js                  # JWT verification middleware (replaces @login_required)
│   │   └── errorHandler.js          # Global error handler
│   ├── models/                      # Mongoose schemas (replace PostgreSQL tables)
│   │   ├── User.js
│   │   ├── WasteSourcing.js
│   │   ├── StorageRecord.js
│   │   ├── ProcessingRecord.js
│   │   ├── EnvMonitoringWaste.js
│   │   ├── EnvMonitoringLarvae.js
│   │   ├── SubstratePreparation.js
│   │   ├── HealthIntervention.js
│   │   ├── HarvestYield.js
│   │   ├── FeedingSchedule.js
│   │   ├── HatcheryBatch.js
│   │   ├── HatcheryFeeding.js
│   │   ├── HatcheryMonitoring.js
│   │   ├── HatcheryCleaning.js
│   │   ├── HatcheryProblem.js
│   │   ├── CageMonitoring.js
│   │   ├── FacilityMaintenance.js
│   │   ├── PupaeTransition.js
│   │   ├── EggCollection.js
│   │   ├── BaitPreparation.js
│   │   ├── DryingBatch.js
│   │   ├── DryingInput.js
│   │   ├── DryingOutput.js
│   │   ├── DryingQualityControl.js
│   │   ├── DryingReviewApproval.js
│   │   ├── Customer.js
│   │   ├── Sale.js
│   │   ├── Delivery.js
│   │   └── CustomerFeedback.js
│   └── routes/                      # Express routers (replace Flask blueprints + app.py routes)
│       ├── auth.js                  # /api/auth/*
│       ├── waste.js                 # /api/waste-*, /api/storage-*, etc.
│       ├── feeding.js               # /api/feeding/*, /api/substrate-*, etc.
│       ├── hatchery.js              # /api/hatchery/*
│       ├── facility.js              # /api/facility/*
│       ├── drying.js                # /api/drying/*
│       ├── sales.js                 # /api/sales/*, /api/customers/*, etc.
│       ├── analytics.js             # /api/analytics/*
│       ├── statistics.js            # /api/statistics/*
│       └── records.js               # /api/records (date+section query)
├── client/                          # React frontend (replaces frontend/)
│   ├── index.html                   # Vite entry point
│   ├── vite.config.js               # Vite config with proxy to Express
│   ├── src/
│   │   ├── main.jsx                 # React root mount
│   │   ├── App.jsx                  # React Router setup, route definitions
│   │   ├── api/
│   │   │   └── client.js            # Axios instance with JWT header injection
│   │   ├── context/
│   │   │   └── AuthContext.jsx      # Global auth state (replaces Flask-Login current_user)
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.jsx      # Navigation sidebar
│   │   │   │   ├── Navbar.jsx       # Top bar with user info and logout
│   │   │   │   └── ProtectedRoute.jsx # Redirect to /login if not authenticated
│   │   │   ├── common/
│   │   │   │   ├── Notification.jsx # Toast notifications (replaces notificationManager.js)
│   │   │   │   └── FormSection.jsx  # Reusable form wrapper
│   │   │   ├── waste/
│   │   │   │   ├── WasteSourcingForm.jsx
│   │   │   │   ├── StorageRecordForm.jsx
│   │   │   │   ├── ProcessingRecordForm.jsx
│   │   │   │   └── WasteEnvMonitoringForm.jsx
│   │   │   ├── feeding/
│   │   │   │   ├── SubstratePreparationForm.jsx
│   │   │   │   ├── FeedingScheduleForm.jsx
│   │   │   │   ├── HealthInterventionForm.jsx
│   │   │   │   ├── HarvestYieldForm.jsx
│   │   │   │   └── LarvaeEnvMonitoringForm.jsx
│   │   │   ├── hatchery/
│   │   │   │   ├── BatchInfoForm.jsx
│   │   │   │   ├── HatcheryFeedingForm.jsx
│   │   │   │   ├── HatcheryEnvMonitoringForm.jsx
│   │   │   │   ├── HatcheryCleaningForm.jsx
│   │   │   │   └── HatcheryProblemsForm.jsx
│   │   │   ├── facility/
│   │   │   │   ├── CageMonitoringForm.jsx
│   │   │   │   ├── FacilityMaintenanceForm.jsx
│   │   │   │   ├── PupaeTransitionForm.jsx
│   │   │   │   ├── EggCollectionForm.jsx
│   │   │   │   └── BaitPreparationForm.jsx
│   │   │   ├── drying/
│   │   │   │   ├── DryingBatchForm.jsx
│   │   │   │   ├── DryingInputForm.jsx
│   │   │   │   ├── DryingOutputForm.jsx
│   │   │   │   ├── DryingQCForm.jsx
│   │   │   │   └── DryingReviewForm.jsx
│   │   │   ├── sales/
│   │   │   │   ├── CustomerForm.jsx
│   │   │   │   ├── SalesForm.jsx
│   │   │   │   ├── DeliveryForm.jsx
│   │   │   │   └── FeedbackForm.jsx
│   │   │   └── analytics/
│   │   │       ├── WasteCharts.jsx
│   │   │       ├── HatcheryCharts.jsx
│   │   │       ├── FeedingCharts.jsx
│   │   │       ├── FacilityCharts.jsx
│   │   │       └── SalesCharts.jsx
│   │   └── pages/
│   │       ├── Landing.jsx          # Replaces frontend/main.html
│   │       ├── Login.jsx            # Replaces frontend/login.html
│   │       ├── Register.jsx         # Replaces frontend/register.html
│   │       ├── Dashboard.jsx        # Replaces frontend/index.html
│   │       └── Analytics.jsx        # Replaces frontend/analytics.html
└── package.json                     # Root scripts to run both server and client
```

---

## 3. Dependencies

### Server (`server/package.json`)

```json
{
  "name": "bsf-farm-server",
  "version": "1.0.0",
  "scripts": {
    "start": "node index.js",
    "dev": "nodemon index.js"
  },
  "dependencies": {
    "bcryptjs": "^2.4.3",
    "cors": "^2.8.5",
    "dotenv": "^16.4.5",
    "express": "^4.19.2",
    "jsonwebtoken": "^9.0.2",
    "mongoose": "^8.4.0",
    "express-validator": "^7.1.0"
  },
  "devDependencies": {
    "nodemon": "^3.1.4"
  }
}
```

### Client (`client/package.json`)

```json
{
  "name": "bsf-farm-client",
  "version": "1.0.0",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "axios": "^1.7.2",
    "chart.js": "^4.4.3",
    "jspdf": "^2.5.1",
    "jspdf-autotable": "^3.8.2",
    "react": "^18.3.1",
    "react-chartjs-2": "^5.2.0",
    "react-dom": "^18.3.1",
    "react-hook-form": "^7.52.1",
    "react-router-dom": "^6.24.0",
    "xlsx": "^0.18.5"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.3.1"
  }
}
```

### Root `package.json` (run both at once)

```json
{
  "name": "bsf-farm-mern",
  "version": "1.0.0",
  "scripts": {
    "dev": "concurrently \"npm run dev --prefix server\" \"npm run dev --prefix client\"",
    "install:all": "npm install && npm install --prefix server && npm install --prefix client"
  },
  "devDependencies": {
    "concurrently": "^8.2.2"
  }
}
```

---

## 4. Database: PostgreSQL → MongoDB

### Why the mapping works

The current app uses PostgreSQL with raw SQL (`psycopg2`). MongoDB's document model maps naturally to each table — one Mongoose model per PostgreSQL table. Relational joins (e.g. `sales JOIN customers`) become either embedded subdocuments or Mongoose `populate()` references.

### Schema mapping

| PostgreSQL table | Mongoose model | Notes |
|---|---|---|
| `users` | `User.js` | `user_id` → `_id` (auto) |
| `waste_sourcing` | `WasteSourcing.js` | Direct field mapping |
| `storage_records` | `StorageRecord.js` | Direct field mapping |
| `processing_records` | `ProcessingRecord.js` | Direct field mapping |
| `environmental_monitoring_waste` | `EnvMonitoringWaste.js` | Direct field mapping |
| `environmental_monitoring_larvaefeeding` | `EnvMonitoringLarvae.js` | Direct field mapping |
| `substrate_preparation` | `SubstratePreparation.js` | Direct field mapping |
| `health_intervention` | `HealthIntervention.js` | Direct field mapping |
| `harvest_yield` | `HarvestYield.js` | Direct field mapping |
| `feeding_schedule` | `FeedingSchedule.js` | Direct field mapping |
| `hatchery_batches` | `HatcheryBatch.js` | Direct field mapping |
| `hatchery_feeding` | `HatcheryFeeding.js` | Direct field mapping |
| `hatchery_monitoring` | `HatcheryMonitoring.js` | Direct field mapping |
| `hatchery_cleaning` | `HatcheryCleaning.js` | Direct field mapping |
| `hatchery_problems` | `HatcheryProblem.js` | Direct field mapping |
| `cage_monitoring` | `CageMonitoring.js` | Direct field mapping |
| `facility_maintenance` | `FacilityMaintenance.js` | Direct field mapping |
| `pupae_transition` | `PupaeTransition.js` | Direct field mapping |
| `egg_collection` | `EggCollection.js` | Direct field mapping |
| `bait_preparation` | `BaitPreparation.js` | Direct field mapping |
| `drying_batches` | `DryingBatch.js` | Direct field mapping |
| `drying_input` | `DryingInput.js` | Direct field mapping |
| `drying_output` | `DryingOutput.js` | Direct field mapping |
| `drying_quality_control` | `DryingQualityControl.js` | Direct field mapping |
| `drying_review_approval` | `DryingReviewApproval.js` | Direct field mapping |
| `customers` | `Customer.js` | Direct field mapping |
| `sales` | `Sale.js` | `customer_id INTEGER REFERENCES` → `customerId: ObjectId ref` |
| `deliveries` | `Delivery.js` | `customer_id` → `customerId: ObjectId ref` |
| `customer_feedback` | `CustomerFeedback.js` | `customer_id` → `customerId: ObjectId ref` |
| `flask_sessions` | *(eliminated)* | JWT is stateless; no session table needed |

---

## 5. Backend: Flask → Express.js

### `server/config/db.js` — Mongoose connection

```js
const mongoose = require('mongoose');

const connectDB = async () => {
  try {
    await mongoose.connect(process.env.MONGODB_URI);
    console.log('MongoDB connected');
  } catch (err) {
    console.error('MongoDB connection error:', err.message);
    process.exit(1);
  }
};

module.exports = connectDB;
```

---

### `server/app.js` — Express app setup

This replaces `backend/app.py`. All Flask app configuration becomes Express middleware.

```js
const express = require('express');
const cors = require('cors');
const path = require('path');

const authRoutes      = require('./routes/auth');
const wasteRoutes     = require('./routes/waste');
const feedingRoutes   = require('./routes/feeding');
const hatcheryRoutes  = require('./routes/hatchery');
const facilityRoutes  = require('./routes/facility');
const dryingRoutes    = require('./routes/drying');
const salesRoutes     = require('./routes/sales');
const analyticsRoutes = require('./routes/analytics');
const statisticsRoutes = require('./routes/statistics');
const recordsRoutes   = require('./routes/records');

const app = express();

// CORS — allow the React dev server (port 5173) to communicate with Express (port 5000)
app.use(cors({
  origin: process.env.CLIENT_URL || 'http://localhost:5173',
  credentials: true,
}));

app.use(express.json());

// API routes
app.use('/api/auth',       authRoutes);
app.use('/api',            wasteRoutes);
app.use('/api',            feedingRoutes);
app.use('/api/hatchery',   hatcheryRoutes);
app.use('/api/facility',   facilityRoutes);
app.use('/api/drying',     dryingRoutes);
app.use('/api',            salesRoutes);
app.use('/api/analytics',  analyticsRoutes);
app.use('/api/statistics', statisticsRoutes);
app.use('/api/records',    recordsRoutes);

// Serve React build in production
if (process.env.NODE_ENV === 'production') {
  app.use(express.static(path.join(__dirname, '../client/dist')));
  app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, '../client/dist/index.html'));
  });
}

module.exports = app;
```

---

### `server/index.js` — Entry point

```js
require('dotenv').config();
const app = require('./app');
const connectDB = require('./config/db');

const PORT = process.env.PORT || 5000;

connectDB().then(() => {
  app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
});
```

---

## 6. Authentication: Flask-Login → JWT

The current app uses Flask-Login with server-side sessions stored in PostgreSQL. MERN replaces this with **stateless JWT tokens**.

### Flow comparison

| Step | Flask | MERN |
|---|---|---|
| Login | Sets `bsf_session` cookie (PostgreSQL-backed) | Returns a signed JWT token |
| Auth check per request | `@login_required` decorator reads cookie → looks up session in DB | `auth.js` middleware verifies JWT signature |
| Current user | `current_user.username` (Flask-Login proxy) | `req.user` (set by middleware after decoding JWT) |
| Logout | Deletes server-side session from DB | Client discards JWT from storage |

---

### `server/middleware/auth.js` — JWT middleware (replaces `@login_required`)

```js
const jwt = require('jsonwebtoken');

module.exports = function (req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1]; // Bearer <token>

  if (!token) {
    return res.status(401).json({ success: false, message: 'No token, authorisation denied' });
  }

  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.user = decoded; // { id, username, email, role }
    next();
  } catch (err) {
    res.status(401).json({ success: false, message: 'Token is not valid' });
  }
};
```

---

### `server/models/User.js` — User model (replaces `users` table)

```js
const mongoose = require('mongoose');
const bcrypt = require('bcryptjs');

const userSchema = new mongoose.Schema({
  username:     { type: String, required: true, unique: true, trim: true },
  fullName:     { type: String, required: true },
  email:        { type: String, required: true, unique: true, lowercase: true },
  passwordHash: { type: String, required: true },
  role:         { type: String, enum: ['admin', 'farmer', 'viewer'], default: 'viewer' },
  isActive:     { type: Boolean, default: true },
  lastLogin:    { type: Date },
}, { timestamps: true }); // adds createdAt, updatedAt automatically

// Hash password before saving
userSchema.pre('save', async function (next) {
  if (!this.isModified('passwordHash')) return next();
  this.passwordHash = await bcrypt.hash(this.passwordHash, 12);
  next();
});

userSchema.methods.comparePassword = function (plainPassword) {
  return bcrypt.compare(plainPassword, this.passwordHash);
};

module.exports = mongoose.model('User', userSchema);
```

---

### `server/routes/auth.js` — Auth routes

```js
const express = require('express');
const jwt = require('jsonwebtoken');
const User = require('../models/User');
const auth = require('../middleware/auth');
const router = express.Router();

// POST /api/auth/register
router.post('/register', async (req, res) => {
  const { username, fullName, email, password } = req.body;

  if (!username || !fullName || !email || !password) {
    return res.status(400).json({ success: false, message: 'All fields are required' });
  }

  try {
    const existing = await User.findOne({ $or: [{ email }, { username }] });
    if (existing) {
      return res.status(409).json({ success: false, message: 'Email or username already registered' });
    }

    const user = new User({ username, fullName, email, passwordHash: password });
    await user.save();

    res.status(201).json({ success: true, message: 'Registration successful. Please log in.' });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error', error: err.message });
  }
});

// POST /api/auth/login
router.post('/login', async (req, res) => {
  const { email, password } = req.body;

  try {
    const user = await User.findOne({ email: email.toLowerCase().trim() });
    if (!user || !user.isActive) {
      return res.status(401).json({ success: false, message: 'Invalid email or password' });
    }

    const isMatch = await user.comparePassword(password);
    if (!isMatch) {
      return res.status(401).json({ success: false, message: 'Invalid email or password' });
    }

    user.lastLogin = new Date();
    await user.save();

    const token = jwt.sign(
      { id: user._id, username: user.username, email: user.email, role: user.role },
      process.env.JWT_SECRET,
      { expiresIn: '7d' }
    );

    res.json({ success: true, token, user: { username: user.username, email: user.email, role: user.role } });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error', error: err.message });
  }
});

// GET /api/auth/me — get current user (replaces load_user)
router.get('/me', auth, async (req, res) => {
  try {
    const user = await User.findById(req.user.id).select('-passwordHash');
    res.json({ success: true, user });
  } catch (err) {
    res.status(500).json({ success: false, message: 'Server error' });
  }
});

module.exports = router;
```

---

## 7. API Route Mapping

Every Flask route maps 1-to-1 to an Express route. The URL paths stay **exactly the same** so the frontend JavaScript only needs its import source changed, not the URLs.

### Auth

| Flask | Express |
|---|---|
| `POST /api/auth/login` | `POST /api/auth/login` |
| `POST /api/auth/register` | `POST /api/auth/register` |
| `GET /logout` | *(client-side — discard JWT)* |

### Waste Management

| Flask route | Express route file |
|---|---|
| `POST /api/waste-sourcing` | `routes/waste.js` |
| `GET /api/waste-sourcing` | `routes/waste.js` |
| `POST /api/storage-records` | `routes/waste.js` |
| `GET /api/storage-records` | `routes/waste.js` |
| `POST /api/processing-records` | `routes/waste.js` |
| `GET /api/processing-records` | `routes/waste.js` |
| `POST /api/environmental-monitoring-waste` | `routes/waste.js` |
| `GET /api/environmental-monitoring` | `routes/waste.js` |
| `POST /api/substrate-preparation` | `routes/waste.js` |

### Larval Feeding

| Flask route | Express route file |
|---|---|
| `POST /api/feeding/environmental-monitoring` | `routes/feeding.js` |
| `POST /api/feeding/health-intervention` | `routes/feeding.js` |
| `POST /api/feeding/harvest-yield` | `routes/feeding.js` |
| `POST /api/feeding/schedule` | `routes/feeding.js` |
| `POST /api/health-intervention` (legacy) | `routes/feeding.js` |
| `POST /api/harvest-yield` (legacy) | `routes/feeding.js` |
| `POST /api/larvae-feeding` | `routes/feeding.js` |

### Hatchery

| Flask route | Express route file |
|---|---|
| `POST /api/hatchery/batch-information` | `routes/hatchery.js` |
| `POST /api/hatchery/batch` | `routes/hatchery.js` |
| `POST /api/hatchery/feeding-records` | `routes/hatchery.js` |
| `POST /api/hatchery/feeding` | `routes/hatchery.js` |
| `POST /api/hatchery/environmental-monitoring` | `routes/hatchery.js` |
| `POST /api/hatchery/monitoring` | `routes/hatchery.js` |
| `POST /api/hatchery/cleaning` | `routes/hatchery.js` |
| `POST /api/hatchery/problems` | `routes/hatchery.js` |

### Fly Facility

| Flask route | Express route file |
|---|---|
| `POST /api/fly-facility/cage-monitoring` | `routes/facility.js` |
| `POST /api/facility/cage-monitoring` | `routes/facility.js` |
| `POST /api/fly-facility/maintenance` | `routes/facility.js` |
| `POST /api/facility/maintenance` | `routes/facility.js` |
| `POST /api/fly-facility/pupae-transition` | `routes/facility.js` |
| `POST /api/facility/pupae-transition` | `routes/facility.js` |
| `POST /api/fly-facility/egg-collection` | `routes/facility.js` |
| `POST /api/facility/egg-collection` | `routes/facility.js` |
| `POST /api/fly-facility/bait-preparation` | `routes/facility.js` |
| `POST /api/facility/bait-preparation` | `routes/facility.js` |

### Drying

| Flask route | Express route file |
|---|---|
| `POST/GET /api/drying/batches` | `routes/drying.js` |
| `POST/GET /api/drying/input` | `routes/drying.js` |
| `POST/GET /api/drying/output` | `routes/drying.js` |
| `POST/GET /api/drying/quality-control` | `routes/drying.js` |
| `POST/GET /api/drying/review-approval` | `routes/drying.js` |

### Analytics

| Flask route | Express route file |
|---|---|
| `GET /api/analytics/waste-sourcing` | `routes/analytics.js` |
| `GET /api/analytics/storage-records` | `routes/analytics.js` |
| `GET /api/analytics/processing-records` | `routes/analytics.js` |
| `GET /api/analytics/waste-env-monitoring` | `routes/analytics.js` |
| `GET /api/analytics/hatchery-batches` | `routes/analytics.js` |
| `GET /api/analytics/hatchery-feeding` | `routes/analytics.js` |
| `GET /api/analytics/hatchery-monitoring` | `routes/analytics.js` |
| `GET /api/analytics/larvae-env-monitoring` | `routes/analytics.js` |
| `GET /api/analytics/substrate-preparation` | `routes/analytics.js` |
| `GET /api/analytics/health-intervention` | `routes/analytics.js` |
| `GET /api/analytics/harvest-yield` | `routes/analytics.js` |
| `GET /api/analytics/feeding-schedule` | `routes/analytics.js` |
| `GET /api/analytics/cage-monitoring` | `routes/analytics.js` |
| `GET /api/analytics/facility-maintenance` | `routes/analytics.js` |
| `GET /api/analytics/pupae-transition` | `routes/analytics.js` |
| `GET /api/analytics/egg-collection` | `routes/analytics.js` |
| `GET /api/analytics/bait-preparation` | `routes/analytics.js` |
| `GET /api/analytics/drying-batches` | `routes/analytics.js` |
| `GET /api/analytics/customers` | `routes/analytics.js` |
| `GET /api/analytics/sales` | `routes/analytics.js` |
| `GET /api/analytics/deliveries` | `routes/analytics.js` |
| `GET /api/analytics/feedback` | `routes/analytics.js` |

### Statistics

| Flask route | Express route file |
|---|---|
| `GET /api/statistics/waste-processing` | `routes/statistics.js` |
| `GET /api/statistics/environmental` | `routes/statistics.js` |
| `GET /api/statistics/larval-growth` | `routes/statistics.js` |
| `GET /api/statistics/system-efficiency` | `routes/statistics.js` |
| `GET /api/statistics/daily-report` | `routes/statistics.js` |
| `GET /api/statistics/harvest-efficiency` | `routes/statistics.js` |

### Records (Date + Section lookup)

| Flask route | Express route file |
|---|---|
| `GET /api/records?date=&section=` | `routes/records.js` |

---

## 8. All Mongoose Models

### Pattern

Every model below follows the same pattern. Field names change from `snake_case` (Python convention) to `camelCase` (JS convention), though you can keep snake_case if preferred for API compatibility.

---

### `server/models/WasteSourcing.js`

```js
const mongoose = require('mongoose');

const schema = new mongoose.Schema({
  collectionDate:      { type: Date, required: true },
  collectionTime:      { type: String, required: true },
  sourceType:          { type: String, required: true },
  sourceName:          { type: String, required: true },
  wasteType:           { type: String, required: true },
  wasteWeight:         { type: Number, required: true },
  segregationStatus:   { type: String, required: true },
  contaminantsFound:   { type: String },
  collectionNotes:     { type: String },
  collectionPersonnel: { type: String, required: true },
  recordedBy:          { type: String },
}, { timestamps: true });

schema.index({ collectionDate: -1 });
module.exports = mongoose.model('WasteSourcing', schema);
```

### `server/models/StorageRecord.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  storageDate:          { type: Date, required: true },
  storageMethod:        { type: String, required: true },
  storageConditions:    { type: String, required: true },
  storageDuration:      { type: Number, required: true },
  plannedUtilization:   { type: String, required: true },
  storageObservations:  { type: String },
  recordedBy:           { type: String },
}, { timestamps: true });
schema.index({ storageDate: -1 });
module.exports = mongoose.model('StorageRecord', schema);
```

### `server/models/ProcessingRecord.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  processingDate:   { type: Date, required: true },
  processingType:   { type: String, required: true },
  processingMethod: { type: String, required: true },
  wasteProcessed:   { type: Number, required: true },
  byProducts:       { type: String },
  wasteReduction:   { type: Number },
  processingRemarks:{ type: String },
  recordedBy:       { type: String },
}, { timestamps: true });
schema.index({ processingDate: -1 });
module.exports = mongoose.model('ProcessingRecord', schema);
```

### `server/models/EnvMonitoringWaste.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  monitoringDate:     { type: Date, required: true },
  monitoringTime:     { type: String, required: true },
  temperature:        { type: Number, required: true },
  humidity:           { type: Number, required: true },
  odorLevel:          { type: String, required: true },
  pestPresence:       { type: String, required: true },
  pestDetails:        { type: String },
  mitigationActions:  { type: String },
  remarks:            { type: String },
  recordedBy:         { type: String },
}, { timestamps: true });
schema.index({ monitoringDate: -1 });
module.exports = mongoose.model('EnvMonitoringWaste', schema);
```

### `server/models/EnvMonitoringLarvae.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  monitoringDate: { type: Date, required: true },
  monitoringTime: { type: String, required: true },
  trayFacilityId: { type: String, required: true },
  temperature:    { type: Number, required: true },
  humidity:       { type: Number, required: true },
  ammoniaOdor:    { type: String, required: true },
  notes:          { type: String },
  recordedBy:     { type: String },
}, { timestamps: true });
module.exports = mongoose.model('EnvMonitoringLarvae', schema);
```

### `server/models/SubstratePreparation.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  batchNo:           { type: String, required: true },
  prepDate:          { type: Date, required: true },
  organicWasteSource:{ type: String, required: true },
  moisturePercentage:{ type: Number, required: true },
  wasteParticleSize: { type: String, required: true },
  foreignMatter:     { type: String, required: true },
  handlerOperator:   { type: String, required: true },
  notes:             { type: String },
}, { timestamps: true });
module.exports = mongoose.model('SubstratePreparation', schema);
```

### `server/models/HealthIntervention.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  healthDate:    { type: Date, required: true },
  trayBatchId:   { type: String, required: true },
  observedIssue: { type: String, required: true },
  severity:      { type: String, required: true },
  actionTaken:   { type: String, required: true },
  followUpDate:  { type: Date },
  resolved:      { type: String },
  comments:      { type: String },
  recordedBy:    { type: String },
}, { timestamps: true });
module.exports = mongoose.model('HealthIntervention', schema);
```

### `server/models/HarvestYield.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  harvestDate:      { type: Date, required: true },
  trayBatchId:      { type: String, required: true },
  instarStage:      { type: String, required: true },
  larvaeCollected:  { type: Number, required: true },
  processingMethod: { type: String, required: true },
  storageTemp:      { type: Number },
  notes:            { type: String },
  recordedBy:       { type: String },
}, { timestamps: true });
module.exports = mongoose.model('HarvestYield', schema);
```

### `server/models/FeedingSchedule.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  feedingDate:  { type: Date, required: true },
  trayBatchId:  { type: String, required: true },
  larvaeAgeDays:{ type: Number, required: true },
  larvaeWeight: { type: Number, required: true },
  feedType:     { type: String, required: true },
  feedQuantity: { type: Number, required: true },
  startWeight:  { type: Number },
  endWeight:    { type: Number },
  consumption:  { type: Number },
  operator:     { type: String, required: true },
  recordedBy:   { type: String },
}, { timestamps: true });
module.exports = mongoose.model('FeedingSchedule', schema);
```

### `server/models/HatcheryBatch.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  batchNumber:       { type: String, required: true },
  batchDate:         { type: Date, required: true },
  eggIncubationDate: { type: Date, required: true },
  totalEggsGrams:    { type: Number, required: true },
  expectedHatchDate: { type: Date, required: true },
  actualHatchDate:   { type: Date },
  hatchDays:         { type: Number },
  supervisorName:    { type: String, required: true },
  notes:             { type: String },
}, { timestamps: true });
module.exports = mongoose.model('HatcheryBatch', schema);
```

### `server/models/Customer.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  name:    { type: String, required: true },
  contact: { type: String },
  email:   { type: String },
  address: { type: String },
}, { timestamps: true });
module.exports = mongoose.model('Customer', schema);
```

### `server/models/Sale.js`

```js
const mongoose = require('mongoose');
const schema = new mongoose.Schema({
  date:       { type: Date, required: true },
  customerId: { type: mongoose.Schema.Types.ObjectId, ref: 'Customer', required: true },
  product:    { type: String, required: true },
  quantity:   { type: Number, required: true },
  amount:     { type: Number, required: true },
}, { timestamps: true });
module.exports = mongoose.model('Sale', schema);
```

> **Note:** Define all remaining models (`CageMonitoring`, `FacilityMaintenance`, `PupaeTransition`, `EggCollection`, `BaitPreparation`, `DryingBatch`, `DryingInput`, `DryingOutput`, `DryingQualityControl`, `DryingReviewApproval`, `Delivery`, `CustomerFeedback`) following the same pattern, using the PostgreSQL table definitions in `backend/init_db.py` as the source of truth for every field name and type.

---

## 9. All Express Route Files

### Pattern for every route

```js
const express = require('express');
const router = express.Router();
const auth = require('../middleware/auth');
const Model = require('../models/ModelName');

// POST — create record
router.post('/endpoint', auth, async (req, res) => {
  try {
    const record = new Model({ ...req.body, recordedBy: req.user.username });
    await record.save();
    res.status(201).json({ success: true, message: 'Record saved successfully' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

// GET — fetch all records
router.get('/endpoint', auth, async (req, res) => {
  try {
    const records = await Model.find().sort({ createdAt: -1 });
    res.json({ success: true, records });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

module.exports = router;
```

---

### `server/routes/waste.js` — full example

```js
const express = require('express');
const router = express.Router();
const auth = require('../middleware/auth');
const WasteSourcing   = require('../models/WasteSourcing');
const StorageRecord   = require('../models/StorageRecord');
const ProcessingRecord = require('../models/ProcessingRecord');
const EnvMonitoringWaste = require('../models/EnvMonitoringWaste');
const SubstratePreparation = require('../models/SubstratePreparation');

router.post('/waste-sourcing', auth, async (req, res) => {
  try {
    const record = new WasteSourcing({ ...req.body, recordedBy: req.user.username });
    await record.save();
    res.status(201).json({ success: true, message: 'Waste sourcing data recorded successfully' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

router.get('/waste-sourcing', auth, async (req, res) => {
  try {
    const records = await WasteSourcing.find().sort({ collectionDate: -1 });
    res.json(records);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.post('/storage-records', auth, async (req, res) => {
  try {
    const record = new StorageRecord({ ...req.body, recordedBy: req.user.username });
    await record.save();
    res.status(201).json({ success: true, message: 'Storage record saved successfully' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

router.get('/storage-records', auth, async (req, res) => {
  try {
    const records = await StorageRecord.find().sort({ storageDate: -1 });
    res.json(records);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.post('/processing-records', auth, async (req, res) => {
  try {
    const record = new ProcessingRecord({ ...req.body, recordedBy: req.user.username });
    await record.save();
    res.status(201).json({ success: true, message: 'Processing record saved successfully' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

router.post('/environmental-monitoring-waste', auth, async (req, res) => {
  try {
    const record = new EnvMonitoringWaste({ ...req.body, recordedBy: req.user.username });
    await record.save();
    res.status(201).json({ success: true, message: 'Environmental monitoring record saved successfully' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

router.post('/substrate-preparation', auth, async (req, res) => {
  try {
    const record = new SubstratePreparation(req.body);
    await record.save();
    res.status(201).json({ success: true, message: 'Substrate preparation record saved successfully' });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

module.exports = router;
```

---

### `server/routes/analytics.js` — analytics GET endpoints

```js
const express = require('express');
const router = express.Router();
const auth = require('../middleware/auth');

// Import all models
const WasteSourcing      = require('../models/WasteSourcing');
const StorageRecord      = require('../models/StorageRecord');
const ProcessingRecord   = require('../models/ProcessingRecord');
const EnvMonitoringWaste = require('../models/EnvMonitoringWaste');
const HatcheryBatch      = require('../models/HatcheryBatch');
const HarvestYield       = require('../models/HarvestYield');
const FeedingSchedule    = require('../models/FeedingSchedule');
const CageMonitoring     = require('../models/CageMonitoring');
const Customer           = require('../models/Customer');
const Sale               = require('../models/Sale');
const Delivery           = require('../models/Delivery');
const CustomerFeedback   = require('../models/CustomerFeedback');

const makeAnalyticsRoute = (Model, sortField) => async (req, res) => {
  try {
    const records = await Model.find().sort({ [sortField]: -1 });
    res.json({ records, success: true });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
};

router.get('/waste-sourcing',       auth, makeAnalyticsRoute(WasteSourcing, 'collectionDate'));
router.get('/storage-records',      auth, makeAnalyticsRoute(StorageRecord, 'storageDate'));
router.get('/processing-records',   auth, makeAnalyticsRoute(ProcessingRecord, 'processingDate'));
router.get('/waste-env-monitoring', auth, makeAnalyticsRoute(EnvMonitoringWaste, 'monitoringDate'));
router.get('/hatchery-batches',     auth, makeAnalyticsRoute(HatcheryBatch, 'batchDate'));
router.get('/harvest-yield',        auth, makeAnalyticsRoute(HarvestYield, 'harvestDate'));
router.get('/feeding-schedule',     auth, makeAnalyticsRoute(FeedingSchedule, 'feedingDate'));
router.get('/cage-monitoring',      auth, makeAnalyticsRoute(CageMonitoring, 'monitoringDate'));
router.get('/customers',            auth, makeAnalyticsRoute(Customer, 'name'));

router.get('/sales', auth, async (req, res) => {
  try {
    const records = await Sale.find().populate('customerId', 'name').sort({ date: -1 });
    res.json({ records, success: true });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

router.get('/deliveries', auth, async (req, res) => {
  try {
    const records = await Delivery.find().populate('customerId', 'name').sort({ date: -1 });
    res.json({ records, success: true });
  } catch (err) {
    res.status(500).json({ success: false, message: err.message });
  }
});

module.exports = router;
```

---

### `server/routes/statistics.js` — statistics aggregations

MongoDB aggregation pipelines replace the PostgreSQL `GROUP BY` queries in `app.py`.

```js
const express = require('express');
const router = express.Router();
const auth = require('../middleware/auth');
const ProcessingRecord = require('../models/ProcessingRecord');
const EnvMonitoringWaste = require('../models/EnvMonitoringWaste');
const FeedingSchedule = require('../models/FeedingSchedule');
const WasteSourcing = require('../models/WasteSourcing');
const HarvestYield = require('../models/HarvestYield');

// GET /api/statistics/waste-processing  (replaces Flask GROUP BY query)
router.get('/waste-processing', auth, async (req, res) => {
  try {
    const stats = await ProcessingRecord.aggregate([
      { $group: {
          _id: { $dateToString: { format: '%Y-%m-%d', date: '$processingDate' } },
          totalProcessed: { $sum: '$wasteProcessed' }
      }},
      { $sort: { _id: -1 } },
      { $limit: 30 },
      { $project: { date: '$_id', totalProcessed: 1, _id: 0 } }
    ]);
    res.json(stats);
  } catch (err) {
    res.status(500).json([]);
  }
});

// GET /api/statistics/environmental
router.get('/environmental', auth, async (req, res) => {
  try {
    const stats = await EnvMonitoringWaste.aggregate([
      { $group: {
          _id: { $dateToString: { format: '%Y-%m-%d', date: '$monitoringDate' } },
          avgTemp: { $avg: '$temperature' },
          avgHumidity: { $avg: '$humidity' }
      }},
      { $sort: { _id: -1 } },
      { $limit: 30 },
      { $project: { date: '$_id', avgTemp: 1, avgHumidity: 1, _id: 0 } }
    ]);
    res.json(stats);
  } catch (err) {
    res.status(500).json([]);
  }
});

// GET /api/statistics/system-efficiency
router.get('/system-efficiency', auth, async (req, res) => {
  try {
    const [wasteResult] = await WasteSourcing.aggregate([{ $group: { _id: null, total: { $sum: '$wasteWeight' } } }]);
    const [larvaeResult] = await HarvestYield.aggregate([{ $group: { _id: null, total: { $sum: '$larvaeCollected' } } }]);
    const processingCount = await require('../models/ProcessingRecord').countDocuments();

    const totalWasteIn   = wasteResult?.total || 0;
    const totalLarvaeOut = larvaeResult?.total || 0;

    res.json({
      totalWasteIn,
      totalLarvaeOut,
      totalProcessingRecords: processingCount,
      overallEfficiency: totalWasteIn > 0 ? totalLarvaeOut / totalWasteIn : 0
    });
  } catch (err) {
    res.status(500).json({});
  }
});

// GET /api/statistics/daily-report
router.get('/daily-report', auth, async (req, res) => {
  try {
    const today = new Date();
    const startOfDay = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const endOfDay   = new Date(startOfDay.getTime() + 86400000);

    const dateFilter = { $gte: startOfDay, $lt: endOfDay };

    const [waste] = await WasteSourcing.aggregate([
      { $match: { collectionDate: dateFilter } },
      { $group: { _id: null, total: { $sum: '$wasteWeight' } } }
    ]);
    const [larvae] = await HarvestYield.aggregate([
      { $match: { harvestDate: dateFilter } },
      { $group: { _id: null, total: { $sum: '$larvaeCollected' } } }
    ]);
    const [feed] = await FeedingSchedule.aggregate([
      { $match: { feedingDate: dateFilter } },
      { $group: { _id: null, total: { $sum: '$feedQuantity' } } }
    ]);
    const [eggs] = await require('../models/EggCollection').aggregate([
      { $match: { collectionDate: dateFilter } },
      { $group: { _id: null, total: { $sum: '$eggsCollected' } } }
    ]);

    res.json({
      wasteSourcedToday:    waste?.total || 0,
      larvaeHarvestedToday: larvae?.total || 0,
      feedGivenToday:       feed?.total || 0,
      eggsCollectedToday:   eggs?.total || 0,
    });
  } catch (err) {
    res.status(500).json({});
  }
});

module.exports = router;
```

---

## 10. Frontend: Vanilla HTML/JS → React

### Key translation table

| Current (Vanilla JS) | React equivalent |
|---|---|
| `document.getElementById('form')` | `useRef()` or controlled inputs |
| `fetch('/api/...')` with `credentials: 'include'` | `axios` with `Authorization: Bearer <token>` header |
| `window.location.href = '/dashboard'` | `useNavigate()` from React Router |
| `flask_login.current_user` server-side | `useContext(AuthContext)` client-side |
| `render_template('login.html', form=form)` | `<Login />` React page component |
| `notificationManager.js` toast | `<Notification />` component with state |
| `analyticsManager.js` Chart.js code | `react-chartjs-2` chart components |
| `exportManager.js` (xlsx, jsPDF) | Same libraries imported as npm packages |
| `dataManager.js` localStorage | Same logic in a React custom hook |

---

### `client/vite.config.js` — proxy API calls to Express

```js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
});
```

---

### `client/src/api/client.js` — Axios instance with JWT

This replaces all `fetch('/api/...', { credentials: 'include' })` calls.

```js
import axios from 'axios';

const client = axios.create({ baseURL: '/api' });

// Attach JWT token to every request automatically
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('bsf_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Redirect to login on 401
client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('bsf_token');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export default client;
```

---

### `client/src/context/AuthContext.jsx` — global auth state

Replaces Flask-Login's `current_user`.

```jsx
import { createContext, useContext, useState, useEffect } from 'react';
import client from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('bsf_token');
    if (token) {
      client.get('/auth/me')
        .then(res => setUser(res.data.user))
        .catch(() => localStorage.removeItem('bsf_token'))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (email, password) => {
    const res = await client.post('/auth/login', { email, password });
    localStorage.setItem('bsf_token', res.data.token);
    setUser(res.data.user);
  };

  const logout = () => {
    localStorage.removeItem('bsf_token');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

---

### `client/src/App.jsx` — React Router setup

Replaces Flask's page routes (`/`, `/login`, `/register`, `/dashboard`, `/analytics`).

```jsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Landing   from './pages/Landing';
import Login     from './pages/Login';
import Register  from './pages/Register';
import Dashboard from './pages/Dashboard';
import Analytics from './pages/Analytics';

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div>Loading...</div>;
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/"          element={<Landing />} />
          <Route path="/login"     element={<Login />} />
          <Route path="/register"  element={<Register />} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/analytics" element={<ProtectedRoute><Analytics /></ProtectedRoute>} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
```

---

### `client/src/pages/Login.jsx` — login page

```jsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await login(email, password);
      navigate('/dashboard');
    } catch (err) {
      setError(err.response?.data?.message || 'Login failed');
    }
  };

  return (
    <div className="auth-container">
      <h2>BSF Farm Login</h2>
      {error && <div className="alert alert-danger">{error}</div>}
      <form onSubmit={handleSubmit}>
        <input type="email"    placeholder="Email"    value={email}    onChange={e => setEmail(e.target.value)}    required />
        <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required />
        <button type="submit">Login</button>
      </form>
    </div>
  );
}
```

---

### Example form component: `client/src/components/waste/WasteSourcingForm.jsx`

Each of the 25+ form pages in `frontend/index.html` becomes its own React component using React Hook Form.

```jsx
import { useForm } from 'react-hook-form';
import client from '../../api/client';

export default function WasteSourcingForm({ onSuccess }) {
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm();

  const onSubmit = async (data) => {
    try {
      await client.post('/waste-sourcing', data);
      onSuccess('Waste sourcing data recorded successfully');
      reset();
    } catch (err) {
      onSuccess(err.response?.data?.message || 'Submission failed', 'error');
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <div className="mb-3">
        <label>Collection Date</label>
        <input type="date" {...register('collectionDate', { required: true })} className="form-control" />
        {errors.collectionDate && <span className="text-danger">Required</span>}
      </div>

      <div className="mb-3">
        <label>Source Type</label>
        <select {...register('sourceType', { required: true })} className="form-select">
          <option value="">Select...</option>
          <option value="restaurant">Restaurant</option>
          <option value="market">Market</option>
          <option value="household">Household</option>
        </select>
      </div>

      <div className="mb-3">
        <label>Waste Weight (kg)</label>
        <input type="number" step="0.01" {...register('wasteWeight', { required: true, min: 0.01 })} className="form-control" />
      </div>

      {/* Add all other fields from frontend/index.html wasteSourcingForm */}

      <button type="submit" disabled={isSubmitting} className="btn btn-success">
        {isSubmitting ? 'Saving...' : 'Save Record'}
      </button>
    </form>
  );
}
```

> **Important:** Open `frontend/index.html` and copy every `<input>`, `<select>`, and `<textarea>` field name from each form section. Register each one with `register('fieldName')` in the corresponding React component. The field names must match what the Express route handler expects.

---

## 11. React Component Breakdown

### Dashboard page structure

`frontend/index.html` is one massive HTML file with all sections in `<div class="section">` containers, toggled by `showSection()` in JavaScript. In React, this becomes a single `Dashboard.jsx` page with state controlling which section is visible:

```jsx
import { useState } from 'react';
import Sidebar from '../components/layout/Sidebar';
import WasteSourcingForm from '../components/waste/WasteSourcingForm';
import StorageRecordForm from '../components/waste/StorageRecordForm';
// ... import all other form components

const SECTIONS = {
  'waste-sourcing':          <WasteSourcingForm />,
  'storage-records':         <StorageRecordForm />,
  'processing-records':      <ProcessingRecordForm />,
  // ... all other sections
};

export default function Dashboard() {
  const [activeSection, setActiveSection] = useState('waste-sourcing');
  const [notification, setNotification] = useState(null);

  return (
    <div className="dashboard-layout">
      <Sidebar onSelect={setActiveSection} activeSection={activeSection} />
      <main>
        {notification && <div className={`alert alert-${notification.type}`}>{notification.message}</div>}
        {SECTIONS[activeSection]
          ? React.cloneElement(SECTIONS[activeSection], {
              onSuccess: (msg, type = 'success') => setNotification({ message: msg, type })
            })
          : <p>Select a section from the sidebar.</p>
        }
      </main>
    </div>
  );
}
```

---

## 12. Analytics: Migrating Chart.js

The current `analyticsManager.js` uses Chart.js directly with canvas elements. In React, use `react-chartjs-2`.

### Current pattern (vanilla JS)
```js
new Chart(ctx, { type: 'bar', data: { ... }, options: { ... } });
```

### MERN pattern (React)
```jsx
import { Bar, Line, Pie, Doughnut } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, LineElement,
         PointElement, ArcElement, Title, Tooltip, Legend } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement,
                 PointElement, ArcElement, Title, Tooltip, Legend);

export default function WasteCharts({ records }) {
  const wasteByType = records.reduce((acc, r) => {
    acc[r.wasteType] = (acc[r.wasteType] || 0) + 1;
    return acc;
  }, {});

  const data = {
    labels: Object.keys(wasteByType),
    datasets: [{
      label: 'Waste by Type',
      data: Object.values(wasteByType),
      backgroundColor: ['#3498db', '#2ecc71', '#e74c3c', '#f39c12'],
    }],
  };

  return <Bar data={data} />;
}
```

---

## 13. Export: Excel & PDF in React

The current `exportManager.js` uses SheetJS and jsPDF loaded from CDN. In React, import them as npm packages.

### Excel export (xlsx)
```jsx
import * as XLSX from 'xlsx';

function exportToExcel(data, filename = 'export') {
  const ws = XLSX.utils.json_to_sheet(data);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
  XLSX.writeFile(wb, `${filename}.xlsx`);
}
```

### PDF export (jsPDF + autotable)
```jsx
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';

function exportToPDF(columns, rows, filename = 'export') {
  const doc = new jsPDF();
  autoTable(doc, { head: [columns], body: rows });
  doc.save(`${filename}.pdf`);
}
```

---

## 14. Environment Variables

### Server `.env` (replaces Replit PostgreSQL env vars)

```env
PORT=5000
MONGODB_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/bsf_farm?retryWrites=true&w=majority
JWT_SECRET=replace-with-a-long-random-secret
NODE_ENV=development
CLIENT_URL=http://localhost:5173
```

### Client `.env` (Vite)

```env
VITE_API_BASE_URL=/api
```

> In Replit, set `MONGODB_URI` and `JWT_SECRET` as Replit Secrets. Use MongoDB Atlas (free tier) for the cloud database since Replit does not provide native MongoDB hosting.

---

## 15. Replit-Specific Setup

### MongoDB on Replit

Replit does not include a managed MongoDB service. You have two options:

**Option A — MongoDB Atlas (recommended)**
1. Create a free cluster at [cloud.mongodb.com](https://cloud.mongodb.com)
2. Get the connection string: `mongodb+srv://user:pass@cluster.mongodb.net/bsf_farm`
3. Add it as a Replit Secret named `MONGODB_URI`

**Option B — Replit integrations**
Check whether a MongoDB connector is available in Replit Integrations (the integrations panel in your Repl). If listed, use it to auto-provision credentials.

---

### Replit `.replit` workflow configuration

```toml
modules = ["web", "nodejs-20"]

[nix]
channel = "stable-25_05"

[[workflows.workflow]]
name = "MERN Dev"
author = "agent"
mode = "parallel"

[workflows.workflow.metadata]
outputType = "webview"

[[workflows.workflow.tasks]]
task = "shell.exec"
args = "npm run install:all && npm run dev"
waitForPort = 5173

[[ports]]
localPort = 5173
externalPort = 80
```

### Deployment (publish) command

```bash
# Build React, then serve everything from Express on port 5000
npm run build --prefix client && node server/index.js
```

In production, Express serves the React build from `client/dist/`. Set `NODE_ENV=production` and point the deployment run command to `node server/index.js`.

---

## 16. Conversion Checklist

Use this to track progress when working with the converting model:

### Phase 1 — Project scaffolding
- [ ] Create `server/` and `client/` directories
- [ ] Initialise `server/package.json` and install Express dependencies
- [ ] Scaffold React app in `client/` using Vite: `npm create vite@latest client -- --template react`
- [ ] Install client dependencies
- [ ] Create root `package.json` with concurrently dev script
- [ ] Configure `vite.config.js` with `/api` proxy to port 5000

### Phase 2 — Database & server core
- [ ] Create `server/config/db.js` (Mongoose connection)
- [ ] Create `server/index.js` entry point
- [ ] Create `server/app.js` with middleware
- [ ] Create `server/middleware/auth.js` JWT middleware
- [ ] Add `MONGODB_URI` and `JWT_SECRET` to Replit Secrets
- [ ] Set up MongoDB Atlas cluster and whitelist `0.0.0.0/0` for Replit IPs

### Phase 3 — Mongoose models (one per PostgreSQL table)
- [ ] `User.js`
- [ ] `WasteSourcing.js`
- [ ] `StorageRecord.js`
- [ ] `ProcessingRecord.js`
- [ ] `EnvMonitoringWaste.js`
- [ ] `EnvMonitoringLarvae.js`
- [ ] `SubstratePreparation.js`
- [ ] `HealthIntervention.js`
- [ ] `HarvestYield.js`
- [ ] `FeedingSchedule.js`
- [ ] `HatcheryBatch.js`
- [ ] `HatcheryFeeding.js`
- [ ] `HatcheryMonitoring.js`
- [ ] `HatcheryCleaning.js`
- [ ] `HatcheryProblem.js`
- [ ] `CageMonitoring.js`
- [ ] `FacilityMaintenance.js`
- [ ] `PupaeTransition.js`
- [ ] `EggCollection.js`
- [ ] `BaitPreparation.js`
- [ ] `DryingBatch.js`
- [ ] `DryingInput.js`
- [ ] `DryingOutput.js`
- [ ] `DryingQualityControl.js`
- [ ] `DryingReviewApproval.js`
- [ ] `Customer.js`
- [ ] `Sale.js` (with ObjectId ref to Customer)
- [ ] `Delivery.js` (with ObjectId ref to Customer)
- [ ] `CustomerFeedback.js` (with ObjectId ref to Customer)

### Phase 4 — Express routes
- [ ] `routes/auth.js` (register, login, /me)
- [ ] `routes/waste.js`
- [ ] `routes/feeding.js`
- [ ] `routes/hatchery.js`
- [ ] `routes/facility.js`
- [ ] `routes/drying.js`
- [ ] `routes/sales.js`
- [ ] `routes/analytics.js`
- [ ] `routes/statistics.js` (MongoDB aggregation pipelines)
- [ ] `routes/records.js` (date + section filter)

### Phase 5 — React frontend
- [ ] `AuthContext.jsx` with login/logout/user state
- [ ] `client.js` Axios instance with JWT interceptor
- [ ] `App.jsx` with React Router routes
- [ ] `pages/Landing.jsx` (portal selector)
- [ ] `pages/Login.jsx`
- [ ] `pages/Register.jsx`
- [ ] `pages/Dashboard.jsx` (section switcher)
- [ ] `pages/Analytics.jsx`
- [ ] `components/layout/Sidebar.jsx`
- [ ] `components/layout/Navbar.jsx`
- [ ] `components/common/Notification.jsx`
- [ ] All 25+ form components (one per form section in `index.html`)
- [ ] All chart components in `components/analytics/`

### Phase 6 — Validation
- [ ] All API routes return correct HTTP status codes (201 for create, 401 for auth, 400 for validation)
- [ ] JWT token persists across page refreshes
- [ ] Analytics charts load real data from MongoDB
- [ ] Excel and PDF export work for all analytics sections
- [ ] `/api/records?date=&section=` date-range query works with MongoDB date filters
- [ ] `populate()` on sales/deliveries/feedback joins customer names correctly

---

## Important Notes for the Converting Model

1. **Field name casing**: The Flask backend uses `snake_case` keys (from `normalize_keys()`). Express receives JSON directly — use `camelCase` in Mongoose models and React forms to follow JS convention, but make sure both sides agree. The easiest approach is to keep using `camelCase` throughout since Express/Mongoose natively use it.

2. **The `normalize_keys()` function**: Flask had a utility that converted incoming `camelCase` JSON keys to `snake_case` for the database. In MERN you do not need this — Mongoose models use camelCase natively and there is no conversion needed.

3. **Date handling**: PostgreSQL's `DATE` and `TIME` types become MongoDB `Date` objects. `collection_time` (stored as a string like `"14:30"`) stays as a `String` field in Mongoose since MongoDB has no separate TIME type.

4. **`recorded_by` field**: In Flask, this was `current_user.username` injected server-side. In Express, inject `req.user.username` from the JWT middleware: `{ ...req.body, recordedBy: req.user.username }`.

5. **Duplicate routes**: The Flask app has some duplicate route paths (e.g. both `/api/fly-facility/cage-monitoring` from the blueprint and `/api/facility/cage-monitoring` from `app.py`). In MERN, consolidate to one path per operation — use `/api/facility/cage-monitoring`.

6. **The `records` endpoint**: The `GET /api/records?date=&section=` endpoint queries multiple tables by date. In MongoDB, replicate this with parallel `Model.find({ <dateField>: { $gte: startOfDay, $lt: endOfDay } })` calls across all relevant models and combine the results.

7. **CORS**: In Replit, the React dev server and Express run on different ports. The Vite proxy handles this in development. In production, Express serves the React build directly and CORS is not needed.

8. **CSS and styling**: Copy `frontend/css/styles.css` and `frontend/css/auth.css` directly into `client/src/` and import them. All class names (`btn`, `form-control`, `alert`, Bootstrap classes) remain identical since Bootstrap is still being used.

9. **Images**: Copy `frontend/images/` into `client/public/images/` and reference them as `/images/logo.png` in React — Vite serves the `public/` directory at the root.

10. **Data migration**: If you have existing data in PostgreSQL that needs to move to MongoDB, use a one-time migration script that reads from PostgreSQL with `psycopg2` and inserts into MongoDB with `pymongo` or `mongoose`, transforming snake_case keys to camelCase and converting `SERIAL` integer IDs to MongoDB ObjectIds where necessary.
