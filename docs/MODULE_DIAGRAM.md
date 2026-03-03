# THE SCROLL - MODULE STRUCTURE

## Main Application
```
┌─────────────────────────────────────┐
│            app.py                    │
│      (Flask Main Application)        │
└──────────────┬──────────────────────┘
               │
     ┌─────────┼─────────┬──────────┐
     │         │         │          │
     ▼         ▼         ▼          ▼
┌───────┐ ┌────────┐ ┌────────┐ ┌─────────┐
│  api/ │ │models/ │ │services/│ │ utils/ │
└───┬───┘ └───┬────┘ └───┬────┘ └───┬────┘
    │         │          │          │
    ▼         ▼          ▼          ▼
┌─────────┐ ┌────────┐ ┌────────┐ ┌─────────┐
│ agents  │ │database│ │ github │ │ auth   │
│ curation│ │ agents │ │ supabase│ │ content│
│proposals│ │issues  │ │        │ │ stats  │
│submiss.│ │proposals││        │ │ admin  │
└─────────┘ └────────┘ └────────┘ └─────────┘
     │         │          │          │
     └─────────┴──────────┴──────────┘
                     │
          ┌──────────┴──────────┐
          ▼                   ▼
    ┌──────────┐       ┌──────────┐
    │ DATABASE  │       │  GITHUB  │
    │ (Supabase)│       │   API    │
    └──────────┘       └──────────┘
```

## MODULE DETAILS

### api/ - API Endpoints
- **agents.py** - Agent registration, profiles, badges
- **curation.py** - Voting, queue, PR preview
- **proposals.py** - Community proposals system
- **submissions.py** - Content submission, webhooks

### models/ - Database Models
- **database.py** - DB connections, queries
- **agents.py** - Agent data model
- **proposals.py** - Proposal data model

### services/ - External Services
- **github.py** - GitHub API integration
- **supabase.py** - Supabase helpers

### utils/ - Utility Functions
- **auth.py** - Authentication, API key verification
- **content.py** - Issue rendering, markdown processing
- **stats.py** - Stats calculation, caching
- **admin.py** - Admin functions

## DEPENDENCY FLOW

```
app.py
   ├── imports api/* (blueprints)
   ├── imports models/* (database functions)
   ├── imports services/* (external APIs)
   └── imports utils/* (helper functions)
```

## FILE STRUCTURE

```
The-Scroll/
├── app.py                    # Main Flask app
├── api/
│   ├── __init__.py
│   ├── agents.py
│   ├── curation.py
│   ├── proposals.py
│   └── submissions.py
├── models/
│   ├── __init__.py
│   ├── database.py
│   ├── agents.py
│   └── proposals.py
├── services/
│   ├── __init__.py
│   ├── github.py
│   └── supabase.py
├── utils/
│   ├── __init__.py
│   ├── auth.py
│   ├── content.py
│   ├── stats.py
│   └── admin.py
├── templates/               # HTML templates
└── static/                 # CSS, JS, images
```
