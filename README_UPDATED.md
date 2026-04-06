# 🌟 StoryMe

> ✨ Transform photos into magical personalized storybooks

---

## 🧱 Architecture Diagram

![Architecture](https://raw.githubusercontent.com/ashishps1/awesome-system-design-resources/main/diagrams/microservices-architecture.png)

---

## 🚀 High-Level Architecture

```
User (📱 Browser / Mobile)
        ↓
Frontend (⚛️ React - Azure Static Web Apps)
        ↓
Backend API (🚀 FastAPI - Azure App Service)
        ↓
Storage Layer (🧩 Pluggable)
    ├── ☁️ Azure Blob Storage (Production)
    └── 💻 Local Storage (Development)
```

---

## 🔐 Authentication Flow (OTP)

### ✅ Current (Simulated OTP)

```
User enters phone 📱
        ↓
Frontend → /send-otp
        ↓
Backend generates OTP 🔢
        ↓
Stored in memory 🧠
        ↓
[SIMULATED SMS → Logs]
        ↓
User enters OTP
        ↓
Frontend → /verify-otp
        ↓
Backend validates
        ↓
✅ Authenticated
```

---

### 🔄 Future (Real OTP)

```
Backend → SMS Provider (Twilio / MSG91)
        ↓
User receives OTP 📲
        ↓
Verification
```

---

## 🧠 Storage Design

```
Storage Interface
    ├── LocalStorage 💻
    └── AzureBlobStorage ☁️
```

---

## ⚙️ Deployment (Azure)

| Layer | Service |
|------|--------|
| Frontend | Azure Static Web Apps ⚛️ |
| Backend | Azure App Service 🚀 |
| Storage | Azure Blob Storage ☁️ |
| CI/CD | GitHub Actions 🔁 |

---

## 🔁 CI/CD Flow

```
Push → GitHub Actions
   ├── Frontend Deploy
   └── Backend Deploy
```

---

## 📦 Features

- 🎨 Story generation
- 🧒 Face overlay
- 📄 PDF creation
- 🔐 OTP login
- ☁️ Cloud storage

---

## 🧪 Local vs Cloud

| Feature | Local | Azure |
|--------|------|-------|
| Storage | Local FS | Blob |
| OTP | Simulated | Real (future) |
| Hosting | Local | Public |

---

## 🧱 Backend Modules

```
FastAPI
  ├── Auth 🔐
  ├── Story 📖
  ├── Image 🎨
  ├── PDF 📄
  └── Storage ☁️
```

---

## 🚀 Future

- Real OTP
- Payments
- Async processing
- CDN

---

## 🧑‍💻 Tech Stack

- ⚛️ React
- 🐍 FastAPI
- ☁️ Azure
- 🔁 GitHub Actions

---

✨ Built with vision by Shantanu Desai
