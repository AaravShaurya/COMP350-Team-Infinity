# main.py
#uvicorn main:app --reload
#http://127.0.0.1:8000

# main.py

# main.py

from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, engine
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

# Initialize app and templates
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create database tables
from models import Voter, Vote  # Ensure models are imported before creating tables
from database import Base  # Import Base after models
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Encryption key for voter anonymity
FERNET_KEY = os.getenv("FERNET_KEY")  # Set this environment variable
if not FERNET_KEY:
    raise ValueError("FERNET_KEY environment variable is not set.")
fernet = Fernet(FERNET_KEY)

# Use a consistent secret key that doesn't regenerate with each restart
SECRET_KEY = os.getenv("SECRET_KEY")  # Set this environment variable
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is not set.")
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Add SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Required email components
REQUIRED_EMAIL_COMPONENTS = ["sias", "krea.ac.in"]

# Email configuration (store sensitive info securely)
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USERNAME = "easemyvote@gmail.com"
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # Get password from environment variable
if not EMAIL_PASSWORD:
    raise ValueError("EMAIL_PASSWORD environment variable is not set.")

# Routes

@app.get("/", response_class=HTMLResponse)
def read_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
async def login(
    request: Request,
    email: EmailStr = Form(...),
    db: Session = Depends(get_db)
):
    email = email.lower().strip()  # Ensure email is in lowercase and stripped of whitespace

    # Log the email for debugging
    print(f"Email entered: {email}")

    # Check if both "sias" and "krea.ac.in" are present in the email
    if not all(component in email for component in REQUIRED_EMAIL_COMPONENTS):
        print(f"Email validation failed for: {email}")
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    # Check if voter exists
    voter = db.query(Voter).filter(Voter.email == email).first()
    if voter:
        # Check if voter has voted in the last 6 months
        if voter.has_voted:
            if voter.voted_at:
                six_months_ago = datetime.datetime.utcnow() - datetime.timedelta(days=180)
                if voter.voted_at >= six_months_ago:
                    print(f"Voter {email} has already voted in the last 6 months.")
                    return templates.TemplateResponse("login.html", {"request": request, "error": "You have already voted in the last 6 months."})
                else:
                    # Reset voter status
                    voter.has_voted = False
                    voter.is_verified = False
                    db.commit()
            else:
                # If voted_at is None, reset voting status
                voter.has_voted = False
                voter.is_verified = False
                db.commit()
    else:
        print(f"Voter with email {email} does not exist in the database.")
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    # Generate a token
    token = serializer.dumps(email, salt="email-confirm")

    # Create a verification link
    verification_link = f"http://127.0.0.1:8000/verify-email?token={token}"

    # Render the email template
    template_path = "verification_email.html"
    with open(os.path.join("templates", template_path)) as f:
        template = Template(f.read())

    email_body = template.render(email=email, verification_link=verification_link)

    # Send the verification email using aiosmtplib
    message = EmailMessage()
    message["From"] = EMAIL_USERNAME
    message["To"] = email
    message["Subject"] = "EaseMyVote Email Verification"
    message.set_content(email_body, subtype="html")

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
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    return templates.TemplateResponse("email_sent.html", {"request": request})

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        email = serializer.loads(token, salt="email-confirm", max_age=3600)
        print(f"Email verified: {email}")
    except (SignatureExpired, BadSignature, BadTimeSignature) as e:
        print(f"Email verification failed: {e}")
        return templates.TemplateResponse("login.html", {"request": request, "error": "The verification link is invalid or has expired."})

    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        print(f"Voter with email {email} not found during verification.")
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    voter.is_verified = True

    # Generate and store encrypted_voter_id if not already set
    if not voter.encrypted_id:
        encrypted_voter_id = fernet.encrypt(str(voter.id).encode()).decode()
        voter.encrypted_id = encrypted_voter_id

    db.commit()

    # Store data in session
    request.session['user_email'] = email
    request.session['rules_read'] = False

    # Render the rules page directly
    return templates.TemplateResponse("rules.html", {"request": request})

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
def show_voting_page(request: Request):
    email = request.session.get('user_email')
    rules_read = request.session.get('rules_read')

    if not email:
        print("No user_email in session when accessing voting page. Redirecting to login.")
        return RedirectResponse(url="/")
    if not rules_read:
        print("Rules not accepted yet. Redirecting to rules page.")
        return RedirectResponse(url="/rules")
    return templates.TemplateResponse("voting.html", {"request": request})

