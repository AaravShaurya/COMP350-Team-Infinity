# main.py
#uvicorn main:app --reload
#http://127.0.0.1:8000


from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import Base, SessionLocal, engine
from models import Voter, Vote, Candidate
from pydantic import EmailStr
from cryptography.fernet import Fernet
from collections import defaultdict
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature, BadTimeSignature
import os
import aiosmtplib
from email.message import EmailMessage
from jinja2 import Template
import datetime
from starlette.middleware.sessions import SessionMiddleware
import json
import asyncio

# Initialize app and templates
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create database tables
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Encryption key for voter anonymity
FERNET_KEY = os.getenv("FERNET_KEY")  # Ensure this environment variable is set
if not FERNET_KEY:
    raise ValueError("FERNET_KEY environment variable is not set.")
fernet = Fernet(FERNET_KEY)

# Consistent secret key for session management and token serialization
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is not set.")
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Add SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Required email components for validation
REQUIRED_EMAIL_COMPONENTS = ["sias", "krea.ac.in"]

# Email configuration (ensure sensitive info is stored securely)
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USERNAME = "easemyvote@gmail.com"
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
if not EMAIL_PASSWORD:
    raise ValueError("EMAIL_PASSWORD environment variable is not set.")

# Routes

@app.get("/", response_class=HTMLResponse)
def read_login(request: Request):
    return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": None})

@app.post("/login")
async def login(
    request: Request,
    email: EmailStr = Form(...),
    db: Session = Depends(get_db)
):
    email = email.lower().strip()  # Normalize email
    
    # Debug: Log the entered email
    print(f"Email entered: {email}")

    # Validate email components
    if not all(component in email for component in REQUIRED_EMAIL_COMPONENTS):
        print(f"Email validation failed for: {email}")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Unable to verify email."})

    # Check if voter exists
    voter = db.query(Voter).filter(Voter.email == email).first()
    if voter:
        # Check if voter has voted in the last 6 months
        if voter.has_voted:
            if voter.voted_at:
                six_months_ago = datetime.datetime.utcnow() - datetime.timedelta(days=180)
                if voter.voted_at >= six_months_ago:
                    print(f"Voter {email} has already voted in the last 6 months.")
                    return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "You have already voted in the last 6 months."})
                else:
                    # Reset voter status
                    voter.has_voted = False
                    voter.is_verified = False
                    try:
                        db.commit()
                    except Exception as e:
                        db.rollback()
                        print(f"Database commit failed: {e}")
                        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Database error."})
            else:
                # If voted_at is None, reset voting status
                voter.has_voted = False
                voter.is_verified = False
                try:
                    db.commit()
                except Exception as e:
                    db.rollback()
                    print(f"Database commit failed: {e}")
                    return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Database error."})
    else:
        print(f"Voter with email {email} does not exist in the database.")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Unable to verify email."})

    # Generate a token for email verification
    token = serializer.dumps(email, salt="email-confirm")

    # Create a verification link
    verification_link = f"http://127.0.0.1:8000/verify-email?token={token}"

    # Render the email template
    template_path = "verification_email.html"
    try:
        with open(os.path.join("templates", template_path)) as f:
            template = Template(f.read())
    except FileNotFoundError:
        print(f"Email template '{template_path}' not found.")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Email template missing."})

    email_body = template.render(email=email, verification_link=verification_link)

    # Prepare the email message
    message = EmailMessage()
    message["From"] = EMAIL_USERNAME
    message["To"] = email
    message["Subject"] = "EaseMyVote Email Verification"
    message.set_content(email_body, subtype="html")

    # Send the verification email asynchronously
    try:
        await aiosmtplib.send(
            message,
            hostname=EMAIL_HOST,
            port=EMAIL_PORT,
            start_tls=True,
            username=EMAIL_USERNAME,
            password=EMAIL_PASSWORD,
        )
        print(f"Verification email sent to {email}.")
    except Exception as e:
        print(f"Email sending failed: {e}")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Unable to send verification email."})

    return templates.TemplateResponse("email_sent.html", {"request": request})

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        # Decode the token to get the email
        email = serializer.loads(token, salt="email-confirm", max_age=3600)
        print(f"Email verified: {email}")
    except (SignatureExpired, BadSignature, BadTimeSignature) as e:
        print(f"Email verification failed: {e}")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "The verification link is invalid or has expired."})

    # Fetch the voter from the database
    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        print(f"Voter with email {email} not found during verification.")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Unable to verify email."})

    voter.is_verified = True

    # Generate and store encrypted_voter_id if not already set
    if not voter.encrypted_id:
        encrypted_voter_id = fernet.encrypt(str(voter.id).encode()).decode()
        voter.encrypted_id = encrypted_voter_id

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Database commit failed: {e}")
        return templates.TemplateResponse("Login_easemyvote.html", {"request": request, "error": "Database error during verification."})

    # Store data in session
    request.session['user_email'] = email
    request.session['rules_read'] = False

    # Redirect to the rules page
    return RedirectResponse(url="/rules", status_code=303)

