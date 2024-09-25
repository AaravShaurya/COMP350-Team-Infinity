import secrets
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from models import Voter, Vote
from pydantic import EmailStr
from cryptography.fernet import Fernet
import json
from collections import defaultdict
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature, BadTimeSignature
import os
import aiosmtplib
from email.message import EmailMessage
from jinja2 import Template  # Import Jinja2 Template rendering

# Initialize app and templates
app = FastAPI()
templates = Jinja2Templates(directory="templates")

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
fernet = Fernet(Fernet.generate_key())

# Use a consistent secret key that doesn't regenerate with each restart
SECRET_KEY = "your-consistent-secret-key"  # Set a fixed secret key here for consistency
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Required email components
REQUIRED_EMAIL_COMPONENTS = ["sias", "krea.ac.in"]

# Email configuration
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USERNAME = "aarav_shaurya.sias22@krea.ac.in"
EMAIL_PASSWORD = "vgmyzacfhccrdkcn"

# Routes

@app.get("/", response_class=HTMLResponse)
def read_login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
async def login(request: Request, email: EmailStr = Form(...), db: Session = Depends(get_db)):
    email = email.lower()  # Ensure email is in lowercase for consistency

    # Check if both "sias" and "krea.ac.in" are present in the email
    if not all(component in email for component in REQUIRED_EMAIL_COMPONENTS):
        # Display a generic error message
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    # Check if voter exists
    voter = db.query(Voter).filter(Voter.email == email).first()

    if voter and voter.is_verified:
        # Voter already verified, redirect to rules page
        response = RedirectResponse(url="/rules")
        response.set_cookie(key="user_email", value=email)
        return response

    # Generate a token
    token = serializer.dumps(email, salt="email-confirm")

    # Create a verification link
    verification_link = f"http://localhost:8000/verify-email?token={token}"

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
    except Exception as e:
        # If email sending fails, display a generic error message
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    # Update or create the voter in the database
    if not voter:
        voter = Voter(email=email, is_verified=False)
        db.add(voter)
    db.commit()

    # Redirect to the email_sent.html page after the email is successfully sent
    return templates.TemplateResponse("email_sent.html", {"request": request})

@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        email = serializer.loads(token, salt="email-confirm", max_age=3600)
    except (SignatureExpired, BadSignature, BadTimeSignature):
        # Display a generic error message for invalid or expired tokens
        return templates.TemplateResponse("login.html", {"request": request, "error": "The verification link is invalid or has expired."})

    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter:
        # Display a generic error message if voter not found
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    voter.is_verified = True
    db.commit()

    # Set a cookie indicating they need to read the rules
    response = RedirectResponse(url="/rules")
    response.set_cookie(key="user_email", value=email)
    response.set_cookie(key="rules_read", value="false")
    return response

@app.get("/rules", response_class=HTMLResponse)
def show_rules(request: Request):
    email = request.cookies.get("user_email")
    if not email:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("rules.html", {"request": request})

@app.post("/rules")
def accept_rules(request: Request):
    email = request.cookies.get("user_email")
    if not email:
        return RedirectResponse(url="/")

    # Mark the rules as accepted
    response = RedirectResponse(url="/voting")
    response.set_cookie(key="rules_read", value="true")
    return response

@app.get("/voting", response_class=HTMLResponse)
def show_voting_page(request: Request):
    email = request.cookies.get("user_email")
    rules_read = request.cookies.get("rules_read")

    if not email:
        return RedirectResponse(url="/")
    if rules_read != "true":
        return RedirectResponse(url="/rules")
    return templates.TemplateResponse("voting.html", {"request": request})

@app.post("/vote")
def submit_vote(request: Request, first_pref: str = Form(...), second_pref: str = Form(...), db: Session = Depends(get_db)):
    email = request.cookies.get("user_email")
    if not email:
        raise HTTPException(status_code=400, detail="Email missing")

    voter = db.query(Voter).filter(Voter.email == email).first()
    if not voter or voter.has_voted:
        # Display a generic error message
        return templates.TemplateResponse("login.html", {"request": request, "error": "Unable to verify email."})

    encrypted_voter_id = fernet.encrypt(str(voter.id).encode()).decode()

    preferences = {
        "first_pref": first_pref,
        "second_pref": second_pref
    }

    vote = Vote(
        encrypted_voter_id=encrypted_voter_id,
        preferences=json.dumps(preferences)
    )
    db.add(vote)
    voter.has_voted = True
    voter.encrypted_id = encrypted_voter_id
    db.commit()

    response = RedirectResponse(url="/summary")
    return response

@app.get("/summary", response_class=HTMLResponse)
def show_summary(request: Request):
    email = request.cookies.get("user_email")
    if not email:
        return RedirectResponse(url="/")

    # Retrieve preferences from the database
    db = next(get_db())
    voter = db.query(Voter).filter(Voter.email == email).first()
    vote = db.query(Vote).filter(Vote.encrypted_voter_id == voter.encrypted_id).first()
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