@app.post("/vote")
def submit_vote(
    request: Request,
    first_pref: str = Form(...),
    second_pref: str = Form(...),
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
            "login.html", {"request": request, "error": "Unable to verify email."}
        )
    if voter.has_voted:
        print(f"Voter with email {email} has already voted.")
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "You have already voted."}
        )

    encrypted_voter_id = voter.encrypted_id

    # Check if a vote already exists for this voter
    existing_vote = db.query(Vote).filter(Vote.encrypted_voter_id == encrypted_voter_id).first()

    preferences = {
        "first_pref": first_pref,
        "second_pref": second_pref
    }

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

    print(f"Vote submitted by {email}.")

    return RedirectResponse(url="/summary", status_code=303)

@app.get("/summary", response_class=HTMLResponse)
def show_summary(request: Request):
    email = request.session.get('user_email')
    if not email:
        print("No user_email in session when accessing summary page. Redirecting to login.")
        return RedirectResponse(url="/")

    # Retrieve preferences from the database
    db = next(get_db())
    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        print(f"Voter with email {email} not found when fetching summary.")
        return RedirectResponse(url="/")
    vote = db.query(Vote).filter(Vote.encrypted_voter_id == voter.encrypted_id).first()
    if not vote:
        print(f"Vote not found for voter {email} when fetching summary.")
        return RedirectResponse(url="/")
    preferences = json.loads(vote.preferences)

    return templates.TemplateResponse("summary.html", {"request": request, "preferences": preferences})

@app.get("/thankyou", response_class=HTMLResponse)
def thank_you(request: Request):
    return templates.TemplateResponse("thankyou.html", {"request": request})

@app.get("/results", response_class=HTMLResponse)
def get_results(request: Request, db: Session = Depends(get_db)):
    votes = db.query(Vote).all()
    all_preferences = [json.loads(vote.preferences) for vote in votes]

    # Candidates list (Should be dynamic or from DB)
    candidates = ["Candidate 1", "Candidate 2", "Candidate 3"]
    winner = instant_runoff_voting(all_preferences, candidates)
    return templates.TemplateResponse("results.html", {"request": request, "winner": winner})

def instant_runoff_voting(votes, candidates):
    while True:
        counts = defaultdict(int)
        for vote in votes:
            if vote and 'first_pref' in vote and vote['first_pref']:
                counts[vote['first_pref']] += 1

        total_votes = sum(counts.values())
        for candidate, count in counts.items():
            if count > total_votes / 2:
                return candidate

        # Eliminate candidate with fewest votes
        least_votes_candidate = min(counts, key=counts.get)
        candidates.remove(least_votes_candidate)

        # Remove eliminated candidate from votes
        for vote in votes:
            if 'first_pref' in vote and vote['first_pref'] == least_votes_candidate:
                # Promote second preference to first
                vote['first_pref'] = vote.get('second_pref', None)
                vote['second_pref'] = None

        if len(candidates) == 1:
            return candidates[0]
        
@app.get("/votes/{position}")
def get_votes(position: str):
    db: Session = SessionLocal()
    votes = db.query(Candidate.name, Vote.vote_count).join(Vote).filter(Candidate.position == position).all()
    db.close()
    
    # Format the data into a dict format suitable for frontend consumption
    response_data = {
        "labels": [candidate_name for candidate_name, _ in votes],
        "votes": [vote_count for _, vote_count in votes]
    }
    return response_data