@app.get("/rules", response_class=HTMLResponse)
def show_rules(request: Request):
    email = request.session.get('user_email')
    if not email:
        print("No user_email in session. Redirecting to login.")
        return RedirectResponse(url="/")
    return templates.TemplateResponse("rules.html", {"request": request})

@app.post("/rules")
def accept_rules(request: Request):
    email = request.session.get('user_email')
    if not email:
        print("No user_email in session during rules acceptance. Redirecting to login.")
        return RedirectResponse(url="/", status_code=303)

    # Mark the rules as accepted
    request.session['rules_read'] = True
    return RedirectResponse(url="/voting", status_code=303)

@app.get("/voting", response_class=HTMLResponse)
def show_voting_page(request: Request, db: Session = Depends(get_db)):
    email = request.session.get('user_email')
    rules_read = request.session.get('rules_read')

    if not email:
        print("No user_email in session when accessing voting page. Redirecting to login.")
        return RedirectResponse(url="/")
    if not rules_read:
        print("Rules not accepted yet. Redirecting to rules page.")
        return RedirectResponse(url="/rules")

    # Define the position to display
    position = "MOCC"  # Ensure this matches the position you want to display

    # Fetch candidates with case-insensitive position matching
    try:
        candidates = db.query(Candidate).filter(func.lower(Candidate.position) == position.lower()).all()
    except Exception as e:
        print(f"Error fetching candidates: {e}")
        raise HTTPException(status_code=500, detail="Error fetching candidates.")

    # Debugging: Print the list of candidates for the position
    print(f"Candidates for position '{position}': {[candidate.name for candidate in candidates]}")

    return templates.TemplateResponse("voting.html", {"request": request, "candidates": candidates, "position": position})

@app.post("/vote")
def submit_vote(
    request: Request,
    first_pref: int = Form(...),
    second_pref: int = Form(...),
    db: Session = Depends(get_db)
):
    email = request.session.get('user_email')
    if not email:
        print("Email missing in session during vote submission.")
        raise HTTPException(status_code=400, detail="Email missing")

    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        print(f"Voter with email {email} not found during vote submission.")
        return templates.TemplateResponse(
            "Login_easemyvote.html", {"request": request, "error": "Unable to verify email."}
        )

    encrypted_voter_id = voter.encrypted_id

    # Check if a vote already exists for this voter
    existing_vote = db.query(Vote).filter(Vote.encrypted_voter_id == encrypted_voter_id).first()

    preferences = {
        "first_pref": first_pref,
        "second_pref": second_pref
    }

    try:
        if existing_vote:
            # Update the existing vote
            existing_vote.preferences = json.dumps(preferences)
        else:
            # Create a new vote
            vote = Vote(
                encrypted_voter_id=encrypted_voter_id,
                preferences=json.dumps(preferences)
            )
            db.add(vote)

        voter.has_voted = True
        voter.voted_at = datetime.datetime.utcnow()
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Database commit failed during vote submission: {e}")
        raise HTTPException(status_code=500, detail="Database error during vote submission.")

    print(f"Vote submitted by {email}.")

    return RedirectResponse(url="/summary", status_code=303)

