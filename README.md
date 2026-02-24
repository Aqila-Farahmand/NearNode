# NearNode – Smart Travel Planning

NearNode is a Django-based travel planning application that addresses the "last mile" problem and supports multi-modal trip planning with natural-language search.

## Features

### 1. Nearest Alternate Optimization

Finds cheaper flights to nearby airports and calculates total trip cost (flight + ground transport). Users enter their final address; the app evaluates airports within a configurable radius and prioritizes total journey time and cost.

### 2. Multi-Modal Connections

Goes beyond flight-to-flight connections by suggesting train links (e.g. fly into Brussels, train to Amsterdam, fly out) and scoring layovers by lounge access, sleeping pods, and city access.

### 3. AI Search

Natural-language trip search: users describe what they want (e.g. "warm beach under €300, max 5 hours from Milan"). The app parses the query and returns top matches using your flight database or Amadeus when configured.

### 4. Collaborative Planning

Couples can sync via a shared code, vote on options, and see matches that fit both preferences.

### 5. Delay Prediction & Self-Transfer Insurance

Route-level delay likelihood and self-transfer risk for unbundled connections.

## Installation

**Prerequisites:** Python 3.8+, pip

1. Clone the repo and enter the project directory.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Copy environment: `cp .env.example .env` and add your keys.
5. Run migrations: `python manage.py migrate`
6. (Optional) Create superuser: `python manage.py createsuperuser`
7. (Optional) Load airports: `python manage.py load_world_airports`
8. Start the server: `python manage.py runserver`

**Access:** Web UI at http://localhost:8000 · Admin at http://localhost:8000/admin · API at http://localhost:8000/api

## API Overview

| Feature            | Method | Endpoint                    |
|--------------------|--------|-----------------------------|
| Nearest alternate  | POST   | `/api/nearest-alternate/`   |
| Multi-modal search | POST   | `/api/multi-modal/`         |
| AI Search          | POST   | `/api/ai-search/`          |
| Collaborative      | POST/GET | `/api/collaborative/*`   |
| Delay prediction   | GET    | `/api/delay-prediction/?flight_id=...` |

Request bodies use JSON (e.g. `origin_airport_code`, `final_destination_address`, `date` for nearest alternate; `query` for AI Search). Authentication required for protected endpoints.

## Configuration

- **AI Search (LLM):** Set in `.env`: `AI_SEARCH_LLM_BACKEND=ollama` with optional `OLLAMA_BASE_URL` and `AI_SEARCH_OLLAMA_MODEL`. Without a backend, keyword-based parsing is used.
- **Real flights:** Set `AMADEUS_API_KEY` and `AMADEUS_API_SECRET` for live flight search; use `load_world_airports` so origins/destinations resolve.
- **Weather:** Optional `WEATHER_API_KEY` for destination weather in results.
- **Database:** SQLite by default; use PostgreSQL in production (see `settings.py`).

## Project Structure

- `nearnode/` – Django project settings  
- `core/` – Models, views, profile  
- `api/` – REST API (views, serializers, services)  
- `templates/` – HTML templates  
- `manage.py`, `requirements.txt`

## Tech Stack

Django, Django REST Framework, Geopy, Tailwind CSS. Optional: OpenAI-compatible LLM (Ollama/Groq/OpenAI), Amadeus API, Celery/Redis.

## License

See LICENSE.
