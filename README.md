# NearNode - Smart Travel Planning Platform

NearNode is a Django-based travel planning application that solves the "last mile" problem and provides multi-modal trip planning with smart search capabilities.

## Features

### 1. Nearest Alternate Optimization

While most apps search for a specific city, NearNode solves the "last mile" problem by finding cheaper flights to nearby airports and calculating the total trip cost (flight + ground transport).

**Example**: Flying to London Heathrow might be expensive, but flying to London Stansted or Southampton might be half the price and only 30 minutes longer by train.

- **True Destination Radius Search**: Users input their final street address, and the app calculates total time and cost for all airports within a 100km radius
- **Prioritizes Total Trip Cost and Time**: Not just flight ticket price, but the complete journey

### 2. Multi-Modal Connection Logic

Instead of just flight-to-flight connections, NearNode integrates "Hacker Connections" with train links.

- **Train-Link Suggestions**: If a flight connection is 6 hours long, the app suggests flying into Brussels, taking a 1-hour high-speed train to Amsterdam, and flying out from there
- **Layover Quality Scores**: Rankings based on lounge access, airport sleeping pods, or ease of quick city visits during wait times

### 3. AI-Driven "Vibe" Search

Move away from "Where to?" and toward "What for?"

- **Natural Language Processing**: Users describe their dream trip in plain language
- **Example Query**: "I want a warm beach destination within a 5-hour flight of Milan for under €300 this weekend"
- **Smart Parsing**: The app parses weather, flight prices, and distance simultaneously to provide "Top 3 Matches"

### 4. Collaborative Mode ("Husband & Wife" Feature)

Perfect for couples planning trips together.

- **Joint Trip Voting**: Two users sync their apps with a unique code
- **Swipe-Style Voting**: Users "swipe right" on flights they like
- **Perfect Match Detection**: The app highlights options that fit both users' budgets and schedules

### 5. Predictive Delay Protection & Self-Transfer Insurance

Smart features for risk management.

- **Delay Prediction**: Uses historical data to predict delay likelihood for specific routes
- **Self-Transfer Insurance**: Notifies users if they have enough time to manually collect bags and re-check them for cheaper "unbundled" flight connections
- **Risk Assessment**: Calculates self-transfer risk based on layover time and delay probabilities

## Installation

### Prerequisites

- Python 3.8+
- pip
- (Optional) Redis for Celery tasks

### Setup

1. **Clone the repository**

   ```bash
   cd NearNode
   ```

2. **Create virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**

   ```bash
   cp .env.example .env
   # Edit .env and add your API keys
   ```

5. **Run migrations**

   ```bash
   python manage.py migrate
   ```

6. **Create superuser (optional)**

   ```bash
   python manage.py createsuperuser
   ```

7. **Load sample data (optional)**

   ```bash
   python manage.py load_sample_data
   ```

8. **Run development server**

   ```bash
   python manage.py runserver
   ```

9. **Access the application**
   - Web UI: http://localhost:8000
   - Admin Panel: http://localhost:8000/admin
   - API: http://localhost:8000/api

## API Endpoints

### Nearest Alternate Search

```
POST /api/nearest-alternate/
Body: {
    "origin_airport_code": "MIL",
    "final_destination_address": "123 Main St, London",
    "date": "2024-06-15",
    "radius_km": 100
}
```

### Multi-Modal Search

```
POST /api/multi-modal/
Body: {
    "origin_airport_code": "BRU",
    "destination_airport_code": "AMS",
    "date": "2024-06-15"
}
```

### AI Vibe Search

```
POST /api/vibe-search/
Body: {
    "query": "I want a warm beach destination within a 5-hour flight of Milan for under €300 this weekend"
}
```

### Collaborative Features

```
POST /api/collaborative/generate-code/  # Generate sync code
POST /api/collaborative/link-partner/   # Link partner account
POST /api/collaborative/vote/           # Vote on trip option
GET  /api/collaborative/matches/        # Get perfect matches
```

### Delay Prediction

```
GET /api/delay-prediction/?flight_id=1
POST /api/self-transfer-check/
Body: {
    "connection_id": 1
}
```

## Project Structure

```
NearNode/
├── nearnode/          # Django project settings
├── core/              # Core models and business logic
│   ├── models.py      # Database models
│   └── admin.py       # Admin interface
├── api/               # API endpoints
│   ├── views.py       # API views
│   ├── serializers.py # DRF serializers
│   ├── services.py    # Business logic services
│   └── urls.py        # API URL routing
├── templates/         # HTML templates
├── static/            # Static files
├── manage.py          # Django management script
└── requirements.txt   # Python dependencies
```

## Configuration

### Required API Keys (in .env)

- `OPENAI_API_KEY`: For AI-driven vibe search (optional, has fallback)
- `FLIGHT_API_KEY`: For real flight data (you'll need to integrate with a flight API)
- `WEATHER_API_KEY`: For weather-based destination matching (optional)

### Database

Default is SQLite for development. For production, configure PostgreSQL in `settings.py`.

## Development

### Running Tests

```bash
python manage.py test
```

### Creating Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### Accessing Admin

1. Create superuser: `python manage.py createsuperuser`
2. Visit: http://localhost:8000/admin

## Technologies Used

- **Django 4.2**: Web framework
- **Django REST Framework**: API development
- **Geopy**: Geocoding and distance calculations
- **OpenAI API**: Natural language processing (optional)
- **PostgreSQL/SQLite**: Database
- **Celery & Redis**: Async task processing (optional)
- **Tailwind CSS**: Modern UI styling

## Future Enhancements

- Integration with real flight booking APIs (Amadeus, Skyscanner, etc.)
- Real-time flight price tracking
- Weather API integration for destination matching
- Mobile app (React Native)
- Advanced machine learning for delay prediction
- Integration with train/bus booking systems

## License

See LICENSE file for details.

## Contributing

This is a personal project, but suggestions and improvements are welcome!

## Authors

Built for smart travelers who want to optimize their journey, not just their flight ticket.