@app.get("/summary", response_class=HTMLResponse)
def show_summary(request: Request, db: Session = Depends(get_db)):
    email = request.session.get('user_email')
    if not email:
        print("No user_email in session when accessing summary page. Redirecting to login.")
        return RedirectResponse(url="/")

    # Retrieve preferences from the database
    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        print(f"Voter with email {email} not found when fetching summary.")
        return RedirectResponse(url="/")
    vote = db.query(Vote).filter(Vote.encrypted_voter_id == voter.encrypted_id).first()
    if not vote:
        print(f"Vote not found for voter {email} when fetching summary.")
        return RedirectResponse(url="/")
    preferences = json.loads(vote.preferences)

    # Retrieve candidate names
    first_pref_candidate = db.query(Candidate).filter(Candidate.id == preferences['first_pref']).first()
    second_pref_candidate = db.query(Candidate).filter(Candidate.id == preferences['second_pref']).first()

    preferences_display = {
        "first_pref": first_pref_candidate.name if first_pref_candidate else "N/A",
        "second_pref": second_pref_candidate.name if second_pref_candidate else "N/A"
    }

    return templates.TemplateResponse("summary.html", {"request": request, "preferences": preferences_display})

@app.get("/thankyou", response_class=HTMLResponse)
def thank_you(request: Request):
    return templates.TemplateResponse("thankyou.html", {"request": request})

@app.get("/results", response_class=HTMLResponse)
def get_results(request: Request, db: Session = Depends(get_db)):
    votes = db.query(Vote).all()
    all_preferences = [json.loads(vote.preferences) for vote in votes]

    # Candidates list from the database
    candidate_objs = db.query(Candidate).all()
    candidates = {str(candidate.id): candidate.name for candidate in candidate_objs}
    winner_id = instant_runoff_voting(all_preferences, list(candidates.keys()))
    winner_name = candidates.get(str(winner_id), "No winner")

    return templates.TemplateResponse("results.html", {"request": request, "winner": winner_name})

def instant_runoff_voting(votes, candidate_ids):
    while True:
        counts = defaultdict(int)
        for vote in votes:
            if vote and 'first_pref' in vote and vote['first_pref']:
                counts[str(vote['first_pref'])] += 1

        total_votes = sum(counts.values())
        for candidate_id, count in counts.items():
            if count > total_votes / 2:
                return candidate_id

        if not counts:
            return None  # No candidates left

        # Eliminate candidate with fewest votes
        least_votes_candidate = min(counts, key=counts.get)
        if least_votes_candidate not in candidate_ids:
            return None
        candidate_ids.remove(least_votes_candidate)

        # Remove eliminated candidate from votes
        for vote in votes:
            if 'first_pref' in vote and str(vote['first_pref']) == least_votes_candidate:
                # Promote second preference to first
                vote['first_pref'] = vote.get('second_pref', None)
                vote['second_pref'] = None

        if len(candidate_ids) == 1:
            return candidate_ids[0]

@app.get("/votes/{position}")
def get_votes(position: str, db: Session = Depends(get_db)):
    # Fetch candidates and votes for the given position with case-insensitive matching
    try:
        candidates = db.query(Candidate).filter(func.lower(Candidate.position) == position.lower()).all()
    except Exception as e:
        print(f"Error fetching candidates for position '{position}': {e}")
        raise HTTPException(status_code=500, detail="Error fetching candidates.")

    candidate_ids = [str(candidate.id) for candidate in candidates]
    candidate_names = {str(candidate.id): candidate.name for candidate in candidates}

    votes = db.query(Vote).all()
    vote_counts = defaultdict(int)

    for vote in votes:
        preferences = json.loads(vote.preferences)
        first_pref = str(preferences.get('first_pref'))
        if first_pref in candidate_ids:
            vote_counts[first_pref] += 1

    response_data = {
        "labels": [candidate_names[candidate_id] for candidate_id in vote_counts.keys()],
        "votes": [count for count in vote_counts.values()]
    }
    return response_data
