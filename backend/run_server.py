from pathlib import Path
from dotenv import load_dotenv

# Load backend/.env before importing the Flask app.
load_dotenv(Path(__file__).resolve().parent / ".env")
from app import app

if __name__ == "__main__":
    app.run(debug=True)
